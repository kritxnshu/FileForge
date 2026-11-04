"""Page-level PDF tools: organize, crop, resize, pages per sheet, page numbers, repair, extract images, metadata,
flatten."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...context import ConversionError, Ctx
from ...registry import Operation, register, ui
from .pdfcommon import RANGE_FIELD, PdfPasswordOptions, open_pike, open_reader, parse_ranges
from .pdfgeom import check_page, font_for, frame_pypdf, hex_color, stamp

MM = 72 / 25.4
SHEETS_MM = {"A4": (210, 297), "A3": (297, 420), "A5": (148, 210), "Letter": (215.9, 279.4),
             "Legal": (215.9, 355.6), "Tabloid": (279.4, 431.8)}
NORM = dict(ge=-0.01, le=1.01)


def _write(ctx: Ctx, writer, name: str = "output.pdf"):
    out = ctx.out_path(name)
    with out.open("wb") as f:
        writer.write(f)
    return out


def _save_pike(ctx: Ctx, pdf, name: str = "output.pdf"):
    out = ctx.out_path(name)
    pdf.save(out)
    return out


# ---------------------------------------------------------------------------
# organize: reorder, rotate, delete, duplicate and insert blank pages in one go


class OrganizePage(BaseModel):
    source: int | None = Field(None, ge=1, description="Page number from the original PDF; empty for a blank page.")
    rotate: Literal[0, 90, 180, 270] = Field(0, description="Extra clockwise rotation.")


class OrganizeOptions(PdfPasswordOptions):
    pages: list[OrganizePage] = Field(default_factory=list, max_length=5000, title="Pages",
                                      description="The new document, page by page.",
                                      json_schema_extra=ui(widget="pdf-organize"))


def organize(ctx: Ctx) -> None:
    import pikepdf

    o: OrganizeOptions = ctx.options  # type: ignore[assignment]
    src = open_pike(ctx.input.path, o.password)
    n = len(src.pages)
    if not o.pages:
        raise ConversionError("invalid_option", "Arrange the pages first: the new document can't be empty.")
    if all(p.source is None for p in o.pages):
        raise ConversionError("invalid_option", "Keep at least one page from the original PDF.")
    first = src.pages[0].mediabox
    new = pikepdf.new()
    blanks = rotated = 0
    for k, spec in enumerate(o.pages):
        ctx.progress(k, len(o.pages), stage=f"Arranging page {k + 1} of {len(o.pages)}")
        if spec.source is None:
            ref = new.pages[-1] if len(new.pages) else None
            box = ref.mediabox if ref is not None else first
            new.add_blank_page(page_size=(float(box[2]) - float(box[0]), float(box[3]) - float(box[1])))
            blanks += 1
        else:
            new.pages.append(src.pages[check_page(spec.source, n)])
    # Rotations go on after every page is in place: appending a page twice makes a shallow copy of whatever the
    # first copy looks like at that moment, so rotating early would leak into duplicates.
    for page, spec in zip(new.pages, o.pages):
        if spec.source is None:
            continue
        base = int(src.pages[spec.source - 1].obj.get("/Rotate", 0))
        page.obj.Rotate = (base + spec.rotate) % 360
        rotated += 1 if spec.rotate else 0
    kept = {p.source for p in o.pages if p.source}
    ctx.info.update(pages=len(o.pages), blank_pages=blanks, rotated=rotated, removed=n - len(kept))
    ctx.stage("Writing PDF")
    ctx.add_output(_save_pike(ctx, new), "pdf")


register(Operation(
    id="pdf.organize", category="documents", label="Organize pages",
    description="Reorder, rotate, delete, duplicate and add blank pages, all on one screen.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=OrganizeOptions, run=organize, engines=("pikepdf",),
    slug="organize-pdf", keywords=("arrange", "sort", "rearrange", "insert blank page", "duplicate page"),
))


# ---------------------------------------------------------------------------
# crop


class CropArea(BaseModel):
    x: float = Field(..., **NORM)
    y: float = Field(..., **NORM)
    w: float = Field(..., gt=0, le=1.02)
    h: float = Field(..., gt=0, le=1.02)


class CropOptions(PdfPasswordOptions):
    area: CropArea | None = Field(None, title="Area to keep", description="Draw the area to keep on the page.",
                                  json_schema_extra=ui(widget="pdf-editor", mode="crop"))
    margin_top_mm: float = Field(0, ge=0, le=500, title="Trim top", json_schema_extra=ui(unit="mm", advanced=True))
    margin_right_mm: float = Field(0, ge=0, le=500, title="Trim right", json_schema_extra=ui(unit="mm", advanced=True))
    margin_bottom_mm: float = Field(0, ge=0, le=500, title="Trim bottom", json_schema_extra=ui(unit="mm", advanced=True))
    margin_left_mm: float = Field(0, ge=0, le=500, title="Trim left", json_schema_extra=ui(unit="mm", advanced=True))
    pages: str | None = Field(None, title="Pages", description="Leave empty to crop every page.",
                              json_schema_extra=ui(placeholder="All pages"), **RANGE_FIELD)


def crop(ctx: Ctx) -> None:
    from pypdf import PdfWriter
    from pypdf.generic import RectangleObject

    o: CropOptions = ctx.options  # type: ignore[assignment]
    margins = (o.margin_top_mm, o.margin_right_mm, o.margin_bottom_mm, o.margin_left_mm)
    if o.area is None and not any(margins):
        raise ConversionError("invalid_option", "Draw the area to keep, or enter margins to trim.")
    r = open_reader(ctx.input.path, o.password)
    sel = set(parse_ranges(o.pages, len(r.pages)))
    w = PdfWriter()
    for i, page in enumerate(r.pages):
        if i in sel:
            f = frame_pypdf(page)
            if o.area is not None:
                u, v, uw, vh = o.area.x, o.area.y, o.area.w, o.area.h
            else:
                t, rt, b, lf = (m * MM for m in margins)
                u, v = lf / f.width, t / f.height
                uw, vh = 1 - (lf + rt) / f.width, 1 - (t + b) / f.height
            u, v = max(0.0, u), max(0.0, v)
            uw, vh = min(uw, 1 - u), min(vh, 1 - v)
            if uw * f.width < 18 or vh * f.height < 18:
                raise ConversionError("invalid_option", f"That would leave page {i + 1} smaller than 6 mm. Keep a "
                                                        f"bigger area.")
            x0, y0, x1, y1 = f.rect_to_user(u, v, uw, vh)
            box = RectangleObject([x0, y0, x1, y1])
            page.cropbox = box
            page.trimbox = box
        w.add_page(page)
    ctx.stage("Cropping pages")
    ctx.add_output(_write(ctx, w), "pdf")


register(Operation(
    id="pdf.crop", category="documents", label="Crop PDF",
    description="Trim the margins of PDF pages, or keep just an area you draw, on every page or the ones you pick.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=CropOptions, run=crop, engines=("pypdf",),
    slug="crop-pdf", keywords=("trim", "margins", "cut"),
    limitations=("Cropping hides what's outside the area; it isn't deleted from the file. Use Redact to remove "
                 "content permanently.",),
))


# ---------------------------------------------------------------------------
# resize and pages per sheet


def _sheet(size: str, landscape: bool) -> tuple[float, float]:
    w, h = (v * MM for v in SHEETS_MM[size])
    return (max(w, h), min(w, h)) if landscape else (min(w, h), max(w, h))


def _place(sheet, page, x: float, y: float, w: float, h: float, border: bool = False) -> None:
    """Scale `page` (rotation already moved into its content) to fit the box (x, y, w, h) of `sheet`, centred."""
    from pypdf import Transformation

    box = page.cropbox
    pw, ph = float(box.width), float(box.height)
    s = min(w / pw, h / ph)
    tx = x + (w - pw * s) / 2 - float(box.left) * s
    ty = y + (h - ph * s) / 2 - float(box.bottom) * s
    sheet.merge_transformed_page(page, Transformation().scale(s).translate(tx, ty))
    if border:
        def draw(c, f):
            c.setLineWidth(0.6)
            c.setStrokeGray(0.6)
            c.rect(x + (w - pw * s) / 2, y + (h - ph * s) / 2, pw * s, ph * s)

        stamp(sheet, draw)


class ResizeOptions(PdfPasswordOptions):
    size: Literal["A4", "Letter", "Legal", "A3", "A5", "Tabloid"] = Field("A4", title="Page size")
    orientation: Literal["auto", "portrait", "landscape"] = Field("auto", title="Orientation",
                                                                  description="auto keeps each page's shape.")
    margin_mm: float = Field(0, ge=0, le=50, title="Margins", json_schema_extra=ui(unit="mm"))


def resize(ctx: Ctx) -> None:
    from pypdf import PageObject, PdfWriter

    o: ResizeOptions = ctx.options  # type: ignore[assignment]
    r = open_reader(ctx.input.path, o.password)
    w = PdfWriter()
    n = len(r.pages)
    m = o.margin_mm * MM
    for i, page in enumerate(r.pages):
        ctx.progress(i, n, stage=f"Resizing page {i + 1} of {n}")
        page.transfer_rotation_to_content()
        landscape = o.orientation == "landscape" or (o.orientation == "auto" and float(page.cropbox.width) > float(page.cropbox.height))
        sw, sh = _sheet(o.size, landscape)
        sheet = PageObject.create_blank_page(width=sw, height=sh)
        _place(sheet, page, m, m, sw - 2 * m, sh - 2 * m)
        w.add_page(sheet)
    ctx.add_output(_write(ctx, w), "pdf")


register(Operation(
    id="pdf.resize", category="documents", label="Resize pages",
    description="Fit every page onto A4, Letter or another paper size, scaled to fit with optional margins.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=ResizeOptions, run=resize, engines=("pypdf",),
    slug="resize-pdf", keywords=("page size", "a4", "letter", "scale"),
))


NUP_GRID = {2: (2, 1, True), 4: (2, 2, False), 6: (3, 2, True), 9: (3, 3, False), 16: (4, 4, False)}


class NupOptions(PdfPasswordOptions):
    per_sheet: Literal[2, 4, 6, 9, 16] = Field(2, title="Pages per sheet")
    size: Literal["A4", "Letter", "A3", "Legal"] = Field("A4", title="Sheet size")
    border: bool = Field(False, title="Draw a border around each page")
    margin_mm: float = Field(8, ge=0, le=40, title="Margins", json_schema_extra=ui(unit="mm", advanced=True))


def nup(ctx: Ctx) -> None:
    from pypdf import PageObject, PdfWriter

    o: NupOptions = ctx.options  # type: ignore[assignment]
    r = open_reader(ctx.input.path, o.password)
    cols, rows, landscape = NUP_GRID[o.per_sheet]
    sw, sh = _sheet(o.size, landscape)
    m = o.margin_mm * MM
    gap = 4 * MM
    cell_w = (sw - 2 * m - (cols - 1) * gap) / cols
    cell_h = (sh - 2 * m - (rows - 1) * gap) / rows
    w = PdfWriter()
    pages = list(r.pages)
    sheets = (len(pages) + o.per_sheet - 1) // o.per_sheet
    for s in range(sheets):
        ctx.progress(s, sheets, stage=f"Laying out sheet {s + 1} of {sheets}")
        sheet = PageObject.create_blank_page(width=sw, height=sh)
        for k, page in enumerate(pages[s * o.per_sheet:(s + 1) * o.per_sheet]):
            page.transfer_rotation_to_content()
            c, rw = k % cols, k // cols
            x = m + c * (cell_w + gap)
            y = sh - m - (rw + 1) * cell_h - rw * gap
            _place(sheet, page, x, y, cell_w, cell_h, o.border)
        w.add_page(sheet)
    ctx.info.update(sheets=sheets)
    ctx.add_output(_write(ctx, w), "pdf")


register(Operation(
    id="pdf.nup", category="documents", label="Pages per sheet",
    description="Print-friendly layouts: put 2, 4, 6, 9 or 16 pages on each sheet, in reading order.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=NupOptions, run=nup, engines=("pypdf",),
    slug="pdf-pages-per-sheet", keywords=("n-up", "2 up", "4 up", "handout", "print"),
))


# ---------------------------------------------------------------------------
# page numbers, headers and footers

POSITIONS = Literal["bottom-center", "bottom-right", "bottom-left", "top-center", "top-right", "top-left"]


class PageNumberOptions(PdfPasswordOptions):
    text: str = Field("{n}", min_length=1, max_length=200, title="Text",
                      description="{n} is the page number and {total} the last number, e.g. “Page {n} of {total}”. "
                                  "Without {n} it's a header or footer.")
    position: POSITIONS = Field("bottom-center", title="Position")
    start_at: int = Field(1, ge=0, le=100000, title="First number")
    font: Literal["helvetica", "helvetica-bold", "times", "times-bold", "courier"] = Field("helvetica", title="Font")
    size: float = Field(11, ge=5, le=72, title="Font size", json_schema_extra=ui(unit="pt"))
    color: str = Field("#333333", pattern=r"^#[0-9a-fA-F]{6}$", title="Color", json_schema_extra=ui(widget="color"))
    margin_mm: float = Field(12, ge=3, le=60, title="Distance from the edge", json_schema_extra=ui(unit="mm"))
    pages: str | None = Field(None, title="Pages", description="Leave empty for every page, e.g. 2-last to skip a cover.",
                              json_schema_extra=ui(placeholder="All pages", advanced=True), **RANGE_FIELD)


def page_numbers(ctx: Ctx) -> None:
    from pypdf import PdfWriter
    from reportlab.pdfbase.pdfmetrics import stringWidth

    o: PageNumberOptions = ctx.options  # type: ignore[assignment]
    r = open_reader(ctx.input.path, o.password)
    sel = parse_ranges(o.pages, len(r.pages))
    number = {page: o.start_at + k for k, page in enumerate(sel)}
    total = o.start_at + len(sel) - 1
    w = PdfWriter()
    n = len(r.pages)
    for i, page in enumerate(r.pages):
        if i in number:
            ctx.progress(i, n, stage=f"Numbering page {i + 1} of {n}")
            label = o.text.replace("{n}", str(number[i])).replace("{total}", str(total))
            font = font_for(label, o.font)

            def draw(c, f, label=label, font=font):
                c.setFont(font, o.size)
                c.setFillColor(hex_color(o.color))
                m = o.margin_mm * MM
                tw = stringWidth(label, font, o.size)
                vert, horiz = o.position.split("-")
                y = f.height - m - o.size * 0.75 if vert == "top" else m
                x = {"left": m, "center": (f.width - tw) / 2, "right": f.width - m - tw}[horiz]
                c.drawString(x, y, label)

            stamp(page, draw)
        w.add_page(page)
    ctx.info.update(numbered=len(sel))
    ctx.add_output(_write(ctx, w), "pdf")


register(Operation(
    id="pdf.page_numbers", category="documents", label="Add page numbers",
    description="Number pages, or add a header or footer such as “Page 3 of 10” or a document title, in the "
                "position, font and size you choose.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=PageNumberOptions, run=page_numbers,
    engines=("pypdf", "reportlab"), slug="add-page-numbers", keywords=("numbering", "header", "footer", "bates"),
))


# ---------------------------------------------------------------------------
# repair


class RepairOptions(PdfPasswordOptions):
    pass


def repair(ctx: Ctx) -> None:
    import pikepdf

    o: RepairOptions = ctx.options  # type: ignore[assignment]
    out = ctx.default_out("pdf")
    ctx.stage("Rebuilding the file structure")
    try:
        pdf = pikepdf.open(str(ctx.input.path), password=o.password or "", attempt_recovery=True)
        problems = len(pdf.get_warnings())
        pages = len(pdf.pages)
        if pages == 0:
            raise pikepdf.PdfError("no pages")
        pdf.save(out, fix_metadata_version=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
        engine = "qpdf"
    except pikepdf.PasswordError as e:
        raise ConversionError("password_required" if not o.password else "wrong_password",
                              "This PDF is password-protected — enter its password to repair it." if not o.password
                              else "That password is incorrect for this PDF. Check it and try again.") from e
    except pikepdf.PdfError:
        # Second opinion: PDFium has its own recovery heuristics.
        import pypdfium2 as pdfium

        try:
            doc = pdfium.PdfDocument(str(ctx.input.path), password=o.password or None)
            pages = len(doc)
            if pages == 0:
                raise ConversionError("corrupt_input", "This PDF is too damaged to repair: no pages could be recovered.")
            with out.open("wb") as f:
                doc.save(f)
            problems = 1
            engine = "pdfium"
        except pdfium.PdfiumError as e:
            raise ConversionError("corrupt_input", "This PDF is too damaged to repair: no pages could be recovered.") from e
    # The result must open cleanly with a strict, independent parser.
    from pypdf import PdfReader

    try:
        check = PdfReader(str(out), strict=True)
        _ = len(check.pages)
    except Exception as e:
        raise ConversionError("corrupt_input", "We rebuilt the file, but it still isn't a valid PDF. It may be too "
                                               "damaged to recover.") from e
    ctx.info.update(problems_fixed=problems, pages=pages, engine=engine)
    ctx.notice(f"Recovered {pages} page{'s' if pages != 1 else ''}. "
               + (f"Fixed {problems} structural problem{'s' if problems != 1 else ''}." if problems
                  else "No structural problems were found; the file was rewritten cleanly."))
    ctx.add_output(out, "pdf")


register(Operation(
    id="pdf.repair", category="documents", label="Repair PDF",
    description="Rebuild a damaged PDF's internal structure and recover its pages.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=RepairOptions, run=repair,
    engines=("pikepdf", "pypdfium2", "pypdf"), slug="repair-pdf", keywords=("fix", "corrupt", "broken", "recover"),
    limitations=("Recovers what the file still contains; content that was cut off or overwritten can't be brought back.",),
))


# ---------------------------------------------------------------------------
# extract embedded images


class ExtractImagesOptions(PdfPasswordOptions):
    min_size: int = Field(32, ge=1, le=4000, title="Skip images smaller than",
                          description="Ignores icons and decorations below this width or height.",
                          json_schema_extra=ui(unit="px", advanced=True))


def extract_images(ctx: Ctx) -> None:
    from pikepdf import PdfImage
    from PIL import Image

    from ...safety import max_image_pixels

    o: ExtractImagesOptions = ctx.options  # type: ignore[assignment]
    pdf = open_pike(ctx.input.path, o.password)
    seen: set = set()
    n = len(pdf.pages)
    count = skipped = 0
    for pi, page in enumerate(pdf.pages):
        ctx.progress(pi, n, stage=f"Scanning page {pi + 1} of {n}")
        for k, (_, raw) in enumerate(page.images.items()):
            if raw.objgen in seen:
                continue
            seen.add(raw.objgen)
            try:
                img = PdfImage(raw)
                if img.width < o.min_size or img.height < o.min_size:
                    skipped += 1
                    continue
                if img.width * img.height > max_image_pixels():
                    skipped += 1
                    continue
                stem = f"page{pi + 1:03d}-image{k + 1}"
                if raw.get("/Filter") == "/DCTDecode" and str(img.colorspace) in ("/DeviceRGB", "/DeviceGray"):
                    out = ctx.out_path(stem + ".jpg")
                    out.write_bytes(raw.read_raw_bytes())
                    fmt = "jpg"
                else:
                    pil = img.as_pil_image()
                    if pil.mode not in ("RGB", "RGBA", "L", "LA", "1", "P"):
                        pil = pil.convert("RGB")
                    out = ctx.out_path(stem + ".png")
                    pil.save(out, "PNG")
                    fmt = "png"
                with Image.open(out) as check:
                    check.verify()
            except Exception:
                skipped += 1
                continue
            count += 1
            ctx.add_output(out, fmt, label=f"Page {pi + 1}, image {k + 1}")
    if not count:
        raise ConversionError("no_images", "This PDF doesn't contain any embedded images we could extract. To save "
                                           "whole pages as pictures, use PDF to JPG instead.")
    if skipped:
        ctx.notice(f"Skipped {skipped} small or unsupported image{'s' if skipped != 1 else ''}.")
    ctx.notice("Photos stored as JPEG are extracted exactly as embedded; other images are saved as PNG.")
    ctx.info.update(images=count)


register(Operation(
    id="pdf.extract_images", category="documents", label="Extract images",
    description="Save the photos and pictures embedded in a PDF as separate image files, at their original quality.",
    inputs=("pdf",), outputs=("png",), cardinality="one_to_many", options=ExtractImagesOptions, run=extract_images,
    engines=("pikepdf", "pillow"), slug="extract-pdf-images", keywords=("pictures", "photos", "save images"),
))


# ---------------------------------------------------------------------------
# metadata


class MetadataOptions(PdfPasswordOptions):
    mode: Literal["edit", "remove"] = Field("edit", title="What to do",
                                            description="edit: set the fields below (empty ones stay as they are); "
                                                        "remove: delete all document properties.")
    title: str | None = Field(None, max_length=500, title="Title")
    author: str | None = Field(None, max_length=500, title="Author")
    subject: str | None = Field(None, max_length=1000, title="Subject")
    keywords: str | None = Field(None, max_length=1000, title="Keywords", description="Separate with commas.")


DOCINFO = {"title": "/Title", "author": "/Author", "subject": "/Subject", "keywords": "/Keywords"}
XMP = {"title": "dc:title", "author": "dc:creator", "subject": "dc:description", "keywords": "pdf:Keywords"}


def metadata(ctx: Ctx) -> None:
    import pikepdf

    o: MetadataOptions = ctx.options  # type: ignore[assignment]
    pdf = open_pike(ctx.input.path, o.password)
    before = {k: str(pdf.docinfo.get(v, "")) for k, v in DOCINFO.items() if pdf.docinfo.get(v)}
    if o.mode == "remove":
        for key in list(pdf.docinfo.keys()):
            del pdf.docinfo[key]
        if "/Metadata" in pdf.Root:
            del pdf.Root.Metadata
        ctx.notice("Removed all document properties" + (f" ({', '.join(before)})." if before else "."))
    else:
        changes = {k: getattr(o, k) for k in DOCINFO if getattr(o, k)}
        if not changes:
            raise ConversionError("invalid_option", "Enter at least one property to change, or choose “remove”.")
        with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
            for k, v in changes.items():
                pdf.docinfo[DOCINFO[k]] = pikepdf.String(v)
                meta[XMP[k]] = [v] if k == "author" else v
        ctx.notice("Updated: " + ", ".join(changes) + ".")
    ctx.info["before"] = before
    ctx.add_output(_save_pike(ctx, pdf), "pdf")


register(Operation(
    id="pdf.metadata", category="documents", label="Edit PDF properties",
    description="Change a PDF's title, author, subject and keywords, or remove all of its properties for privacy.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=MetadataOptions, run=metadata, engines=("pikepdf",),
    slug="edit-pdf-metadata", keywords=("metadata", "title", "author", "properties", "remove metadata"),
))


# ---------------------------------------------------------------------------
# flatten


class FlattenOptions(PdfPasswordOptions):
    pass


def flatten(ctx: Ctx) -> None:
    o: FlattenOptions = ctx.options  # type: ignore[assignment]
    pdf = open_pike(ctx.input.path, o.password)
    annots = sum(len(p.obj.get("/Annots", [])) for p in pdf.pages)
    fields = len(pdf.Root.AcroForm.get("/Fields", [])) if "/AcroForm" in pdf.Root else 0
    if not annots and not fields:
        raise ConversionError("nothing_to_flatten", "This PDF has no form fields or annotations to flatten.")
    ctx.stage("Flattening")
    pdf.generate_appearance_streams()
    pdf.flatten_annotations(mode="all")
    if "/AcroForm" in pdf.Root:
        del pdf.Root.AcroForm
    ctx.info.update(annotations=annots, fields=fields)
    ctx.notice("Form fields and annotations are now part of the page and can't be edited.")
    ctx.add_output(_save_pike(ctx, pdf), "pdf")


register(Operation(
    id="pdf.flatten", category="documents", label="Flatten PDF",
    description="Make filled-in forms, comments and stamps a permanent part of the page, so they can't be changed.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=FlattenOptions, run=flatten, engines=("pikepdf",),
    slug="flatten-pdf", keywords=("forms", "annotations", "lock"),
))

