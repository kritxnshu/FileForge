"""Spreadsheets: export sheets to CSV/TSV/JSON, import CSV/TSV/JSON, convert between
XLSX/XLS/ODS and print to PDF (LibreOffice)."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
from pathlib import Path
from typing import Any

from pydantic import Field

from ... import office
from ...context import ConversionError, Ctx
from ...registry import NoOptions, Operation, Options, register, ui

BOOKS = ("xlsx", "xls", "ods")
INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def neutralize(v: Any) -> Any:
    """CSV formula-injection guard: prefix text that a spreadsheet app would treat as a formula."""
    if isinstance(v, str) and v[:1] in INJECTION_PREFIXES:
        try:
            float(v)
            return v  # a plain negative/positive number
        except ValueError:
            return "'" + v
    return v


def _plain(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if hasattr(v, "item"):  # numpy scalar
        return _plain(v.item())
    return v


def read_book(ctx: Ctx, path: Path, fmt: str) -> tuple[list[tuple[str, list[list[Any]]]], int]:
    """All sheets as (name, rows of computed values). Also returns #formula cells with no saved result."""
    missing = 0
    try:
        if fmt == "xlsx":
            from openpyxl import load_workbook

            wb = load_workbook(str(path), data_only=True, read_only=True)
            wbf = load_workbook(str(path), data_only=False, read_only=True)
            sheets = []
            for ws, wsf in zip(wb.worksheets, wbf.worksheets):
                rows = []
                for r, rf in zip(ws.iter_rows(values_only=True), wsf.iter_rows(values_only=True)):
                    for v, f in zip(r, rf):
                        if v is None and isinstance(f, str) and f.startswith("="):
                            missing += 1
                    rows.append([_plain(v) for v in r])
                sheets.append((ws.title, rows))
            return sheets, missing
        if fmt == "xls":
            import xlrd

            book = xlrd.open_workbook(str(path))
            out = []
            for sh in book.sheets():
                rows = []
                for i in range(sh.nrows):
                    row = []
                    for c in sh.row(i):
                        if c.ctype == xlrd.XL_CELL_DATE:
                            row.append(xlrd.xldate.xldate_as_datetime(c.value, book.datemode).isoformat())
                        elif c.ctype == xlrd.XL_CELL_BOOLEAN:
                            row.append(bool(c.value))
                        elif c.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                            row.append(None)
                        else:
                            row.append(_plain(c.value))
                    rows.append(row)
                out.append((sh.name, rows))
            return out, 0
        import pandas as pd

        frames = pd.read_excel(str(path), sheet_name=None, header=None, engine="odf")
        return [(name, [[_plain(v) for v in row] for row in df.itertuples(index=False, name=None)]) for name, df in frames.items()], 0
    except ConversionError:
        raise
    except Exception as e:
        raise ConversionError("corrupt_input", "This spreadsheet is damaged or isn't a valid " + fmt.upper() + " file.") from e


def _trim(rows: list[list[Any]]) -> list[list[Any]]:
    while rows and all(v is None or v == "" for v in rows[-1]):
        rows.pop()
    width = max((max((i + 1 for i, v in enumerate(r) if v not in (None, "")), default=0) for r in rows), default=0)
    return [r[:width] + [None] * (width - len(r)) for r in rows]


# ---------------------------------------------------------------------------
# export


class ExportOptions(Options):
    sheet: str | None = Field(None, max_length=100, title="Sheet",
                              description="Sheet name or number. Leave empty for the first sheet.",
                              json_schema_extra=ui(placeholder="First sheet"))
    all_sheets: bool = Field(False, title="Export every sheet", description="One file per sheet (download them all as a ZIP).")
    header_row: bool = Field(True, title="First row is headers", json_schema_extra=ui(targets=("json",)))
    neutralize_formulas: bool = Field(True, title="Protect against formula injection",
                                      description="Prefix text cells starting with = + - @ so spreadsheet apps don't run them.",
                                      json_schema_extra=ui(targets=("csv", "tsv")))


def _pick(sheets, o: ExportOptions):
    if o.all_sheets:
        return sheets
    if not o.sheet:
        return sheets[:1]
    names = [n for n, _ in sheets]
    if o.sheet in names:
        return [sheets[names.index(o.sheet)]]
    if o.sheet.strip().isdigit() and 1 <= int(o.sheet) <= len(sheets):
        return [sheets[int(o.sheet) - 1]]
    raise ConversionError("invalid_option", f"There's no sheet called “{o.sheet}”. Sheets in this file: {', '.join(names)}.")


def _safe_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "sheet"
    return keep[:60]


