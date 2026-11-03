"""Browser-only tools (runtime="client"). Registered here so /api/capabilities lists them and the
UI builds their settings from these schemas; implementations live in apps/web/src/lib/tools/.
Verification comes from Vitest (scripts/merge_vitest_results.py → verified.json)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ...registry import Operation, Options, register, ui

TREE = ("json", "xml", "yaml", "toml")


def client(**kw) -> Operation:
    kw.setdefault("runtime", "client")
    kw.setdefault("cardinality", "transform")
    return register(Operation(**kw))


class IndentOptions(Options):
    indent: int = Field(2, ge=0, le=8, title="Indent", description="Spaces per level (0 = compact).",
                        json_schema_extra=ui(targets=("json", "xml", "yaml")))
    neutralize_formulas: bool = Field(True, title="Protect against formula injection",
                                      description="Prefix cells starting with = + - @ so spreadsheet apps don't run them.",
                                      json_schema_extra=ui(targets=("csv", "tsv")))


client(id="dev.data_convert", category="developer", label="Convert data (paste)",
       description="Convert pasted JSON, XML, YAML, TOML, CSV or TSV in your browser.",
       inputs=(*TREE, "csv", "tsv"), outputs=(*TREE, "csv", "tsv"), cardinality="one_to_one", options=IndentOptions,
       explicit_pairs=tuple((s, t) for s in TREE for t in TREE if s != t) + (("csv", "json"), ("tsv", "json"), ("json", "csv"),
                                                                               ("json", "tsv")),
       pair_limitations={(s, "xml"): ("XML needs one root element; other shapes are wrapped in <root>.",) for s in TREE if s != "xml"},
       keywords=("json to yaml", "yaml to json", "xml to json", "json to csv"))


class HtmlMdOptions(Options):
    pass


client(id="dev.html_markdown", category="developer", label="HTML ↔ Markdown (paste)",
       description="Turn pasted HTML into Markdown, or Markdown into HTML, in your browser.",
       inputs=("html", "md"), outputs=("html", "md"), cardinality="one_to_one", options=HtmlMdOptions,
       explicit_pairs=(("html", "md"), ("md", "html")), keywords=("markdown", "html"))


class JsonFormatOptions(Options):
    mode: Literal["format", "minify", "validate"] = Field("format", title="Action")
    indent: int = Field(2, ge=1, le=8, title="Indent", json_schema_extra=ui(show_if={"mode": "format"}))
    sort_keys: bool = Field(False, title="Sort keys")


client(id="dev.json_format", category="developer", label="JSON formatter & validator",
       description="Pretty-print, minify or validate JSON. Errors point to the exact line and column.",
       inputs=("json",), outputs=(), options=JsonFormatOptions, slug="json-formatter",
       keywords=("pretty print", "lint", "validate", "beautify", "minify"))


class CodeFormatOptions(Options):
    mode: Literal["beautify", "minify"] = Field("beautify", title="Action")
    indent: int = Field(2, ge=1, le=8, title="Indent")


client(id="dev.code_format", category="developer", label="Code beautifier & minifier",
       description="Beautify or minify CSS, JavaScript, SQL and XML in your browser.",
       inputs=("css", "js", "sql", "xml"), outputs=(), options=CodeFormatOptions, slug="code-formatter",
       keywords=("beautify", "minify", "prettier", "format sql", "format css"))


class SqlOptions(Options):
    table: str = Field("my_table", pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$", title="Table name")
    dialect: Literal["postgres", "mysql", "sqlite", "sqlserver"] = Field("postgres", title="SQL dialect")
    create_table: bool = Field(True, title="Include CREATE TABLE")


client(id="dev.csv_to_sql", category="developer", label="CSV to SQL (paste)",
       description="Generate INSERT statements from pasted CSV, with quoting for your database.",
       inputs=("csv", "tsv"), outputs=("sql",), cardinality="one_to_one", options=SqlOptions,
       keywords=("insert statements", "database"))


class Base64Options(Options):
    direction: Literal["encode", "decode"] = Field("encode", title="Direction")
    url_safe: bool = Field(False, title="URL-safe alphabet", description="Use - and _ instead of + and /, without padding.")


client(id="dev.base64", category="developer", label="Base64 encode / decode",
       description="Encode text or files to Base64, or decode Base64 back to text or a file.",
       inputs=("txt",), outputs=(), options=Base64Options, slug="base64", keywords=("encode", "decode", "b64"))


class UrlOptions(Options):
    direction: Literal["encode", "decode"] = Field("encode", title="Direction")
    mode: Literal["component", "full"] = Field("component", title="Encode",
                                               description="component encodes every reserved character (for query values); full keeps :/?#& intact.")


client(id="dev.url", category="developer", label="URL encode / decode",
       description="Percent-encode text for URLs, or decode it back.", inputs=("txt",), outputs=(), options=UrlOptions,
       slug="url-encode", keywords=("percent encoding", "escape", "query string"))


class TimestampOptions(Options):
    timezone: str = Field("UTC", max_length=64, title="Time zone", json_schema_extra=ui(widget="timezone"))


client(id="dev.timestamp", category="developer", label="Unix timestamp converter",
       description="Convert Unix timestamps (seconds or milliseconds) to ISO 8601 and local time, and back.",
       inputs=("txt",), outputs=(), options=TimestampOptions, slug="timestamp",
       keywords=("epoch", "unix time", "date", "iso 8601"))
