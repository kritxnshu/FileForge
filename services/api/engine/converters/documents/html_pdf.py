"""HTML / Markdown → PDF with Chromium: JavaScript off, every non-data: request blocked."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ...chromium import html_to_pdf
from ...context import ConversionError, Ctx, which
from ...registry import Operation, Options, register, ui

PRINT_CSS = """<style>
body{font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;line-height:1.5;color:#111;max-width:46em;margin:0 auto}
pre,code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.9em}pre{background:#f5f5f5;padding:.8em;white-space:pre-wrap}
table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:.3em .6em}img{max-width:100%}
</style>"""


class HtmlPdfOptions(Options):
    page_size: Literal["A4", "Letter", "Legal", "A3", "A5"] = Field("A4", title="Page size")
    landscape: bool = Field(False, title="Landscape")
    margin_mm: float = Field(15, ge=0, le=50, title="Margins", json_schema_extra=ui(unit="mm"))
    background: bool = Field(True, title="Print backgrounds", description="Include background colors and images.",
                             json_schema_extra=ui(advanced=True))


def _decode(raw: bytes) -> str:
    from charset_normalizer import from_bytes

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        best = from_bytes(raw).best()
        return str(best) if best else raw.decode("latin-1")


def to_pdf(ctx: Ctx) -> None:
    o: HtmlPdfOptions = ctx.options  # type: ignore[assignment]
    if ctx.input.format == "md":
        exe = which("pandoc", "UC_PANDOC")
        ctx.stage("Rendering Markdown")
        res = ctx.run([exe, "--sandbox", "-f", "gfm", "-t", "html5", "-s", "--metadata", "title= ", str(ctx.input.path)],
                      check=False)
        if res.returncode != 0:
            raise ConversionError("corrupt_input", "This Markdown file couldn't be read.")
        html = res.stdout.decode("utf-8")
        html = html.replace("</head>", PRINT_CSS + "</head>", 1)
    else:
        html = _decode(ctx.input.path.read_bytes())
    out = ctx.default_out("pdf")
    ctx.stage("Rendering PDF")
    blocked = html_to_pdf(html, out, page_size=o.page_size, landscape=o.landscape, margin_mm=o.margin_mm,
                          background=o.background, timeout_s=max(10, ctx.timeout_s - 10))
    if blocked:
        ctx.notice(f"{len(blocked)} external resource{'s were' if len(blocked) != 1 else ' was'} not loaded "
                   "(images, styles or fonts from other files or URLs). Embed them as data: URIs to include them.")
    if "<script" in html.lower():
        ctx.notice("Scripts in the page were not run.")
    ctx.add_output(out, "pdf")


register(Operation(
    id="doc.html_to_pdf", category="documents", label="HTML to PDF",
    description="Print HTML or Markdown to PDF with a browser engine. Scripts don't run and nothing is fetched from the network.",
    inputs=("html", "md"), outputs=("pdf",), cardinality="one_to_one", options=HtmlPdfOptions, run=to_pdf,
    engines=("chromium",), format_engines={"md": ("pandoc",)}, memory_mb=None,
    limitations=("External images, stylesheets and fonts aren't loaded; JavaScript doesn't run.",),
    keywords=("print", "web page"),
))
