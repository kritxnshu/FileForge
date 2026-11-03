"""Extract content from text-based PDFs: text (TXT/MD/HTML), Word (DOCX), tables (XLSX/CSV); OCR.

PDF → DOCX uses a permissive pipeline (pdfplumber → python-docx) because the best
open-source engine, pdf2docx, depends on PyMuPDF (AGPL). With ENABLE_AGPL_ENGINES=true
and pdf2docx installed, pdf2docx is used instead (DECISIONS, THIRD_PARTY_LICENSES).
"""

from __future__ import annotations

import html as htmlmod
import os
import statistics
from typing import Literal

from pydantic import Field

from ...context import ConversionError, Ctx, which
from ...registry import Operation, register, ui
from .pdfcommon import RANGE_FIELD, PdfPasswordOptions, open_reader, parse_ranges

NO_TEXT = ("This PDF has no text layer — it's probably a scan or photo of pages. "
           "Use OCR to make it searchable first, if it's available.")


class ExtractOptions(PdfPasswordOptions):
    pages: str | None = Field(None, title="Pages", json_schema_extra=ui(placeholder="All pages", advanced=True), **RANGE_FIELD)


def _plumber(ctx: Ctx, password: str | None):
    import pdfplumber

    open_reader(ctx.input.path, password)  # consistent password/corruption errors
    try:
        return pdfplumber.open(str(ctx.input.path), password=password or "")
    except Exception as e:
        raise ConversionError("corrupt_input", "This PDF is damaged and can't be read.") from e


def _paragraphs(page) -> list[tuple[str, float]]:
    """Group text lines into paragraphs by vertical gaps; returns (text, font size)."""
    lines = page.extract_text_lines(layout=False, strip=True, return_chars=True)
    if not lines:
        return []
    paras: list[tuple[list[str], list[float]]] = []
    prev_bottom = None
    prev_size = None
    for ln in lines:
        sizes = [c.get("size", 0) for c in ln.get("chars", []) if c.get("text", "").strip()]
        size = statistics.median(sizes) if sizes else 0
        gap = (ln["top"] - prev_bottom) if prev_bottom is not None else 0
        if not paras or gap > max(4.0, (prev_size or size) * 0.7) or (prev_size and abs(size - prev_size) > 1.5):
            paras.append(([], []))
        paras[-1][0].append(ln["text"])
        paras[-1][1].append(size)
        prev_bottom, prev_size = ln["bottom"], size
    return [(" ".join(t), statistics.median(s) if s else 0) for t, s in paras]


def to_text(ctx: Ctx) -> None:
    o: ExtractOptions = ctx.options  # type: ignore[assignment]
    with _plumber(ctx, o.password) as pdf:
        idx = parse_ranges(o.pages, len(pdf.pages))
        pages: list[list[tuple[str, float]]] = []
        for k, i in enumerate(idx):
            ctx.progress(k, len(idx), stage=f"Reading page {k + 1} of {len(idx)}")
            pages.append(_paragraphs(pdf.pages[i]))
    if not any(pages):
        raise ConversionError("no_text", NO_TEXT)
    sizes = [s for p in pages for _, s in p if s]
    body = statistics.median(sizes) if sizes else 0
    out = ctx.default_out()
    if ctx.target == "txt":
        out.write_text("\n\n\f".join("\n\n".join(t for t, _ in p) for p in pages) + "\n", encoding="utf-8")
    elif ctx.target == "md":
        chunks = []
        for p in pages:
            for t, s in p:
                if body and s >= body * 1.6:
                    chunks.append("# " + t)
                elif body and s >= body * 1.25:
                    chunks.append("## " + t)
                else:
                    chunks.append(t.replace("*", r"\*").replace("_", r"\_"))
            chunks.append("---")
        out.write_text("\n\n".join(chunks[:-1]) + "\n", encoding="utf-8")
    else:
        parts = ['<!doctype html><html><head><meta charset="utf-8"><title>Extracted text</title></head><body>']
        for n, p in enumerate(pages):
            parts.append(f'<section data-page="{idx[n] + 1}">')
            for t, s in p:
                tag = "h1" if body and s >= body * 1.6 else "h2" if body and s >= body * 1.25 else "p"
                parts.append(f"<{tag}>{htmlmod.escape(t)}</{tag}>")
            parts.append("</section><hr>")
        parts.append("</body></html>")
        out.write_text("\n".join(parts), encoding="utf-8")
    ctx.notice("Text was extracted; the original layout, images and fonts aren't kept.")
    ctx.add_output(out)


register(Operation(
    id="pdf.to_text", category="documents", label="PDF to text",
    description="Extract the text of a PDF as plain text, Markdown or HTML.",
    inputs=("pdf",), outputs=("txt", "md", "html"), cardinality="one_to_one", options=ExtractOptions, run=to_text,
    engines=("pdfplumber", "pypdf"), support="partial",
    limitations=("Extracts text only; layout, images and fonts are not preserved. Scanned PDFs have no text to extract.",),
    keywords=("extract text",),
))


