"""Presentations: LibreOffice conversions, slides → images (chain: → PDF → pypdfium2),
images → PPTX (python-pptx), and PDF → PPTX as image slides (not editable, and labelled so)."""

from __future__ import annotations

import io
from typing import Literal

from PIL import Image, ImageOps
from pydantic import Field

from ... import office
from ...context import ConversionError, Ctx
from ...registry import NoOptions, Operation, Options, register, ui
from ..documents.pdfcommon import RANGE_FIELD, PdfPasswordOptions, open_pdfium, parse_ranges
from ..images.raster import has_alpha, open_image

DECKS = ("pptx", "ppt", "odp")
RASTER_IN = ("png", "jpg", "webp", "gif", "bmp", "tiff", "heic", "avif")


def deck_convert(ctx: Ctx) -> None:
    out = office.convert_to_output(ctx, ctx.input.path, ctx.target)
    ctx.add_output(out)


register(Operation(
    id="pres.office", category="presentations", label="Convert presentation",
    description="Convert PowerPoint and OpenDocument presentations, or save them as PDF, with LibreOffice.",
    inputs=DECKS, outputs=(*DECKS, "pdf"), cardinality="one_to_one", options=NoOptions, run=deck_convert,
    engines=("soffice",), resource_class="heavy", memory_mb=None,
    pair_limitations={**{(s, "ppt"): ("The old .ppt format may simplify newer animations and effects.",) for s in ("pptx", "odp")},
                      **{(s, "pdf"): ("Animations, transitions and embedded media don't carry over to PDF.",) for s in DECKS}},
    keywords=("powerpoint", "slides", "keynote", "impress"),
))


class SlidesToImagesOptions(Options):
    width: int = Field(1920, ge=320, le=7680, title="Image width", json_schema_extra=ui(unit="px"))
    slides: str | None = Field(None, title="Slides", description="Leave empty for every slide, or e.g. 1-3,7.",
                               json_schema_extra=ui(placeholder="All slides"), **RANGE_FIELD)
    quality: int = Field(90, ge=1, le=100, title="Quality", json_schema_extra=ui(widget="slider", targets=("jpg",)))


def slides_to_images(ctx: Ctx) -> None:
    o: SlidesToImagesOptions = ctx.options  # type: ignore[assignment]
    ctx.stage("Converting slides with LibreOffice (step 1 of 2)")
    pdf = office.convert(ctx, ctx.input.path, "pdf")
    doc = open_pdfium(pdf, None)
    idx = parse_ranges(o.slides, len(doc))
    width = len(str(len(doc)))
    for k, i in enumerate(idx):
        ctx.progress(k, len(idx), stage=f"Rendering slide {k + 1} of {len(idx)} (step 2 of 2)", force=True)
        page = doc[i]
        w, _ = page.get_size()
        img = page.render(scale=o.width / w).to_pil()
        out = ctx.out_path(f"slide-{i + 1:0{max(2, width)}d}.{ctx.target}")
        if ctx.target == "jpg":
            img.convert("RGB").save(out, "JPEG", quality=o.quality, optimize=True)
        else:
            img.save(out, "PNG", optimize=True)
        ctx.add_output(out, ctx.target, label=f"Slide {i + 1}")
    ctx.progress(len(idx), len(idx), stage="Rendered", force=True)


register(Operation(
    id="pres.to_images", category="presentations", label="Slides to images",
    description="Save each slide as a PNG or JPG image.", inputs=DECKS, outputs=("png", "jpg"), cardinality="one_to_many",
    options=SlidesToImagesOptions, run=slides_to_images, engines=("soffice", "pypdfium2"), resource_class="heavy",
    memory_mb=None, keywords=("pptx to png", "pptx to jpg", "export slides"),
))


# ---------------------------------------------------------------------------

SLIDE_SIZES = {"16:9": (13.333, 7.5), "4:3": (10.0, 7.5)}


class ImagesToPptxOptions(Options):
    aspect: Literal["16:9", "4:3"] = Field("16:9", title="Slide shape")
    fit: Literal["fit", "fill"] = Field("fit", title="Placement", description="fit: whole image visible; fill: cover the slide (may crop).")
    background: str = Field("#000000", pattern=r"^#[0-9a-fA-F]{6}$", title="Background", json_schema_extra=ui(widget="color"))


