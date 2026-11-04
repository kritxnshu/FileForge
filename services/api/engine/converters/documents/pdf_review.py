"""Compare two PDFs, and convert to PDF/A (archival)."""

from __future__ import annotations

import difflib
import io
import os
import re
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape

from pydantic import Field

from ...context import ConversionError, Ctx, which
from ...registry import Operation, register, ui
from .pdfcommon import PdfPasswordOptions, open_pdfium, open_pike

# ---------------------------------------------------------------------------
# compare

MAX_COMPARE_PAGES = 300
CELL = 12  # px grid used to group changed pixels into boxes


def _changed_boxes(a, b) -> list[tuple[int, int, int, int]]:
    """Boxes (pixels, in a's coordinates) where two renders differ visibly."""
    from PIL import ImageChops

    diff = ImageChops.difference(a.convert("L"), b.convert("L")).point(lambda p: 255 if p > 48 else 0)
    if diff.getbbox() is None:
        return []
    w, h = diff.size
    cols, rows = (w + CELL - 1) // CELL, (h + CELL - 1) // CELL
    hot = set()
    for r in range(rows):
        for c in range(cols):
            if diff.crop((c * CELL, r * CELL, min(w, (c + 1) * CELL), min(h, (r + 1) * CELL))).getbbox():
                hot.add((r, c))
    boxes = []
    while hot:  # flood-fill neighbouring cells into regions
        stack = [hot.pop()]
        cells = []
        while stack:
            r, c = stack.pop()
            cells.append((r, c))
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    nb = (r + dr, c + dc)
                    if nb in hot:
                        hot.remove(nb)
                        stack.append(nb)
        r0, r1 = min(r for r, _ in cells), max(r for r, _ in cells)
        c0, c1 = min(c for _, c in cells), max(c for _, c in cells)
        boxes.append((c0 * CELL, r0 * CELL, min(w, (c1 + 1) * CELL), min(h, (r1 + 1) * CELL)))
    return boxes


def _words(page) -> list[str]:
    return re.findall(r"\S+", page.get_textpage().get_text_range())


def _snippet(words: list[str], limit: int = 40) -> str:
    s = " ".join(words[:limit])
    return s + (" …" if len(words) > limit else "")


class CompareOptions(PdfPasswordOptions):
    dpi: int = Field(90, ge=50, le=150, title="Detail", description="Higher finds smaller visual changes; slower.",
                     json_schema_extra=ui(unit="dpi", advanced=True))