def export(ctx: Ctx) -> None:
    o: ExportOptions = ctx.options  # type: ignore[assignment]
    ctx.stage("Reading spreadsheet")
    sheets, missing = read_book(ctx, ctx.input.path, ctx.input.format)
    chosen = _pick(sheets, o)
    used: set[str] = set()
    for k, (name, rows) in enumerate(chosen):
        ctx.progress(k, len(chosen), stage=f"Writing sheet {k + 1} of {len(chosen)}", force=True)
        rows = _trim(rows)
        base = _safe_name(name)
        while base in used:
            base += "_"
        used.add(base)
        fname = f"{base}.{ctx.target}" if len(chosen) > 1 else f"output.{ctx.target}"
        out = ctx.out_path(fname)
        if ctx.target in ("csv", "tsv"):
            with out.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter="\t" if ctx.target == "tsv" else ",")
                for r in rows:
                    w.writerow(["" if v is None else (neutralize(v) if o.neutralize_formulas else v) for v in r])
        else:
            if o.header_row and rows:
                head = [str(h) if h not in (None, "") else f"column_{i + 1}" for i, h in enumerate(rows[0])]
                seen: dict[str, int] = {}
                for i, h in enumerate(head):
                    if h in seen:
                        seen[h] += 1
                        head[i] = f"{h}_{seen[h]}"
                    else:
                        seen[h] = 1
                data: Any = [dict(zip(head, r)) for r in rows[1:]]
            else:
                data = rows
            out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        ctx.add_output(out, ctx.target, label=f"Sheet “{name}”" if len(chosen) > 1 else None)
    if missing:
        ctx.warn(f"{missing} formula cell{'s have' if missing != 1 else ' has'} no saved result in this file, so "
                 f"{'they were' if missing != 1 else 'it was'} left empty. Open and save it in a spreadsheet app to fix this.")
    if len(sheets) > 1 and not o.all_sheets:
        ctx.notice(f"This file has {len(sheets)} sheets; only “{chosen[0][0]}” was exported. Turn on “Export every sheet” for all.")
    ctx.notice("Exported computed values, not formulas.")


register(Operation(
    id="sheet.export", category="spreadsheets", label="Export sheet data",
    description="Export spreadsheet data to CSV, TSV or JSON — one sheet, or every sheet as separate files.",
    inputs=BOOKS, outputs=("csv", "tsv", "json"), cardinality="one_to_many", options=ExportOptions, run=export,
    engines=("openpyxl", "pandas"), keywords=("excel to csv", "xlsx to csv", "sheet"),
))


# ---------------------------------------------------------------------------
# import


class ImportOptions(Options):
    sheet_name: str = Field("Sheet1", min_length=1, max_length=31, title="Sheet name")
    header_row: bool = Field(True, title="First row is headers", description="Make the first row bold.",
                             json_schema_extra=ui(targets=("xlsx",), advanced=True))


def _decode(raw: bytes) -> str:
    from charset_normalizer import from_bytes

    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        best = from_bytes(raw).best()
        if not best:
            raise ConversionError("corrupt_input", "We couldn't work out this file's text encoding.")
        return str(best)


def _typed(v: str) -> Any:
    s = v.strip()
    if s == "":
        return None
    if s[:1] in ("0",) and len(s) > 1 and s.isdigit():
        return v  # leading zeros (IDs, ZIP codes) stay text
    try:
        return int(s)
    except ValueError:
        pass
    try:
        f = float(s)
        return f if math.isfinite(f) else v
    except ValueError:
        return v


def _flatten(records: list[dict]) -> tuple[list[str], list[list[Any]]]:
    """Nested objects → dotted columns (a.b.c). Lists and mixed values → JSON text."""
    def walk(prefix: str, val: Any, out: dict):
        if isinstance(val, dict) and val:
            for k, v in val.items():
                walk(f"{prefix}.{k}" if prefix else str(k), v, out)
        elif isinstance(val, (list, dict)):
            out[prefix] = json.dumps(val, ensure_ascii=False)
        else:
            out[prefix] = val

    flat = []
    cols: dict[str, None] = {}
    for r in records:
        f: dict = {}
        walk("", r, f)
        flat.append(f)
        cols.update(dict.fromkeys(f))
    head = list(cols)
    return head, [[f.get(c) for c in head] for f in flat]


def read_table(ctx: Ctx, path: Path, fmt: str) -> tuple[list[str] | None, list[list[Any]]]:
    text = _decode(path.read_bytes())
    if fmt == "json":
        try:
            data = json.loads(text)
        except ValueError as e:
            raise ConversionError("corrupt_input", f"This isn't valid JSON ({e}).") from e
        if not isinstance(data, list) or not data or not all(isinstance(x, dict) for x in data):
            raise ConversionError("invalid_input", "JSON must be an array of objects, like [{\"name\": \"Ann\", \"age\": 31}, …].")
        head, rows = _flatten(data)
        return head, rows
    sample = text[:16384]
    delim = "\t" if fmt == "tsv" else ","
    if fmt == "csv":
        try:
            delim = csv.Sniffer().sniff(sample, delimiters=",;|\t").delimiter
        except csv.Error:
            delim = ","
    rows = [[_typed(c) for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim)]
    if delim != ("\t" if fmt == "tsv" else ","):
        ctx.notice(f"Detected “{delim}” as the column separator.")
    return None, rows


