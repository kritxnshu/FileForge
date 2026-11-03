"""PDF tools: render pages, images → PDF, merge/split/extract/delete/reorder/rotate,
watermark, protect/unlock, compress."""

from __future__ import annotations

import io
import secrets
import shutil
from typing import Literal

from PIL import Image, ImageOps
from pydantic import Field

from ...context import ConversionError, Ctx
from ...registry import Operation, Options, register, ui
from ..images.raster import has_alpha, open_image
from .pdfcommon import RANGE_FIELD, PdfPasswordOptions, open_pdfium, open_pike, open_reader, parse_ranges

RASTER_IN = ("png", "jpg", "webp", "gif", "bmp", "tiff", "heic", "avif")


def _writer_from(reader, indices):
    from pypdf import PdfWriter

    w = PdfWriter()
    for i in indices:
        w.add_page(reader.pages[i])
    return w


def _write(ctx: Ctx, writer, name: str = "output.pdf"):
    out = ctx.out_path(name)
    with out.open("wb") as f:
        writer.write(f)
    return out


# ---------------------------------------------------------------------------
# PDF → images


class PdfToImagesOptions(PdfPasswordOptions):
    dpi: int = Field(150, ge=36, le=600, title="Resolution", description="Higher DPI gives sharper, larger images.",
                     json_schema_extra=ui(unit="dpi"))
    pages: str | None = Field(None, title="Pages", description="Leave empty for all pages, or e.g. 1-3,7.",
                              json_schema_extra=ui(placeholder="All pages"), **RANGE_FIELD)
    quality: int = Field(90, ge=1, le=100, title="Quality", json_schema_extra=ui(widget="slider", targets=("jpg",)))


def pdf_to_images(ctx: Ctx) -> None:
    from ...safety import max_image_pixels

    o: PdfToImagesOptions = ctx.options  # type: ignore[assignment]
    doc = open_pdfium(ctx.input.path, o.password)
    n = len(doc)
    idx = parse_ranges(o.pages, n)
    scale = o.dpi / 72
    width = len(str(n))
    for k, i in enumerate(idx):
        ctx.progress(k, len(idx), stage=f"Rendering page {k + 1} of {len(idx)}", force=True)
        page = doc[i]
        w, h = page.get_size()
        if w * scale * h * scale > max_image_pixels():
            raise ConversionError("too_many_pixels", f"Page {i + 1} would be too large at {o.dpi} DPI. Choose a lower resolution.")
        img = page.render(scale=scale).to_pil()
        out = ctx.out_path(f"page-{i + 1:0{max(3, width)}d}.{'jpg' if ctx.target == 'jpg' else 'png'}")
        if ctx.target == "jpg":
            img.convert("RGB").save(out, "JPEG", quality=o.quality, optimize=True)
        else:
            img.save(out, "PNG", optimize=True)
        ctx.add_output(out, ctx.target, label=f"Page {i + 1}")
    ctx.progress(len(idx), len(idx), stage="Rendered", force=True)
    ctx.info["pages"] = len(idx)


register(Operation(
    id="pdf.to_images", category="documents", label="PDF to images",
    description="Render each PDF page as a PNG or JPG image at the resolution you choose.",
    inputs=("pdf",), outputs=("png", "jpg"), cardinality="one_to_many", options=PdfToImagesOptions, run=pdf_to_images,
    engines=("pypdfium2",), heavy_over_mb=20, keywords=("pages", "render", "pdf to jpg", "pdf to png"),
))


# ---------------------------------------------------------------------------
# images → PDF


PAGE_SIZES_MM = {"A4": (210, 297), "Letter": (215.9, 279.4), "Legal": (215.9, 355.6), "A3": (297, 420), "A5": (148, 210)}