def compare(ctx: Ctx) -> None:
    from PIL import Image, ImageDraw
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    o: CompareOptions = ctx.options  # type: ignore[assignment]
    if len(ctx.inputs) != 2:
        raise ConversionError("invalid_input", "Add exactly two PDFs: the original first, then the changed version.")
    a_in, b_in = ctx.inputs
    da, db = open_pdfium(a_in.path, o.password), open_pdfium(b_in.path, o.password)
    na, nb = len(da), len(db)
    n = min(max(na, nb), MAX_COMPARE_PAGES)
    scale = o.dpi / 72
    st = getSampleStyleSheet()
    pagesize = landscape(A4)
    col_w = (pagesize[0] - 30 * mm) / 2
    col_h = pagesize[1] - 45 * mm
    story_pages = []
    changes: list[tuple[int, str]] = []
    changed_pages: list[int] = []
    for i in range(n):
        ctx.progress(i, n, stage=f"Comparing page {i + 1} of {n}", force=True)
        pa = da[i] if i < na else None
        pb = db[i] if i < nb else None
        ia = pa.render(scale=scale).to_pil().convert("RGB") if pa else None
        ib = pb.render(scale=scale).to_pil().convert("RGB") if pb else None
        boxes = []
        if ia and ib:
            ib_cmp = ib if ib.size == ia.size else ib.resize(ia.size)
            boxes = _changed_boxes(ia, ib_cmp)
        wa, wb = (_words(pa) if pa else []), (_words(pb) if pb else [])
        removed, added = [], []
        for tag, a0, a1, b0, b1 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
            if tag in ("delete", "replace"):
                removed += wa[a0:a1]
            if tag in ("insert", "replace"):
                added += wb[b0:b1]
        if not (boxes or removed or added or pa is None or pb is None):
            continue
        changed_pages.append(i + 1)
        if pa is None:
            changes.append((i + 1, "Only in the changed file (page added)."))
        elif pb is None:
            changes.append((i + 1, "Only in the original file (page removed)."))
        else:
            bits = []
            if removed:
                bits.append(f"<b>Removed:</b> {escape(_snippet(removed))}")
            if added:
                bits.append(f"<b>Added:</b> {escape(_snippet(added))}")
            if not bits:
                bits.append(f"{len(boxes)} visual change{'s' if len(boxes) != 1 else ''} (no text changes).")
            changes.append((i + 1, "<br/>".join(bits)))
        # side-by-side page with changed regions outlined
        cells = []
        for img, label in ((ia, "Original"), (ib, "Changed")):
            if img is None:
                ph = Image.new("RGB", ((ia or ib).width, (ia or ib).height), (235, 235, 235))
                ImageDraw.Draw(ph).text((20, 20), "No such page in this file", fill=(90, 90, 90))
                img = ph
            else:
                img = img.copy()
                d = ImageDraw.Draw(img)
                sx, sy = (img.width / ia.width, img.height / ia.height) if ia else (1, 1)
                for (x0, y0, x1, y1) in boxes:
                    d.rectangle([x0 * sx - 3, y0 * sy - 3, x1 * sx + 3, y1 * sy + 3], outline=(220, 38, 38), width=3)
            buf = io.BytesIO()
            img.save(buf, "PNG")
            buf.seek(0)
            s = min(col_w / img.width, col_h / img.height)
            cells.append([Paragraph(f"<b>{label}</b> — page {i + 1}", st["BodyText"]),
                          RLImage(buf, width=img.width * s, height=img.height * s)])
        t = Table([[cells[0][0], cells[1][0]], [cells[0][1], cells[1][1]]], colWidths=[col_w, col_w])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story_pages += [PageBreak(), t]

    out = ctx.out_path("comparison.pdf")
    doc = SimpleDocTemplate(str(out), pagesize=pagesize, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                            bottomMargin=15 * mm, title="PDF comparison")
    story = [Paragraph("PDF comparison", st["Title"]),
             Paragraph(f"<b>Original:</b> {escape(a_in.name or 'file 1')} ({na} page{'s' if na != 1 else ''})", st["BodyText"]),
             Paragraph(f"<b>Changed:</b> {escape(b_in.name or 'file 2')} ({nb} page{'s' if nb != 1 else ''})", st["BodyText"]),
             Spacer(1, 6 * mm)]
    if changed_pages:
        story.append(Paragraph(f"<b>{len(changed_pages)} of {n} page{'s' if n != 1 else ''} differ:</b> "
                               + ", ".join(str(p) for p in changed_pages), st["BodyText"]))
        story.append(Spacer(1, 3 * mm))
        for p, text in changes:
            story.append(Paragraph(f"<b>Page {p}.</b> {text}", st["BodyText"]))
            story.append(Spacer(1, 2 * mm))
        story.append(Paragraph("The following pages show each changed page side by side, with changed areas outlined "
                               "in red.", st["Italic"]))
    else:
        story.append(Paragraph("<b>No differences found.</b> The pages look the same and contain the same text.",
                               st["BodyText"]))
    if max(na, nb) > MAX_COMPARE_PAGES:
        story.append(Paragraph(f"Only the first {MAX_COMPARE_PAGES} pages were compared.", st["Italic"]))
    doc.build(story + story_pages)
    ctx.info.update(changed_pages=changed_pages, pages_original=na, pages_changed=nb)
    ctx.notice(f"{len(changed_pages)} page{'s' if len(changed_pages) != 1 else ''} differ." if changed_pages
               else "No differences found: the two PDFs look the same and contain the same text.")
    ctx.add_output(out, "pdf", label="Comparison report")


register(Operation(
    id="pdf.compare", category="documents", label="Compare PDFs",
    description="Spot the differences between two versions of a PDF: a report lists changed text and shows each "
                "changed page side by side. Add the original first.",
    inputs=("pdf",), outputs=("pdf",), cardinality="many_to_one", options=CompareOptions, run=compare,
    engines=("pypdfium2", "reportlab", "pillow"), min_inputs=2, max_inputs=2, explicit_pairs=(("pdf", "pdf"),),
    heavy_over_mb=20, slug="compare-pdf", keywords=("diff", "differences", "versions", "changes"),
    limitations=("Compares page by page: if pages were inserted or removed, later pages show as changed.",),
))


# ---------------------------------------------------------------------------
# PDF/A (Ghostscript, AGPL: only with ENABLE_AGPL_ENGINES)