# ---------------------------------------------------------------------------
# PDF → DOCX


def _inside(obj, boxes) -> bool:
    x = (obj["x0"] + obj["x1"]) / 2
    y = (obj["top"] + obj["bottom"]) / 2
    return any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in boxes)


def to_docx(ctx: Ctx) -> None:
    o: ExtractOptions = ctx.options  # type: ignore[assignment]
    if os.environ.get("ENABLE_AGPL_ENGINES", "false").lower() == "true":
        try:
            from pdf2docx import Converter  # AGPL (PyMuPDF); only when explicitly enabled

            out = ctx.default_out("docx")
            cv = Converter(str(ctx.input.path), password=o.password or None)
            cv.convert(str(out))
            cv.close()
            ctx.notice("Converted with pdf2docx (AGPL engine enabled on this server).")
            ctx.add_output(out, "docx")
            return
        except ImportError:
            pass
    from docx import Document
    from docx.enum.text import WD_BREAK
    from docx.shared import Pt

    doc = Document()
    found_text = False
    tables_found = 0
    with _plumber(ctx, o.password) as pdf:
        idx = parse_ranges(o.pages, len(pdf.pages))
        all_sizes: list[float] = []
        for i in idx:
            for c in pdf.pages[i].chars[:4000]:
                if c.get("text", "").strip():
                    all_sizes.append(c.get("size", 0))
        body = statistics.median(all_sizes) if all_sizes else 11
        for k, i in enumerate(idx):
            ctx.progress(k, len(idx), stage=f"Rebuilding page {k + 1} of {len(idx)}")
            page = pdf.pages[i]
            tables = page.find_tables()
            boxes = [t.bbox for t in tables]
            text_page = page.filter(lambda obj: obj.get("object_type") != "char" or not _inside(obj, boxes)) if boxes else page
            blocks: list[tuple[float, str, object]] = []
            for t in tables:
                rows = t.extract()
                if rows and any(any(c for c in r) for r in rows):
                    blocks.append((t.bbox[1], "table", rows))
            lines = text_page.extract_text_lines(layout=False, strip=True, return_chars=True)
            # paragraphs with their vertical position
            cur: list[str] = []
            cur_top = None
            prev_bottom = None
            cur_size = body
            for ln in lines:
                sizes = [c.get("size", 0) for c in ln.get("chars", []) if c.get("text", "").strip()]
                size = statistics.median(sizes) if sizes else body
                gap = ln["top"] - prev_bottom if prev_bottom is not None else 0
                if cur and (gap > max(4.0, size * 0.7) or abs(size - cur_size) > 1.5):
                    blocks.append((cur_top or 0, "para", (" ".join(cur), cur_size)))
                    cur = []
                if not cur:
                    cur_top, cur_size = ln["top"], size
                cur.append(ln["text"])
                prev_bottom = ln["bottom"]
            if cur:
                blocks.append((cur_top or 0, "para", (" ".join(cur), cur_size)))
            for _, kind, data in sorted(blocks, key=lambda b: b[0]):
                if kind == "table":
                    rows = data  # type: ignore[assignment]
                    ncols = max(len(r) for r in rows)
                    tbl = doc.add_table(rows=len(rows), cols=ncols)
                    tbl.style = "Table Grid"
                    for r, row in enumerate(rows):
                        for c in range(ncols):
                            tbl.cell(r, c).text = (row[c] if c < len(row) and row[c] else "")
                    tables_found += 1
                    found_text = True
                else:
                    text, size = data  # type: ignore[misc]
                    found_text = True
                    if size >= body * 1.6:
                        doc.add_heading(text, level=1)
                    elif size >= body * 1.25:
                        doc.add_heading(text, level=2)
                    else:
                        p = doc.add_paragraph(text)
                        if p.runs and abs(size - body) > 0.5:
                            p.runs[0].font.size = Pt(round(size))
            if k < len(idx) - 1:
                doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    if not found_text:
        raise ConversionError("no_text", NO_TEXT)
    out = ctx.default_out("docx")
    doc.save(out)
    ctx.notice(f"Rebuilt text{' and ' + str(tables_found) + ' table' + ('s' if tables_found != 1 else '') if tables_found else ''} "
               "as an editable document. Images, columns and exact positioning aren't kept.")
    ctx.add_output(out, "docx")


register(Operation(
    id="pdf.to_docx", category="documents", label="PDF to Word",
    description="Turn a text-based PDF into an editable Word document with its paragraphs, headings and tables.",
    inputs=("pdf",), outputs=("docx",), cardinality="one_to_one", options=ExtractOptions, run=to_docx,
    engines=("pdfplumber", "python-docx", "pypdf"), support="partial", heavy_over_mb=10,
    limitations=("Text-based PDFs only; scanned PDFs are not supported.",
                 "Text, headings and tables are rebuilt; images, columns, fonts and exact layout are not preserved."),
    keywords=("pdf to word", "editable"),
))