class ImagesToPdfOptions(Options):
    page_size: Literal["image", "A4", "Letter", "Legal", "A3", "A5"] = Field(
        "image", title="Page size", description="image: each page is exactly the size of its image.")
    orientation: Literal["auto", "portrait", "landscape"] = Field("auto", title="Orientation",
                                                                  description="auto matches each image's shape.")
    fit: Literal["fit", "fill", "original"] = Field("fit", title="Placement",
                                                    description="fit: whole image visible; fill: cover the page (may crop edges); original: actual size.")
    margin_mm: float = Field(0, ge=0, le=50, title="Margins", json_schema_extra=ui(unit="mm"))


def images_to_pdf(ctx: Ctx) -> None:
    import img2pdf

    o: ImagesToPdfOptions = ctx.options  # type: ignore[assignment]
    blobs = []
    total = len(ctx.inputs)
    for k, inp in enumerate(ctx.inputs):
        ctx.progress(k, total, stage=f"Adding image {k + 1} of {total}", force=True)
        if inp.format == "jpg":
            im = open_image(ctx, inp.path)
            if im.mode in ("RGB", "L", "CMYK"):
                blobs.append(inp.path.read_bytes())  # embedded as-is: lossless
                continue
        im = open_image(ctx, inp.path)
        if getattr(im, "n_frames", 1) > 1:
            im.seek(0)
            ctx.notice(f"Image {k + 1} is animated; only its first frame was added.")
        im = ImageOps.exif_transpose(im) or im
        if has_alpha(im):
            rgba = im.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.getchannel("A"))
            im = bg
        elif im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "PNG")
        blobs.append(buf.getvalue())
    layout = None
    if o.page_size != "image":
        w, h = PAGE_SIZES_MM[o.page_size]
        if o.orientation == "landscape":
            w, h = max(w, h), min(w, h)
        pagesize = (img2pdf.mm_to_pt(w), img2pdf.mm_to_pt(h))
        fit = {"fit": img2pdf.FitMode.into, "fill": img2pdf.FitMode.fill, "original": img2pdf.FitMode.shrink}[o.fit]
        border = (img2pdf.mm_to_pt(o.margin_mm),) * 2 if o.margin_mm else None
        layout = img2pdf.get_layout_fun(pagesize, imgsize=None, border=border, fit=fit,
                                        auto_orient=o.orientation == "auto")
    elif o.margin_mm:
        border = (img2pdf.mm_to_pt(o.margin_mm),) * 2
        layout = img2pdf.get_layout_fun(None, None, border, img2pdf.FitMode.into, False)
    ctx.stage("Building PDF")
    out = ctx.default_out("pdf")
    try:
        kw = {"layout_fun": layout} if layout else {}
        out.write_bytes(img2pdf.convert(blobs, rotation=img2pdf.Rotation.ifvalid, **kw))
    except img2pdf.ImageOpenError as e:
        raise ConversionError("corrupt_input", "One of the images couldn't be read.") from e
    ctx.info["pages"] = total
    ctx.add_output(out, "pdf")


register(Operation(
    id="pdf.from_images", category="documents", label="Images to PDF",
    description="Combine images into a PDF, one image per page. JPGs are embedded without re-compression.",
    inputs=RASTER_IN, outputs=("pdf",), cardinality="many_to_one", options=ImagesToPdfOptions, run=images_to_pdf,
    engines=("img2pdf", "pillow"), format_engines={"heic": ("pillow-heif",), "avif": ("avif",)}, min_inputs=1,
    max_inputs=200, slug="images-to-pdf", keywords=("jpg to pdf", "png to pdf", "photos", "scan"),
))


# ---------------------------------------------------------------------------
# merge / split / extract / delete / reorder / rotate


class MergeOptions(PdfPasswordOptions):
    pass


def merge(ctx: Ctx) -> None:
    from pypdf import PdfWriter

    o: MergeOptions = ctx.options  # type: ignore[assignment]
    w = PdfWriter()
    total = len(ctx.inputs)
    for k, inp in enumerate(ctx.inputs):
        ctx.progress(k, total, stage=f"Adding file {k + 1} of {total}", force=True)
        r = open_reader(inp.path, o.password)
        for p in r.pages:
            w.add_page(p)
    ctx.stage("Writing PDF")
    ctx.info["pages"] = len(w.pages)
    ctx.add_output(_write(ctx, w), "pdf")