def import_table(ctx: Ctx) -> None:
    o: ImportOptions = ctx.options  # type: ignore[assignment]
    ctx.stage("Reading data")
    head, rows = read_table(ctx, ctx.input.path, ctx.input.format)
    all_rows = ([head] if head else []) + rows
    if not all_rows:
        raise ConversionError("invalid_input", "This file has no rows.")
    out = ctx.default_out()
    ctx.stage("Writing spreadsheet")
    if ctx.target == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook(write_only=False)
        ws = wb.active
        ws.title = o.sheet_name
        for i, r in enumerate(all_rows, start=1):
            for j, v in enumerate(r, start=1):
                c = ws.cell(row=i, column=j, value=v)
                if isinstance(v, str) and v.startswith("="):
                    c.data_type = "s"  # data stays data: never stored as a live formula
                if i == 1 and o.header_row:
                    c.font = Font(bold=True)
        wb.save(out)
    else:
        from odf.opendocument import OpenDocumentSpreadsheet
        from odf.table import Table, TableCell, TableRow
        from odf.text import P

        doc = OpenDocumentSpreadsheet()
        t = Table(name=o.sheet_name)
        for r in all_rows:
            tr = TableRow()
            for v in r:
                if isinstance(v, bool) or v is None or not isinstance(v, (int, float)):
                    cell = TableCell(valuetype="string")
                    cell.addElement(P(text="" if v is None else str(v)))
                else:
                    cell = TableCell(valuetype="float", value=v)
                    cell.addElement(P(text=str(v)))
                tr.addElement(cell)
            t.addElement(tr)
        doc.spreadsheet.addElement(t)
        doc.save(str(out))
    if ctx.input.format == "json":
        ctx.notice("Nested objects became dotted columns (e.g. address.city); lists were stored as JSON text.")
    ctx.info["rows"] = len(all_rows)
    ctx.add_output(out)


register(Operation(
    id="sheet.import", category="spreadsheets", label="Make a spreadsheet",
    description="Turn CSV, TSV or JSON data into an Excel or OpenDocument spreadsheet. Delimiter and encoding are detected.",
    inputs=("csv", "tsv", "json"), outputs=("xlsx", "ods"), cardinality="one_to_one", options=ImportOptions,
    run=import_table, engines=("openpyxl",),
    pair_limitations={("json", "xlsx"): ("JSON must be an array of objects; nested objects become dotted columns.",),
                      ("json", "ods"): ("JSON must be an array of objects; nested objects become dotted columns.",)},
    keywords=("csv to excel", "json to excel"),
))


# ---------------------------------------------------------------------------
# LibreOffice: book ↔ book, → PDF


def book_convert(ctx: Ctx) -> None:
    out = office.convert_to_output(ctx, ctx.input.path, ctx.target)
    ctx.add_output(out)


register(Operation(
    id="sheet.office", category="spreadsheets", label="Convert spreadsheet",
    description="Convert between Excel and OpenDocument spreadsheets with LibreOffice. All sheets are kept.",
    inputs=BOOKS, outputs=BOOKS, cardinality="one_to_one", options=NoOptions, run=book_convert,
    engines=("soffice",), resource_class="heavy", memory_mb=None,
    pair_limitations={(s, "xls"): ("XLS is limited to 65,536 rows and 256 columns per sheet.",) for s in ("xlsx", "ods")},
    keywords=("excel", "libreoffice calc"),
))


class SheetPdfOptions(Options):
    one_page_per_sheet: bool = Field(True, title="Fit each sheet on one page",
                                     description="Scales each sheet to a single page so wide tables aren't split.")


def sheet_pdf(ctx: Ctx) -> None:
    o: SheetPdfOptions = ctx.options  # type: ignore[assignment]
    flt = 'pdf:calc_pdf_Export:{"SinglePageSheets":{"type":"boolean","value":"true"}}' if o.one_page_per_sheet else "pdf"
    infilter = "Text - txt - csv (StarCalc):44,34,76,1" if ctx.input.format == "csv" else None
    out = office.convert_to_output(ctx, ctx.input.path, "pdf", filter_override=flt, infilter=infilter)
    ctx.add_output(out, "pdf")


register(Operation(
    id="sheet.to_pdf", category="spreadsheets", label="Spreadsheet to PDF",
    description="Print every sheet of a spreadsheet (or a CSV) to PDF with LibreOffice.",
    inputs=(*BOOKS, "csv"), outputs=("pdf",), cardinality="one_to_one", options=SheetPdfOptions, run=sheet_pdf,
    engines=("soffice",), resource_class="heavy", memory_mb=None, keywords=("excel to pdf", "print"),
))
