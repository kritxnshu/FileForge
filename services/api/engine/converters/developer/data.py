"""Structured data conversion for uploaded files: JSON ↔ XML ↔ YAML ↔ TOML, CSV/TSV ↔ JSON, CSV → SQL.

XML mapping (documented in docs/ARCHITECTURE.md):
  * attributes become "@name" keys, element text becomes "#text" (or a plain string when the
    element has only text), repeated child elements become arrays
  * XML needs exactly one root element: JSON/YAML/TOML with one top-level key uses it as the
    root; anything else is wrapped in <root>, and arrays become repeated <item> elements
Parsing is hardened: XML via defusedxml (no DTDs, entities or external references), YAML via
a SafeLoader that caps aliases and the expanded size (alias bombs), plus input size limits.
"""

from __future__ import annotations

import csv
import io
import json
import re
import tomllib
import xml.etree.ElementTree as ET
from typing import Any, Literal

import yaml
from defusedxml import ElementTree as DET
from pydantic import Field

from ...context import ConversionError, Ctx
from ...registry import Operation, Options, register, ui

MAX_BYTES = 20 * 1024 * 1024
MAX_NODES = 2_000_000
MAX_ALIASES = 1000
MAX_DEPTH = 200


class _Loader(yaml.SafeLoader):
    aliases = 0

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            self.aliases += 1
            if self.aliases > MAX_ALIASES:
                raise ConversionError("too_large", "This YAML uses too many aliases (possible alias bomb).")
        return super().compose_node(parent, index)


def _budget(obj: Any) -> None:
    """Walk the (alias-expanded) structure with a node and depth budget."""
    count = 0
    stack: list[tuple[Any, int]] = [(obj, 0)]
    while stack:
        cur, depth = stack.pop()
        count += 1
        if count > MAX_NODES:
            raise ConversionError("too_large", "This data expands to too many values to convert safely.")
        if depth > MAX_DEPTH:
            raise ConversionError("too_large", "This data is nested too deeply to convert.")
        if isinstance(cur, dict):
            stack.extend((v, depth + 1) for v in cur.values())
        elif isinstance(cur, list):
            stack.extend((v, depth + 1) for v in cur)


def _text(ctx: Ctx) -> str:
    raw = ctx.input.path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ConversionError("too_large", f"Data files can be at most {MAX_BYTES // (1024 * 1024)} MB.")
    from .._text import decode

    return decode(raw)


# ---------------------------------------------------------------------------
# XML <-> tree