register(Operation(
    id="pdf.merge", category="documents", label="Merge PDFs",
    description="Combine several PDFs into one, in the order you choose.",
    inputs=("pdf",), outputs=("pdf",), cardinality="many_to_one", options=MergeOptions, run=merge,
    engines=("pypdf",), min_inputs=2, max_inputs=100, slug="merge-pdf", keywords=("combine", "join"),
))


class SplitOptions(PdfPasswordOptions):
    mode: Literal["every_page", "ranges", "chunks"] = Field("every_page", title="Split into",
                                                            description="every_page: one file per page; ranges: one file per range; chunks: files of N pages.")
    ranges: str | None = Field(None, title="Ranges", description="One file per range, e.g. 1-3,4-6,7.",
                               json_schema_extra=ui(placeholder="1-3,4-6"), **RANGE_FIELD)
    chunk_size: int = Field(2, ge=1, le=1000, title="Pages per file")


def split(ctx: Ctx) -> None:
    o: SplitOptions = ctx.options  # type: ignore[assignment]
    r = open_reader(ctx.input.path, o.password)
    n = len(r.pages)
    if o.mode == "every_page":
        groups = [[i] for i in range(n)]
    elif o.mode == "chunks":
        groups = [list(range(i, min(n, i + o.chunk_size))) for i in range(0, n, o.chunk_size)]
    else:
        if not o.ranges:
            raise ConversionError("invalid_option", "Enter the ranges to split into, e.g. 1-3,4-6.")
        groups = [parse_ranges(part, n) for part in o.ranges.split(",") if part.strip()]
    for k, g in enumerate(groups):
        ctx.progress(k, len(groups), stage=f"Writing file {k + 1} of {len(groups)}", force=True)
        label = f"Page {g[0] + 1}" if len(g) == 1 else f"Pages {g[0] + 1}-{g[-1] + 1}"
        name = f"pages-{g[0] + 1}" + (f"-{g[-1] + 1}" if len(g) > 1 else "") + ".pdf"
        ctx.add_output(_write(ctx, _writer_from(r, g), name), "pdf", label=label)


register(Operation(
    id="pdf.split", category="documents", label="Split PDF",
    description="Split a PDF into single pages, page ranges, or equal chunks.",
    inputs=("pdf",), outputs=("pdf",), cardinality="one_to_many", options=SplitOptions, run=split, engines=("pypdf",),
    explicit_pairs=(("pdf", "pdf"),), slug="split-pdf", keywords=("separate", "pages"),
))


class PagesOptions(PdfPasswordOptions):
    pages: str = Field("1", title="Pages", description="e.g. 1-3,7 or 2-last.", json_schema_extra=ui(placeholder="1-3,7"),
                       **RANGE_FIELD)


def extract_pages(ctx: Ctx) -> None:
    o: PagesOptions = ctx.options  # type: ignore[assignment]
    r = open_reader(ctx.input.path, o.password)
    idx = parse_ranges(o.pages, len(r.pages), allow_empty=False)
    ctx.stage("Extracting pages")
    ctx.info["pages"] = len(idx)
    ctx.add_output(_write(ctx, _writer_from(r, idx)), "pdf")


def delete_pages(ctx: Ctx) -> None:
    o: PagesOptions = ctx.options  # type: ignore[assignment]
    r = open_reader(ctx.input.path, o.password)
    n = len(r.pages)
    drop = set(parse_ranges(o.pages, n, allow_empty=False))
    keep = [i for i in range(n) if i not in drop]
    if not keep:
        raise ConversionError("invalid_option", "That would delete every page. Keep at least one page.")
    ctx.stage("Removing pages")
    ctx.info["pages"] = len(keep)
    ctx.add_output(_write(ctx, _writer_from(r, keep)), "pdf")


