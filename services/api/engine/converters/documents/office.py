"""Word-processing formats via LibreOffice, and Markdown/HTML via Pandoc (always --sandbox)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ... import office
from ...context import ConversionError, Ctx, which
from ...registry import NoOptions, Operation, Options, register, ui

WORD = ("docx", "doc", "odt", "rtf")


def office_convert(ctx: Ctx) -> None:
    infilter = "Text (encoded):UTF8,LF,,," if ctx.input.format == "txt" else None
    out = office.convert_to_output(ctx, ctx.input.path, ctx.target, infilter=infilter)
    ctx.add_output(out)


register(Operation(
    id="doc.office", category="documents", label="Convert document",
    description="Convert Word, OpenDocument and RTF documents with LibreOffice, keeping text, styles, tables and images.",
    inputs=(*WORD, "txt"), outputs=(*WORD, "pdf"), cardinality="one_to_one", run=office_convert, options=NoOptions,
    engines=("soffice",), resource_class="heavy", memory_mb=None,
    explicit_pairs=tuple([(s, "pdf") for s in (*WORD, "txt")] + [(s, t) for s in WORD for t in WORD if s != t]),
    pair_limitations={
        **{(s, "rtf"): ("RTF can't hold some modern features (e.g. comments threads, SmartArt).",) for s in ("docx", "doc", "odt")},
        **{(s, "doc"): ("The old .doc format may simplify some newer layout features.",) for s in ("docx", "odt", "rtf")},
    },
    keywords=("word", "office", "libreoffice"),
))


# ---------------------------------------------------------------------------
# Pandoc


class PandocOptions(Options):
    standalone: bool = Field(True, title="Full HTML page", description="Include <html>, <head> and a title, not just a fragment.",
                             json_schema_extra=ui(targets=("html",)))
    wrap: Literal["none", "auto"] = Field("none", title="Line wrapping", description="Wrap long Markdown lines at 72 characters.",
                                          json_schema_extra=ui(targets=("md",), advanced=True))


PANDOC_FMT = {"md": "gfm", "html": "html", "docx": "docx", "odt": "odt"}


def pandoc_convert(ctx: Ctx) -> None:
    o: PandocOptions = ctx.options  # type: ignore[assignment]
    exe = which("pandoc", "UC_PANDOC")
    src, dst = ctx.input.format, ctx.target
    out = ctx.default_out(dst)
    cmd = [exe, "--sandbox", "-f", PANDOC_FMT[src], "-t", PANDOC_FMT[dst], "-o", str(out), str(ctx.input.path)]
    if dst == "html" and o.standalone:
        cmd += ["-s", "--metadata", "title=Converted document", "--embed-resources=false"]
    if dst == "md":
        cmd += [f"--wrap={o.wrap}"]
        if src == "docx":
            ctx.notice("Images inside the document aren't included in Markdown output.")
    ctx.stage("Converting with Pandoc")
    res = ctx.run(cmd, check=False)
    if res.returncode != 0 or not out.exists():
        raise ConversionError("corrupt_input", "Pandoc couldn't read this file. Check that it's valid " + src.upper() + ".")
    ctx.add_output(out)


register(Operation(
    id="doc.pandoc", category="documents", label="Convert Markdown / HTML",
    description="Convert between Markdown, HTML and Word/OpenDocument with Pandoc. External files and URLs are never fetched.",
    inputs=("md", "html", "docx"), outputs=("md", "html", "docx", "odt"), cardinality="one_to_one",
    options=PandocOptions, run=pandoc_convert, engines=("pandoc",),
    explicit_pairs=(("md", "html"), ("html", "md"), ("md", "docx"), ("md", "odt"), ("html", "docx"), ("html", "odt"),
                    ("docx", "md")),
    pair_limitations={("docx", "md"): ("Images and complex layout (columns, text boxes) are dropped.",),
                      ("html", "md"): ("Styling, scripts and forms are dropped; structure and links are kept.",),
                      ("html", "docx"): ("Images that point to other files or URLs aren't included.",),
                      ("html", "odt"): ("Images that point to other files or URLs aren't included.",)},
    keywords=("markdown", "pandoc"),
))