def xml_to_obj(text: str) -> dict:
    try:
        root = DET.fromstring(text.encode("utf-8"), forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DET.ParseError as e:
        raise ConversionError("corrupt_input", f"This isn't valid XML ({e}).") from e
    except Exception as e:  # defusedxml raises DTDForbidden / EntitiesForbidden etc.
        raise ConversionError("unsafe_input", "XML with DTDs or entities isn't accepted, for security reasons.") from e

    def tag(t: str) -> str:
        return t.split("}", 1)[-1] if t.startswith("{") else t

    def conv(el) -> Any:
        node: dict[str, Any] = {f"@{tag(k)}": v for k, v in el.attrib.items()}
        children = list(el)
        for ch in children:
            k = tag(ch.tag)
            v = conv(ch)
            if k in node:
                if not isinstance(node[k], list):
                    node[k] = [node[k]]
                node[k].append(v)
            else:
                node[k] = v
        text = (el.text or "").strip()
        if text:
            if not node:
                return text
            node["#text"] = text
        return node if node else None

    return {tag(root.tag): conv(root)}


_NAME = re.compile(r"^[A-Za-z_][\w.-]*$")


def obj_to_xml(obj: Any, ctx: Ctx, indent: bool = True) -> str:
    if isinstance(obj, dict) and len(obj) == 1 and _NAME.match(str(next(iter(obj)))) and not str(next(iter(obj))).startswith(("@", "#")):
        root_name, value = next(iter(obj.items()))
    else:
        root_name, value = "root", obj
        ctx.notice("XML needs a single root element, so the data was wrapped in <root>.")

    def safe(name: str) -> str:
        n = re.sub(r"[^\w.-]", "_", str(name)) or "_"
        return n if _NAME.match(n) else "_" + n

    def build(parent, name, val):
        if isinstance(val, list):
            for item in val:
                build(parent, name, item)
            return
        el = ET.SubElement(parent, safe(name)) if parent is not None else ET.Element(safe(name))
        fill(el, val)
        return el

    def fill(el, val):
        if isinstance(val, dict):
            for k, v in val.items():
                k = str(k)
                if k.startswith("@"):
                    el.set(safe(k[1:]), "" if v is None else _scalar(v))
                elif k == "#text":
                    el.text = "" if v is None else _scalar(v)
                else:
                    build(el, k, v)
        elif isinstance(val, list):
            for item in val:
                build(el, "item", item)
        elif val is not None:
            el.text = _scalar(val)

    root = ET.Element(safe(root_name))
    fill(root, value)
    if indent:
        ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


# ---------------------------------------------------------------------------
# tabular


def csv_to_records(text: str, delim: str) -> list[dict]:
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not rows:
        return []
    head = rows[0]
    return [dict(zip(head, r + [""] * (len(head) - len(r)))) for r in rows[1:]]


def records_to_rows(obj: Any) -> tuple[list[str], list[list[Any]]]:
    if not isinstance(obj, list) or not all(isinstance(x, dict) for x in obj):
        raise ConversionError("invalid_input", "To make CSV, the JSON must be an array of objects, like [{\"a\": 1}, …].")
    from ..spreadsheets.sheets import _flatten

    return _flatten(obj)


# ---------------------------------------------------------------------------


class DataOptions(Options):
    indent: int = Field(2, ge=0, le=8, title="Indent", description="Spaces per level (0 = compact).",
                        json_schema_extra=ui(targets=("json", "xml", "yaml")))
    neutralize_formulas: bool = Field(True, title="Protect against formula injection",
                                      description="Prefix cells starting with = + - @ so spreadsheet apps don't run them.",
                                      json_schema_extra=ui(targets=("csv", "tsv")))


TREE = ("json", "xml", "yaml", "toml")


def parse(ctx: Ctx, fmt: str, text: str) -> Any:
    try:
        if fmt == "json":
            return json.loads(text)
        if fmt == "yaml":
            loader = _Loader(text)
            try:
                return loader.get_single_data()
            finally:
                loader.dispose()
        if fmt == "toml":
            return tomllib.loads(text)
        if fmt == "xml":
            return xml_to_obj(text)
        if fmt in ("csv", "tsv"):
            return csv_to_records(text, "\t" if fmt == "tsv" else ",")
    except ConversionError:
        raise
    except json.JSONDecodeError as e:
        raise ConversionError("corrupt_input", f"This isn't valid JSON: {e.msg} at line {e.lineno}, column {e.colno}.") from e
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise ConversionError("corrupt_input", f"This isn't valid YAML{where}.") from e
    except tomllib.TOMLDecodeError as e:
        raise ConversionError("corrupt_input", f"This isn't valid TOML ({e}).") from e
    raise ConversionError("unsupported", f"Can't read {fmt}.")


def _strip_none(o: Any, dropped: list[int]) -> Any:
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if v is None:
                dropped[0] += 1
                continue
            out[str(k)] = _strip_none(v, dropped)
        return out
    if isinstance(o, list):
        return [_strip_none(v, dropped) for v in o if v is not None]
    return o


def dump(ctx: Ctx, fmt: str, obj: Any, o: DataOptions) -> str:
    import datetime as dt

    def default(v):
        if isinstance(v, (dt.date, dt.datetime, dt.time)):
            return v.isoformat()
        return str(v)

    if fmt == "json":
        return json.dumps(obj, ensure_ascii=False, indent=o.indent or None, default=default,
                          separators=None if o.indent else (",", ":")) + "\n"
    if fmt == "yaml":
        return yaml.safe_dump(json.loads(json.dumps(obj, default=default)), allow_unicode=True, sort_keys=False,
                              indent=max(2, o.indent or 2))
    if fmt == "toml":
        import tomli_w

        if not isinstance(obj, dict):
            obj = {"items": obj} if isinstance(obj, list) else {"value": obj}
            ctx.notice("TOML needs a table at the top level, so the data was put under a key.")
        dropped = [0]
        obj = _strip_none(obj, dropped)
        if dropped[0]:
            ctx.notice(f"TOML has no null value; {dropped[0]} empty value{'s were' if dropped[0] != 1 else ' was'} left out.")
        try:
            return tomli_w.dumps(obj)
        except (TypeError, ValueError) as e:
            raise ConversionError("invalid_input", f"This data can't be represented in TOML ({e}).") from e
    if fmt == "xml":
        return obj_to_xml(obj, ctx, indent=bool(o.indent))
    if fmt in ("csv", "tsv"):
        from ..spreadsheets.sheets import neutralize

        head, rows = records_to_rows(obj)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter="\t" if fmt == "tsv" else ",")
        w.writerow(head)
        for r in rows:
            w.writerow(["" if v is None else (neutralize(v) if o.neutralize_formulas else v) for v in r])
        return buf.getvalue()
    raise ConversionError("unsupported", f"Can't write {fmt}.")


def data_convert(ctx: Ctx) -> None:
    o: DataOptions = ctx.options  # type: ignore[assignment]
    ctx.stage("Parsing")
    obj = parse(ctx, ctx.input.format, _text(ctx))
    _budget(obj)
    ctx.stage("Writing")
    out = ctx.default_out()
    out.write_text(dump(ctx, ctx.target, obj, o), encoding="utf-8")
    if ctx.input.format == "xml" or ctx.target == "xml":
        ctx.notice("XML attributes map to “@name” keys and element text to “#text”.")
    ctx.add_output(out)