class ReorderOptions(PdfPasswordOptions):
    order: str = Field(..., title="New page order", description="Every page number once, in the new order, e.g. 3,1,2.",
                       json_schema_extra=ui(placeholder="3,1,2", widget="page-order"), **RANGE_FIELD)


def reorder(ctx: Ctx) -> None:
    o: ReorderOptions = ctx.options  # type: ignore[assignment]
    r = open_reader(ctx.input.path, o.password)
    n = len(r.pages)
    idx = parse_ranges(o.order, n, allow_empty=False)
    if sorted(idx) != list(range(n)):
        missing = sorted(set(range(n)) - set(idx))
        dup = sorted({i for i in idx if idx.count(i) > 1})
        bits = []
        if missing:
            bits.append("missing page " + ", ".join(str(i + 1) for i in missing[:10]))
        if dup:
            bits.append("repeated page " + ", ".join(str(i + 1) for i in dup[:10]))
        raise ConversionError("invalid_option", f"List every page exactly once ({'; '.join(bits)}).")
    ctx.stage("Reordering pages")
    ctx.add_output(_write(ctx, _writer_from(r, idx)), "pdf")


class RotateOptions(PdfPasswordOptions):
    angle: Literal[90, 180, 270] = Field(90, title="Rotate clockwise by", json_schema_extra=ui(unit="°"))
    pages: str | None = Field(None, title="Pages", description="Leave empty to rotate every page.",
                              json_schema_extra=ui(placeholder="All pages"), **RANGE_FIELD)


def rotate(ctx: Ctx) -> None:
    o: RotateOptions = ctx.options  # type: ignore[assignment]
    r = open_reader(ctx.input.path, o.password)
    sel = set(parse_ranges(o.pages, len(r.pages)))
    from pypdf import PdfWriter

    w = PdfWriter()
    for i, p in enumerate(r.pages):
        if i in sel:
            p.rotate(o.angle)
        w.add_page(p)
    ctx.stage("Rotating pages")
    ctx.add_output(_write(ctx, w), "pdf")


for _id, _label, _desc, _opts, _fn, _slug, _kw in [
    ("pdf.extract_pages", "Extract pages", "Make a new PDF from just the pages you pick.", PagesOptions, extract_pages,
     "extract-pdf-pages", ("select pages",)),
    ("pdf.delete_pages", "Delete pages", "Remove pages from a PDF.", PagesOptions, delete_pages, "delete-pdf-pages",
     ("remove pages",)),
    ("pdf.reorder", "Reorder pages", "Change the order of pages in a PDF.", ReorderOptions, reorder, "reorder-pdf-pages",
     ("rearrange", "sort pages")),
    ("pdf.rotate", "Rotate pages", "Rotate all or some pages of a PDF by 90, 180 or 270 degrees.", RotateOptions, rotate,
     "rotate-pdf", ("turn",)),
]:
    register(Operation(id=_id, category="documents", label=_label, description=_desc, inputs=("pdf",), outputs=(),
                       cardinality="transform", options=_opts, run=_fn, engines=("pypdf",), slug=_slug, keywords=_kw))


# ---------------------------------------------------------------------------
# watermark


class WatermarkOptions(PdfPasswordOptions):
    text: str = Field("CONFIDENTIAL", min_length=1, max_length=200, title="Watermark text")
    font_size: int = Field(48, ge=6, le=300, title="Font size", json_schema_extra=ui(unit="pt"))
    color: str = Field("#cc0000", pattern=r"^#[0-9a-fA-F]{6}$", title="Color", json_schema_extra=ui(widget="color"))
    opacity: float = Field(0.25, ge=0.05, le=1, title="Opacity", json_schema_extra=ui(widget="slider", step=0.05))
    position: Literal["diagonal", "center", "top", "bottom"] = Field("diagonal", title="Position")
    pages: str | None = Field(None, title="Pages", json_schema_extra=ui(placeholder="All pages", advanced=True), **RANGE_FIELD)