# ---------------------------------------------------------------------------
# PDF → XLSX / CSV (tables)


class TablesOptions(ExtractOptions):
    neutralize_formulas: bool = Field(True, title="Protect against formula injection",
                                      description="Prefix cells starting with = + - @ so spreadsheet apps don't run them.",
                                      json_schema_extra=ui(targets=("csv",)))


def _safe_cell(v: str | None, neutralize: bool) -> str:
    v = v or ""
    if neutralize and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        try:
            float(v)
            return v
        except ValueError:
            return "'" + v
    return v


def to_tables(ctx: Ctx) -> None:
    import csv

    o: TablesOptions = ctx.options  # type: ignore[assignment]
    found: list[tuple[int, list[list[str | None]]]] = []
    with _plumber(ctx, o.password) as pdf:
        idx = parse_ranges(o.pages, len(pdf.pages))
        any_text = False
        for k, i in enumerate(idx):
            ctx.progress(k, len(idx), stage=f"Finding tables on page {k + 1} of {len(idx)}")
            page = pdf.pages[i]
            any_text = any_text or bool(page.chars)
            for t in page.extract_tables():
                if t and len(t) >= 1 and any(any(c for c in r) for r in t):
                    found.append((i + 1, t))
    if not found:
        if not any_text:
            raise ConversionError("no_text", NO_TEXT)
        raise ConversionError("no_tables", "We didn't find any tables in this PDF. Tables need ruled lines or clearly aligned columns.")
    if ctx.target == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        wb.remove(wb.active)
        for n, (page_no, rows) in enumerate(found):
            ws = wb.create_sheet(f"Table {n + 1} (p{page_no})"[:31])
            for row in rows:
                ws.append([_typed(c) for c in row])
        out = ctx.default_out("xlsx")
        wb.save(out)
        ctx.add_output(out, "xlsx")
    else:
        for n, (page_no, rows) in enumerate(found):
            out = ctx.out_path(f"table-{n + 1}.csv") if len(found) > 1 else ctx.default_out("csv")
            with out.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows([[_safe_cell(c, o.neutralize_formulas) for c in r] for r in rows])
            ctx.add_output(out, "csv", label=f"Table {n + 1} (page {page_no})" if len(found) > 1 else None)
    ctx.notice(f"Found {len(found)} table{'s' if len(found) != 1 else ''}.")


def _typed(v: str | None):
    if v is None:
        return None
    s = v.strip()
    try:
        return int(s) if s.lstrip("-").isdigit() else float(s)
    except ValueError:
        return s


register(Operation(
    id="pdf.to_tables", category="spreadsheets", label="PDF tables to spreadsheet",
    description="Find tables in a text-based PDF and export them to Excel (one sheet per table) or CSV.",
    inputs=("pdf",), outputs=("xlsx", "csv"), cardinality="one_to_many", options=TablesOptions, run=to_tables,
    engines=("pdfplumber", "openpyxl", "pypdf"), support="partial",
    limitations=("Works on text-based PDFs with ruled or clearly aligned tables; merged cells may split.",),
    keywords=("pdf to excel", "extract tables"),
))


# ---------------------------------------------------------------------------
# OCR (experimental, ENABLE_OCR)


class OcrOptions(PdfPasswordOptions):
    language: Literal["eng", "deu", "fra", "spa", "ita", "por", "nld"] = Field("eng", title="Language")
    force: bool = Field(False, title="Re-OCR pages that already have text", json_schema_extra=ui(advanced=True))


def ocr(ctx: Ctx) -> None:
    o: OcrOptions = ctx.options  # type: ignore[assignment]
    exe = which("ocrmypdf")
    out = ctx.default_out("pdf")
    cmd = [exe, "--output-type", "pdf", "-l", o.language, "--jobs", "1", "--quiet"]
    cmd.append("--force-ocr" if o.force else "--skip-text")
    cmd += [str(ctx.input.path), str(out)]
    ctx.stage("Recognizing text")
    res = ctx.run(cmd, check=False)
    if res.returncode == 6:
        raise ConversionError("has_text", "This PDF already has text. Turn on “Re-OCR pages that already have text” to redo it.")
    if res.returncode != 0 or not out.exists():
        raise ConversionError("engine_error", "OCR failed on this PDF.")
    ctx.add_output(out, "pdf")


register(Operation(
    id="pdf.ocr", category="documents", label="Make PDF searchable (OCR)",
    description="Recognize text in scanned PDFs and add an invisible, searchable text layer.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=OcrOptions, run=ocr, engines=("ocrmypdf", "tesseract"),
    resource_class="heavy", support="experimental", feature_flag="ENABLE_OCR", slug="ocr-pdf",
    limitations=("Accuracy depends on scan quality and language.",), keywords=("scan", "searchable", "ocr"),
))