_PAIRS = tuple((s, t) for s in TREE for t in TREE if s != t) + (
    ("csv", "json"), ("tsv", "json"), ("json", "csv"), ("json", "tsv"), ("csv", "yaml"), ("tsv", "yaml"))

register(Operation(
    id="data.convert", category="developer", label="Convert data file",
    description="Convert structured data files between JSON, XML, YAML, TOML, CSV and TSV.",
    inputs=(*TREE, "csv", "tsv"), outputs=(*TREE, "csv", "tsv"), cardinality="one_to_one", options=DataOptions,
    run=data_convert, explicit_pairs=_PAIRS,
    pair_limitations={**{(s, "xml"): ("XML needs one root element; other shapes are wrapped in <root>.",) for s in TREE if s != "xml"},
                      **{(s, "toml"): ("TOML has no null; empty values are dropped.",) for s in TREE if s != "toml"},
                      **{("json", t): ("JSON must be an array of objects; nested objects become dotted columns.",) for t in ("csv", "tsv")}},
    keywords=("json to yaml", "xml to json", "config"),
))


# ---------------------------------------------------------------------------
# CSV → SQL


class SqlOptions(Options):
    table: str = Field("my_table", pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$", title="Table name")
    dialect: Literal["postgres", "mysql", "sqlite", "sqlserver"] = Field("postgres", title="SQL dialect")
    create_table: bool = Field(True, title="Include CREATE TABLE")
    batch_size: int = Field(100, ge=1, le=1000, title="Rows per INSERT", json_schema_extra=ui(advanced=True))


def quote_ident(name: str, dialect: str) -> str:
    if dialect == "mysql":
        return "`" + name.replace("`", "``") + "`"
    if dialect == "sqlserver":
        return "[" + name.replace("]", "]]") + "]"
    return '"' + name.replace('"', '""') + '"'


def sql_literal(v: str) -> str:
    if v == "":
        return "NULL"
    if re.fullmatch(r"-?(0|[1-9]\d{0,17})(\.\d+)?", v):
        return v
    return "'" + v.replace("'", "''") + "'"


def csv_to_sql_text(text: str, delim: str, o: SqlOptions) -> tuple[str, int]:
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if len(rows) < 1 or not rows[0]:
        raise ConversionError("invalid_input", "This CSV has no header row.")
    head = rows[0]
    body = [r + [""] * (len(head) - len(r)) for r in rows[1:]]
    cols = ", ".join(quote_ident(h or f"column_{i + 1}", o.dialect) for i, h in enumerate(head))
    tbl = quote_ident(o.table, o.dialect)
    out = []
    if o.create_table:
        def typ(i: int) -> str:
            vals = [r[i] for r in body if r[i] != ""]
            if vals and all(re.fullmatch(r"-?\d{1,18}", v) for v in vals):
                return "BIGINT" if o.dialect != "sqlite" else "INTEGER"
            if vals and all(re.fullmatch(r"-?\d+(\.\d+)?", v) for v in vals):
                return "NUMERIC" if o.dialect != "sqlite" else "REAL"
            return {"mysql": "TEXT", "sqlserver": "NVARCHAR(MAX)"}.get(o.dialect, "TEXT")

        defs = ",\n  ".join(f"{quote_ident(h or f'column_{i + 1}', o.dialect)} {typ(i)}" for i, h in enumerate(head))
        out.append(f"CREATE TABLE {tbl} (\n  {defs}\n);\n")
    for k in range(0, len(body), o.batch_size):
        chunk = body[k:k + o.batch_size]
        values = ",\n  ".join("(" + ", ".join(sql_literal(v) for v in r[: len(head)]) + ")" for r in chunk)
        out.append(f"INSERT INTO {tbl} ({cols}) VALUES\n  {values};\n")
    return "\n".join(out), len(body)


def csv_to_sql(ctx: Ctx) -> None:
    o: SqlOptions = ctx.options  # type: ignore[assignment]
    sql, n = csv_to_sql_text(_text(ctx), "\t" if ctx.input.format == "tsv" else ",", o)
    out = ctx.default_out("sql")
    out.write_text(sql, encoding="utf-8")
    ctx.notice(f"Generated INSERT statements for {n} row{'s' if n != 1 else ''}.")
    ctx.add_output(out, "sql")


register(Operation(
    id="data.csv_to_sql", category="developer", label="CSV to SQL INSERT",
    description="Generate CREATE TABLE and INSERT statements from a CSV file, with correct quoting for your database.",
    inputs=("csv", "tsv"), outputs=("sql",), cardinality="one_to_one", options=SqlOptions, run=csv_to_sql,
    keywords=("insert statements", "database", "import"),
))