def _overlay(w: float, h: float, draw) -> "object":
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w, h))
    draw(c, w, h)
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def _stamp(ctx: Ctx, password: str | None, pages: str | None, draw) -> None:
    from pypdf import PdfWriter

    r = open_reader(ctx.input.path, password)
    sel = set(parse_ranges(pages, len(r.pages)))
    w = PdfWriter()
    n = len(r.pages)
    for i, p in enumerate(r.pages):
        if i in sel:
            ctx.progress(i, n, stage=f"Stamping page {i + 1} of {n}")
            box = p.mediabox
            ov = _overlay(float(box.width), float(box.height), draw)
            p.merge_transformed_page(ov, [1, 0, 0, 1, float(box.left), float(box.bottom)])
        w.add_page(p)
    ctx.add_output(_write(ctx, w), "pdf")


def watermark_text(ctx: Ctx) -> None:
    from reportlab.lib.colors import HexColor

    o: WatermarkOptions = ctx.options  # type: ignore[assignment]

    def draw(c, w, h):
        c.setFillColor(HexColor(o.color), alpha=o.opacity)
        c.setFont("Helvetica-Bold", o.font_size)
        if o.position == "diagonal":
            c.translate(w / 2, h / 2)
            c.rotate(45)
            c.drawCentredString(0, -o.font_size / 3, o.text)
        elif o.position == "center":
            c.drawCentredString(w / 2, h / 2 - o.font_size / 3, o.text)
        elif o.position == "top":
            c.drawCentredString(w / 2, h - o.font_size * 1.5, o.text)
        else:
            c.drawCentredString(w / 2, o.font_size * 0.8, o.text)

    _stamp(ctx, o.password, o.pages, draw)


register(Operation(
    id="pdf.watermark", category="documents", label="Add text watermark",
    description="Stamp text such as CONFIDENTIAL or DRAFT on every page, with your choice of size, color and opacity.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=WatermarkOptions, run=watermark_text,
    engines=("pypdf", "reportlab"), slug="watermark-pdf", keywords=("stamp", "draft", "confidential"),
))


class ImageWatermarkOptions(PdfPasswordOptions):
    scale: float = Field(0.4, ge=0.05, le=1, title="Size", description="Width of the image relative to the page.",
                         json_schema_extra=ui(widget="slider", step=0.05))
    opacity: float = Field(0.3, ge=0.05, le=1, title="Opacity", json_schema_extra=ui(widget="slider", step=0.05))
    position: Literal["center", "top-left", "top-right", "bottom-left", "bottom-right"] = Field("center", title="Position")
    pages: str | None = Field(None, title="Pages", json_schema_extra=ui(placeholder="All pages", advanced=True), **RANGE_FIELD)


def watermark_image(ctx: Ctx) -> None:
    from reportlab.lib.utils import ImageReader

    o: ImageWatermarkOptions = ctx.options  # type: ignore[assignment]
    pdfs = [i for i in ctx.inputs if i.format == "pdf"]
    imgs = [i for i in ctx.inputs if i.format != "pdf"]
    if len(pdfs) != 1 or len(imgs) != 1:
        raise ConversionError("invalid_input", "Add exactly one PDF and one image (the watermark).")
    im = open_image(ctx, imgs[0].path)
    im = (ImageOps.exif_transpose(im) or im).convert("RGBA")
    a = im.getchannel("A").point(lambda v: int(v * o.opacity))
    im.putalpha(a)
    reader = ImageReader(im)
    iw, ih = im.size

    def draw(c, w, h):
        dw = w * o.scale
        dh = dw * ih / iw
        pad = 24
        x, y = {"center": ((w - dw) / 2, (h - dh) / 2), "top-left": (pad, h - dh - pad), "top-right": (w - dw - pad, h - dh - pad),
                "bottom-left": (pad, pad), "bottom-right": (w - dw - pad, pad)}[o.position]
        c.drawImage(reader, x, y, dw, dh, mask="auto")

    ctx.inputs = [pdfs[0], *imgs]  # ctx.input is now the PDF to stamp
    _stamp(ctx, o.password, o.pages, draw)