def _srgb_icc(gs: str) -> str:
    candidates = [os.environ.get("UC_SRGB_ICC", "")]
    prefix = Path(os.path.realpath(gs)).parents[1]
    candidates += [str(prefix / "share/ghostscript/iccprofiles/srgb.icc"), "/usr/share/color/icc/ghostscript/srgb.icc",
                   "/usr/share/ghostscript/iccprofiles/srgb.icc"]
    candidates += [str(p) for p in sorted(prefix.glob("share/ghostscript/*/iccprofiles/srgb.icc"))]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise ConversionError("engine_missing", "Ghostscript's sRGB colour profile wasn't found on this server.")


def _ps_string(s: str) -> str:
    return "(" + s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


class PdfaOptions(PdfPasswordOptions):
    level: Literal["2b", "1b", "3b"] = Field("2b", title="PDF/A version",
                                             description="2b suits most documents; 1b for older archiving systems.")


def to_pdfa(ctx: Ctx) -> None:
    o: PdfaOptions = ctx.options  # type: ignore[assignment]
    gs = which("gs", "UC_GS")
    icc = _srgb_icc(gs)
    n = len(open_pdfium(ctx.input.path, o.password))
    part = o.level[0]
    defs = ctx.work_dir / "pdfa_def.ps"
    defs.write_text("%!\n"
                    f"/ICCProfile {_ps_string(icc)} def\n"
                    "[/_objdef {icc_PDFA} /type /stream /OBJ pdfmark\n"
                    "[{icc_PDFA} <</N 3>> /PUT pdfmark\n"
                    "[{icc_PDFA} ICCProfile (r) file /PUT pdfmark\n"
                    "[/_objdef {OutputIntent_PDFA} /type /dict /OBJ pdfmark\n"
                    "[{OutputIntent_PDFA} << /Type /OutputIntent /S /GTS_PDFA1 /DestOutputProfile {icc_PDFA} "
                    "/OutputConditionIdentifier (sRGB) /Info (sRGB IEC61966-2.1) >> /PUT pdfmark\n"
                    "[{Catalog} <</OutputIntents [ {OutputIntent_PDFA} ]>> /PUT pdfmark\n")
    out = ctx.default_out("pdf")
    cmd = [gs, f"-dPDFA={part}", "-dBATCH", "-dNOPAUSE", "-dSAFER", "-dNOOUTERSAVE", "-sDEVICE=pdfwrite",
           "-dPDFACompatibilityPolicy=1", "-sColorConversionStrategy=RGB", f"--permit-file-read={icc}",
           f"--permit-file-read={defs}", f"-sOutputFile={out}"]
    if o.password:
        cmd.append(f"-sPDFPassword={o.password}")
    cmd += [str(defs), str(ctx.input.path)]

    def line(b: bytes) -> None:
        m = re.match(rb"^Page (\d+)", b)
        if m:
            ctx.progress(int(m.group(1)), n, stage=f"Converting page {int(m.group(1))} of {n}")

    ctx.stage("Converting with Ghostscript")
    ctx.run(cmd, on_line=line, error_message="Ghostscript couldn't convert this PDF to PDF/A.")
    pdf = open_pike(out, None)
    meta = pdf.open_metadata()
    if str(meta.get("pdfaid:part", "")) != part or "/OutputIntents" not in pdf.Root:
        raise ConversionError("engine_error", "Ghostscript didn't produce a PDF/A file for this document.")
    ctx.info.update(pdfa=f"PDF/A-{o.level.upper()}", pages=len(pdf.pages))
    ctx.notice(f"Converted to PDF/A-{o.level.upper()} with Ghostscript: fonts embedded, sRGB output intent added. It "
               "hasn't been checked with a PDF/A validator such as veraPDF.")
    ctx.add_output(out, "pdf")


register(Operation(
    id="pdf.to_pdfa", category="documents", label="Convert to PDF/A",
    description="Make an archival PDF/A version of a PDF, with fonts embedded and colours defined for long-term "
                "preservation.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=PdfaOptions, run=to_pdfa,
    engines=("ghostscript", "pikepdf", "pypdfium2"), resource_class="heavy", feature_flag="ENABLE_AGPL_ENGINES",
    support="partial", slug="pdf-to-pdfa", keywords=("archive", "pdf/a", "iso 19005", "long-term"),
    limitations=("Uses Ghostscript (AGPL), so it's only offered when the operator enables AGPL engines.",
                 "The result carries PDF/A identification and an sRGB output intent, but isn't checked by a PDF/A "
                 "validator; unusual files (transparency, damaged fonts) may not fully comply."),
))