def _png_bytes(ctx: Ctx, inp) -> tuple[bytes, tuple[int, int]]:
    im = open_image(ctx, inp.path)
    if getattr(im, "n_frames", 1) > 1:
        im.seek(0)
    im = ImageOps.exif_transpose(im) or im
    im = im.convert("RGBA") if has_alpha(im) else im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue(), im.size


def _add_picture_slide(prs, blob: bytes, size: tuple[int, int], fit: str, bg: str):
    from pptx.dml.color import RGBColor
    from pptx.util import Emu

    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor.from_string(bg.lstrip("#"))
    sw, sh = prs.slide_width, prs.slide_height
    iw, ih = size
    scale = (min if fit == "fit" else max)(sw / iw, sh / ih)
    w, h = int(iw * scale), int(ih * scale)
    pic = slide.shapes.add_picture(io.BytesIO(blob), Emu((sw - w) // 2), Emu((sh - h) // 2), Emu(w), Emu(h))
    if fit == "fill":  # crop the overflow instead of spilling off the slide
        cx = max(0, (w - sw) / w / 2)
        cy = max(0, (h - sh) / h / 2)
        pic.crop_left = pic.crop_right = cx
        pic.crop_top = pic.crop_bottom = cy
        pic.left, pic.top, pic.width, pic.height = 0, 0, sw, sh
    return slide


def _new_deck(aspect: str):
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    w, h = SLIDE_SIZES[aspect]
    prs.slide_width, prs.slide_height = Inches(w), Inches(h)
    return prs


def images_to_pptx(ctx: Ctx) -> None:
    o: ImagesToPptxOptions = ctx.options  # type: ignore[assignment]
    prs = _new_deck(o.aspect)
    n = len(ctx.inputs)
    for k, inp in enumerate(ctx.inputs):
        ctx.progress(k, n, stage=f"Adding image {k + 1} of {n}", force=True)
        blob, size = _png_bytes(ctx, inp)
        _add_picture_slide(prs, blob, size, o.fit, o.background)
    out = ctx.default_out("pptx")
    prs.save(out)
    ctx.add_output(out, "pptx")


register(Operation(
    id="pres.from_images", category="presentations", label="Images to PowerPoint",
    description="Make a PowerPoint deck with one image per slide.", inputs=RASTER_IN, outputs=("pptx",),
    cardinality="many_to_one", options=ImagesToPptxOptions, run=images_to_pptx, engines=("python-pptx", "pillow"),
    format_engines={"heic": ("pillow-heif",), "avif": ("avif",)}, max_inputs=200, slug="images-to-pptx",
    keywords=("photo slideshow", "jpg to pptx"),
))


class PdfToPptxOptions(PdfPasswordOptions):
    dpi: int = Field(150, ge=72, le=300, title="Image resolution", json_schema_extra=ui(unit="dpi"))


def pdf_to_pptx(ctx: Ctx) -> None:
    from pptx.util import Emu

    o: PdfToPptxOptions = ctx.options  # type: ignore[assignment]
    doc = open_pdfium(ctx.input.path, o.password)
    n = len(doc)
    w0, h0 = doc[0].get_size()
    from pptx import Presentation

    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(int(w0 * 12700)), Emu(int(h0 * 12700))  # 1 pt = 12700 EMU
    for i in range(n):
        ctx.progress(i, n, stage=f"Rendering page {i + 1} of {n}", force=True)
        img = doc[i].render(scale=o.dpi / 72).to_pil().convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        slide = _add_picture_slide(prs, buf.getvalue(), img.size, "fit", "#ffffff")
        slide.notes_slide.notes_text_frame.text = f"Image of PDF page {i + 1}. Not editable text."
    out = ctx.default_out("pptx")
    prs.save(out)
    ctx.warn("Image-based slides — not editable. Each PDF page became a picture on its own slide.")
    ctx.add_output(out, "pptx", label="Image-based slides (not editable)")


register(Operation(
    id="pres.from_pdf", category="presentations", label="PDF to PowerPoint",
    description="Put each PDF page on its own slide as an image.", inputs=("pdf",), outputs=("pptx",),
    cardinality="one_to_one", options=PdfToPptxOptions, run=pdf_to_pptx, engines=("pypdfium2", "python-pptx"),
    support="partial", heavy_over_mb=20,
    limitations=("Image-based slides — not editable. Text can't be changed or searched in the result.",),
    keywords=("pdf to ppt", "pdf to slides"),
))