register(Operation(
    id="pdf.watermark_image", category="documents", label="Add image watermark",
    description="Stamp a logo or image on PDF pages. Add one PDF and one image together.",
    inputs=("pdf", "png", "jpg", "webp"), outputs=("pdf",), cardinality="many_to_one", options=ImageWatermarkOptions,
    run=watermark_image, engines=("pypdf", "reportlab", "pillow"), min_inputs=2, max_inputs=2, combine_only=True,
    explicit_pairs=(("pdf", "pdf"), ("png", "pdf"), ("jpg", "pdf"), ("webp", "pdf")), slug="watermark-pdf-image",
    keywords=("logo", "stamp"),
))


# ---------------------------------------------------------------------------
# protect / unlock


class ProtectOptions(Options):
    password: str = Field(..., min_length=1, max_length=128, title="Password to open",
                          json_schema_extra=ui(widget="password"))
    allow_printing: bool = Field(True, title="Allow printing")
    allow_copying: bool = Field(False, title="Allow copying text")
    allow_editing: bool = Field(False, title="Allow editing")
    owner_password: str | None = Field(None, max_length=128, title="Owner password (optional)",
                                       description="Lets you change permissions later. A random one is used if empty.",
                                       json_schema_extra=ui(widget="password", advanced=True))


def protect(ctx: Ctx) -> None:
    import pikepdf

    o: ProtectOptions = ctx.options  # type: ignore[assignment]
    pdf = open_pike(ctx.input.path, None)
    perms = pikepdf.Permissions(print_lowres=o.allow_printing, print_highres=o.allow_printing, extract=o.allow_copying,
                                modify_annotation=o.allow_editing, modify_form=o.allow_editing, modify_other=o.allow_editing,
                                modify_assembly=o.allow_editing, accessibility=True)
    out = ctx.default_out("pdf")
    ctx.stage("Encrypting (AES-256)")
    pdf.save(out, encryption=pikepdf.Encryption(user=o.password, owner=o.owner_password or secrets.token_urlsafe(24),
                                                 R=6, aes=True, allow=perms))
    ctx.notice("Encrypted with AES-256. Keep the password safe — it can't be recovered.")
    ctx.add_output(out, "pdf")


register(Operation(
    id="pdf.protect", category="documents", label="Password-protect PDF",
    description="Encrypt a PDF with AES-256 so it needs a password to open, and choose what readers may do.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=ProtectOptions, run=protect, engines=("pikepdf",),
    slug="protect-pdf", keywords=("encrypt", "lock", "password"),
))


class UnlockOptions(Options):
    password: str | None = Field(None, max_length=256, title="Current password",
                                 description="The password you use to open this PDF.", json_schema_extra=ui(widget="password"))
    confirm_authorized: bool = Field(False, title="I'm authorized to remove this PDF's restrictions",
                                     description="Needed for PDFs that open without a password but restrict printing or copying.")


def unlock(ctx: Ctx) -> None:
    import pikepdf

    o: UnlockOptions = ctx.options  # type: ignore[assignment]
    try:
        pdf = pikepdf.open(str(ctx.input.path), password=o.password or "")
    except pikepdf.PasswordError as e:
        if o.password:
            raise ConversionError("wrong_password", "That password is incorrect for this PDF. Check it and try again.") from e
        raise ConversionError("password_required", "This PDF needs a password to open — enter it to remove the protection.") from e
    except pikepdf.PdfError as e:
        raise ConversionError("corrupt_input", "This PDF is damaged and can't be read.") from e
    if not pdf.is_encrypted:
        raise ConversionError("not_encrypted", "This PDF isn't password-protected, so there's nothing to remove.")
    user_pw_needed = True
    try:
        pikepdf.open(str(ctx.input.path), password="").close()
        user_pw_needed = False
    except pikepdf.PasswordError:
        pass
    if not user_pw_needed and not o.confirm_authorized:
        raise ConversionError("confirmation_required", "This PDF only restricts printing or copying. Confirm you're authorized "
                                                       "to remove those restrictions, then try again.")
    ctx.stage("Removing protection")
    out = ctx.default_out("pdf")
    pdf.save(out)
    ctx.add_output(out, "pdf")


register(Operation(
    id="pdf.unlock", category="documents", label="Remove PDF password",
    description="Remove the password from a PDF you can open. Requires the correct password — nothing is guessed or cracked.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=UnlockOptions, run=unlock, engines=("pikepdf",),
    slug="unlock-pdf", keywords=("decrypt", "remove password"),
))


# ---------------------------------------------------------------------------
# compress


class CompressPdfOptions(PdfPasswordOptions):
    level: Literal["light", "balanced", "strong"] = Field(
        "balanced", title="Compression", description="Stronger compression lowers image quality and resolution.")


PRESETS = {"light": (85, 2400), "balanced": (70, 1600), "strong": (50, 1100)}


def compress_pdf(ctx: Ctx) -> None:
    import pikepdf
    from pikepdf import Name, PdfImage

    o: CompressPdfOptions = ctx.options  # type: ignore[assignment]
    quality, max_px = PRESETS[o.level]
    pdf = open_pike(ctx.input.path, o.password)
    seen: set = set()
    n = len(pdf.pages)
    changed = 0
    for pi, page in enumerate(pdf.pages):
        ctx.progress(pi, n, stage=f"Optimizing page {pi + 1} of {n}")
        for _, raw in page.images.items():
            key = raw.objgen
            if key in seen:
                continue
            seen.add(key)
            try:
                if raw.get("/SMask") is not None or raw.get("/Mask") is not None or raw.get("/ImageMask"):
                    continue
                pimg = PdfImage(raw)
                if pimg.bits_per_component != 8 or str(pimg.colorspace) not in ("/DeviceRGB", "/DeviceGray"):
                    continue
                im = pimg.as_pil_image()
            except Exception:
                continue
            if max(im.size) > max_px:
                im.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
            im = im.convert("L" if im.mode in ("L", "1") else "RGB")
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=quality, optimize=True)
            if len(buf.getvalue()) >= len(raw.read_raw_bytes()):
                continue
            raw.write(buf.getvalue(), filter=Name.DCTDecode)
            raw.Width, raw.Height = im.size
            raw.ColorSpace = Name.DeviceGray if im.mode == "L" else Name.DeviceRGB
            raw.BitsPerComponent = 8
            for k in ("/DecodeParms", "/Decode"):
                if k in raw:
                    del raw[k]
            changed += 1
    ctx.stage("Writing optimized PDF")
    out = ctx.default_out("pdf")
    pdf.remove_unreferenced_resources()
    pdf.save(out, compress_streams=True, recompress_flate=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    before, after = ctx.input.size, out.stat().st_size
    ctx.info.update(input_size=before, output_size=after, images_recompressed=changed)
    if after >= before:
        shutil.copyfile(ctx.input.path, out)
        ctx.info["returned_original"] = True
        ctx.warn("We couldn't make this PDF any smaller, so this download is your original file, unchanged.")
        ctx.add_output(out, "pdf", label="Your original file (already as small as we can make it)")
        return
    ctx.notice(f"Reduced from {before:,} to {after:,} bytes ({round(100 * (before - after) / before)}% smaller); "
               f"{changed} image{'s' if changed != 1 else ''} recompressed.")
    ctx.add_output(out, "pdf")


register(Operation(
    id="pdf.compress", category="documents", label="Compress PDF",
    description="Shrink a PDF by downsampling and recompressing images and optimizing its structure.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=CompressPdfOptions, run=compress_pdf,
    engines=("pikepdf", "pillow"), support="partial", heavy_over_mb=20, slug="compress-pdf",
    limitations=("Savings depend on the content: text-only PDFs shrink little. Images with transparency or unusual "
                 "color spaces are left as they are.",),
    keywords=("reduce size", "optimize", "smaller"),
))
