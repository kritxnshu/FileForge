"""Putting things on pages: edit (text, images, shapes, drawing), sign, redact, and forms (export, fill, create).

Positions come from the page editor in normalised display coordinates (see pdfgeom.PageFrame), so what's drawn
lands where the user put it, even on rotated or cropped pages.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import math
import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from ...context import ConversionError, Ctx
from ...registry import Operation, register, ui
from .pdfcommon import PdfPasswordOptions, open_pdfium, open_pike, open_reader
from .pdfgeom import check_page, font_for, frame_pdfium, frame_pypdf, hex_color, stamp

NORM = dict(ge=-0.05, le=1.05)
SIZE = dict(gt=0, le=1.1)
HEX = dict(pattern=r"^#[0-9a-fA-F]{6}$")
MAX_IMAGE_DATA = 4_000_000  # characters of base64 per image (~3 MB)
MAX_IMAGE_PIXELS = 25_000_000


# ---------------------------------------------------------------------------
# page objects (shared by Edit and Sign)


class TextObj(BaseModel):
    type: Literal["text"]
    page: int = Field(..., ge=1)
    x: float = Field(..., **NORM)
    y: float = Field(..., **NORM)
    text: str = Field(..., min_length=1, max_length=5000)
    font: Literal["helvetica", "helvetica-bold", "helvetica-italic", "times", "times-bold", "times-italic", "courier",
                  "courier-bold"] = "helvetica"
    size: float = Field(14, ge=4, le=300)
    color: str = Field("#111111", **HEX)
    opacity: float = Field(1, ge=0.05, le=1)


class ImageObj(BaseModel):
    type: Literal["image"]
    page: int = Field(..., ge=1)
    x: float = Field(..., **NORM)
    y: float = Field(..., **NORM)
    w: float = Field(..., **SIZE)
    h: float = Field(..., **SIZE)
    data: str = Field(..., max_length=MAX_IMAGE_DATA, description="data:image/png or image/jpeg URL")
    opacity: float = Field(1, ge=0.05, le=1)


class BoxObj(BaseModel):
    type: Literal["rect", "ellipse", "highlight", "whiteout"]
    page: int = Field(..., ge=1)
    x: float = Field(..., **NORM)
    y: float = Field(..., **NORM)
    w: float = Field(..., **SIZE)
    h: float = Field(..., **SIZE)
    stroke: str | None = Field("#d92d20", **HEX)
    fill: str | None = Field(None, **HEX)
    width: float = Field(2, ge=0, le=40)
    opacity: float = Field(1, ge=0.05, le=1)


class LineObj(BaseModel):
    type: Literal["line", "arrow"]
    page: int = Field(..., ge=1)
    x1: float = Field(..., **NORM)
    y1: float = Field(..., **NORM)
    x2: float = Field(..., **NORM)
    y2: float = Field(..., **NORM)
    color: str = Field("#d92d20", **HEX)
    width: float = Field(2, gt=0, le=40)
    opacity: float = Field(1, ge=0.05, le=1)


class PathObj(BaseModel):
    type: Literal["path"]
    page: int = Field(..., ge=1)
    points: list[tuple[float, float]] = Field(..., min_length=2, max_length=10000)
    color: str = Field("#1d4ed8", **HEX)
    width: float = Field(2.5, gt=0, le=40)
    opacity: float = Field(1, ge=0.05, le=1)


PageObj = Annotated[Union[TextObj, ImageObj, BoxObj, LineObj, PathObj], Field(discriminator="type")]


def _decode_image(data: str):
    from PIL import Image, ImageOps

    m = re.match(r"^data:image/(png|jpeg|jpg|webp);base64,(.+)$", data, re.S)
    if not m:
        raise ConversionError("invalid_option", "Images must be PNG, JPEG or WebP.")
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except (binascii.Error, ValueError) as e:
        raise ConversionError("invalid_option", "One of the images is damaged. Add it again.") from e
    try:
        im = Image.open(io.BytesIO(raw))
        if im.width * im.height > MAX_IMAGE_PIXELS:
            raise ConversionError("too_many_pixels", "One of the images is too large. Use one under 25 megapixels.")
        im.load()
    except ConversionError:
        raise
    except Exception as e:
        raise ConversionError("invalid_option", "One of the images couldn't be read. Add it again.") from e
    im = ImageOps.exif_transpose(im) or im
    return im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")


def _draw_object(c, f, obj) -> None:
    """Draw one object on a reportlab canvas set up in display points (y up) by pdfgeom.stamp."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import getAscentDescent

    W, H = f.width, f.height
    c.saveState()
    if isinstance(obj, TextObj):
        font = font_for(obj.text, obj.font)
        c.setFont(font, obj.size)
        c.setFillColor(hex_color(obj.color, obj.opacity))
        ascent, _ = getAscentDescent(font, obj.size)
        y = (1 - obj.y) * H - ascent
        for line in obj.text.split("\n"):
            c.drawString(obj.x * W, y, line)
            y -= obj.size * 1.2
    elif isinstance(obj, ImageObj):
        im = _decode_image(obj.data)
        c.setFillAlpha(obj.opacity)
        x, w, h = obj.x * W, obj.w * W, obj.h * H
        c.drawImage(ImageReader(im), x, (1 - obj.y) * H - h, w, h, mask="auto")
    elif isinstance(obj, BoxObj):
        x, w, h = obj.x * W, obj.w * W, obj.h * H
        y = (1 - obj.y) * H - h
        stroke, fill = obj.stroke, obj.fill
        alpha = obj.opacity
        if obj.type == "highlight":
            stroke, fill, alpha = None, obj.fill or "#ffd400", min(obj.opacity, 0.45)
        elif obj.type == "whiteout":
            stroke, fill, alpha = None, obj.fill or "#ffffff", 1
        if stroke and obj.width:
            c.setStrokeColor(hex_color(stroke, alpha))
            c.setLineWidth(obj.width)
        if fill:
            c.setFillColor(hex_color(fill, alpha))
        draw_stroke = 1 if (stroke and obj.width) else 0
        if obj.type == "ellipse":
            c.ellipse(x, y, x + w, y + h, stroke=draw_stroke, fill=1 if fill else 0)
        else:
            c.rect(x, y, w, h, stroke=draw_stroke, fill=1 if fill else 0)
    elif isinstance(obj, LineObj):
        c.setStrokeColor(hex_color(obj.color, obj.opacity))
        c.setFillColor(hex_color(obj.color, obj.opacity))
        c.setLineWidth(obj.width)
        c.setLineCap(1)
        x1, y1, x2, y2 = obj.x1 * W, (1 - obj.y1) * H, obj.x2 * W, (1 - obj.y2) * H
        c.line(x1, y1, x2, y2)
        if obj.type == "arrow":
            ang = math.atan2(y2 - y1, x2 - x1)
            size = max(8, obj.width * 4)
            p = c.beginPath()
            p.moveTo(x2, y2)
            p.lineTo(x2 - size * math.cos(ang - 0.45), y2 - size * math.sin(ang - 0.45))
            p.lineTo(x2 - size * math.cos(ang + 0.45), y2 - size * math.sin(ang + 0.45))
            p.close()
            c.drawPath(p, stroke=0, fill=1)
    elif isinstance(obj, PathObj):
        c.setStrokeColor(hex_color(obj.color, obj.opacity))
        c.setLineWidth(obj.width)
        c.setLineCap(1)
        c.setLineJoin(1)
        p = c.beginPath()
        (u0, v0), *rest = obj.points
        p.moveTo(u0 * W, (1 - v0) * H)
        for u, v in rest:
            p.lineTo(u * W, (1 - v) * H)
        c.drawPath(p, stroke=1, fill=0)
    c.restoreState()


def _apply_objects(ctx: Ctx, password: str | None, objects: list) -> None:
    from pypdf import PdfWriter

    r = open_reader(ctx.input.path, password)
    n = len(r.pages)
    by_page: dict[int, list] = {}
    for obj in objects:
        by_page.setdefault(check_page(obj.page, n), []).append(obj)
    w = PdfWriter()
    for i, page in enumerate(r.pages):
        if i in by_page:
            ctx.progress(i, n, stage=f"Drawing on page {i + 1} of {n}")
            stamp(page, lambda c, f, objs=by_page[i]: [_draw_object(c, f, o) for o in objs])
        w.add_page(page)
    out = ctx.default_out("pdf")
    with out.open("wb") as fh:
        w.write(fh)
    ctx.info.update(objects=len(objects), pages_changed=len(by_page))
    ctx.add_output(out, "pdf")


class EditOptions(PdfPasswordOptions):
    objects: list[PageObj] = Field(default_factory=list, max_length=2000, title="Your changes",
                                   json_schema_extra=ui(widget="pdf-editor", mode="edit"))


def edit(ctx: Ctx) -> None:
    o: EditOptions = ctx.options  # type: ignore[assignment]
    if not o.objects:
        raise ConversionError("invalid_option", "Add some text, an image or a shape to a page first.")
    _apply_objects(ctx, o.password, o.objects)


register(Operation(
    id="pdf.edit", category="documents", label="Edit PDF",
    description="Add text, images, shapes, arrows, highlights and freehand drawing to PDF pages, or cover things up "
                "with white-out.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=EditOptions, run=edit,
    engines=("pypdf", "reportlab", "pillow"), slug="edit-pdf", keywords=("annotate", "add text", "draw", "highlight",
                                                                        "white out", "insert image"),
    limitations=("Adds new content on top of the page. Existing text can be covered with white-out and retyped, but "
                 "not edited in place. White-out hides content visually only: use Redact to remove it.",),
))


class SignOptions(PdfPasswordOptions):
    objects: list[PageObj] = Field(default_factory=list, max_length=200, title="Signature placement",
                                   json_schema_extra=ui(widget="pdf-editor", mode="sign"))


def sign(ctx: Ctx) -> None:
    o: SignOptions = ctx.options  # type: ignore[assignment]
    if not any(isinstance(obj, (ImageObj, PathObj)) for obj in o.objects):
        raise ConversionError("invalid_option", "Create your signature and place it on a page first.")
    _apply_objects(ctx, o.password, o.objects)
    ctx.notice("This is a visual signature: it shows your signature on the page, but it isn't a cryptographic "
               "digital signature.")


register(Operation(
    id="pdf.sign", category="documents", label="Sign PDF",
    description="Draw, type or upload your signature and place it on the page, with the date or your initials.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=SignOptions, run=sign,
    engines=("pypdf", "reportlab", "pillow"), slug="sign-pdf", keywords=("signature", "e-sign", "initials"),
    limitations=("A visual signature, not a cryptographic (certificate-based) digital signature.",),
))


# ---------------------------------------------------------------------------
# redact


class RedactArea(BaseModel):
    page: int = Field(..., ge=1)
    x: float = Field(..., **NORM)
    y: float = Field(..., **NORM)
    w: float = Field(..., **SIZE)
    h: float = Field(..., **SIZE)


class RedactOptions(PdfPasswordOptions):
    areas: list[RedactArea] = Field(default_factory=list, max_length=5000, title="Areas to black out",
                                    json_schema_extra=ui(widget="pdf-editor", mode="redact"))
    search: str | None = Field(None, max_length=5000, title="Words to redact",
                               description="One word or phrase per line. Every occurrence is blacked out.",
                               json_schema_extra=ui(widget="textarea", placeholder="Jane Doe\nAccount 12345"))
    match_case: bool = Field(False, title="Match case")
    dpi: int = Field(200, ge=100, le=300, title="Resolution of redacted pages", json_schema_extra=ui(unit="dpi", advanced=True))


def _search_boxes(page, terms: list[str], match_case: bool) -> tuple[list[tuple[float, float, float, float]], set[str]]:
    """User-space boxes of every occurrence of each term on a PDFium page, and which terms were found."""
    tp = page.get_textpage()
    boxes, found = [], set()
    for term in terms:
        searcher = tp.search(term, match_case=match_case, match_whole_word=False)
        while (hit := searcher.get_next()) is not None:
            start, count = hit
            found.add(term)
            chars = [tp.get_charbox(i) for i in range(start, start + count)]
            # one box per line of the hit
            lines: dict[int, list] = {}
            for (l, b, r, t) in chars:
                lines.setdefault(round(b / 3), []).append((l, b, r, t))
            for cs in lines.values():
                boxes.append((min(c[0] for c in cs) - 1, min(c[1] for c in cs) - 1,
                              max(c[2] for c in cs) + 1, max(c[3] for c in cs) + 1))
    return boxes, found


def redact(ctx: Ctx) -> None:
    import img2pdf
    from PIL import ImageDraw
    from pypdf import PdfReader, PdfWriter

    from ...safety import max_image_pixels

    o: RedactOptions = ctx.options  # type: ignore[assignment]
    terms = [t.strip() for t in (o.search or "").splitlines() if t.strip()]
    if not o.areas and not terms:
        raise ConversionError("invalid_option", "Mark the areas to black out, or enter words to redact.")
    doc = open_pdfium(ctx.input.path, o.password)
    n = len(doc)
    marks: dict[int, list[tuple[float, float, float, float]]] = {}
    for a in o.areas:
        marks.setdefault(check_page(a.page, n), []).append((a.x, a.y, a.w, a.h))
    found: set[str] = set()
    if terms:
        for i in range(n):
            ctx.progress(i, n, stage=f"Searching page {i + 1} of {n}")
            page = doc[i]
            f = frame_pdfium(page)
            boxes, hit = _search_boxes(page, terms, o.match_case)
            found |= hit
            for (l, b, r, t) in boxes:
                u0, v0 = f.to_display(l, t)
                u1, v1 = f.to_display(r, b)
                marks.setdefault(i, []).append((min(u0, u1), min(v0, v1), abs(u1 - u0), abs(v1 - v0)))
    missing = [t for t in terms if t not in found]
    if not marks:
        raise ConversionError("not_found", "None of those words appear in this PDF's text, and no areas were marked. "
                                           "If it's a scanned document, run OCR first.")
    # Rasterise each affected page with the boxes burnt in: nothing under a box survives in the file.
    scale = o.dpi / 72
    replaced: dict[int, bytes] = {}
    for k, (i, boxes) in enumerate(sorted(marks.items())):
        ctx.progress(k, len(marks), stage=f"Redacting page {i + 1}", force=True)
        page = doc[i]
        f = frame_pdfium(page)
        if f.width * scale * f.height * scale > max_image_pixels():
            raise ConversionError("too_many_pixels", f"Page {i + 1} is too large to redact at {o.dpi} dpi. Choose a lower resolution.")
        img = page.render(scale=scale).to_pil().convert("RGB")
        d = ImageDraw.Draw(img)
        for (u, v, w, h) in boxes:
            d.rectangle([u * img.width, v * img.height, (u + w) * img.width, (v + h) * img.height], fill=(0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        layout = img2pdf.get_layout_fun((f.width, f.height), None, None, img2pdf.FitMode.into, False)
        replaced[i] = img2pdf.convert(buf.getvalue(), layout_fun=layout)
    src = open_reader(ctx.input.path, o.password)
    w = PdfWriter()
    for i, page in enumerate(src.pages):
        if i in replaced:
            w.add_page(PdfReader(io.BytesIO(replaced[i])).pages[0])
        else:
            w.add_page(page)
    out = ctx.default_out("pdf")
    with out.open("wb") as fh:
        w.write(fh)  # document properties, bookmarks and attachments aren't copied
    total = sum(len(b) for b in marks.values())
    ctx.info.update(redactions=total, pages_redacted=len(marks), terms_found=sorted(found))
    ctx.notice(f"Blacked out {total} area{'s' if total != 1 else ''} on {len(marks)} page{'s' if len(marks) != 1 else ''}. "
               "Redacted pages are now images, so their text can't be selected or searched. Document properties "
               "and bookmarks were removed.")
    if missing:
        ctx.warn("Not found, so nothing was redacted for: " + ", ".join(f"“{t}”" for t in missing[:10]) + ".")
    ctx.add_output(out, "pdf")


register(Operation(
    id="pdf.redact", category="documents", label="Redact PDF",
    description="Permanently black out names, numbers or areas. The content under each box is removed from the "
                "file, not just hidden.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=RedactOptions, run=redact,
    engines=("pypdfium2", "pypdf", "img2pdf", "pillow"), slug="redact-pdf",
    keywords=("black out", "censor", "remove sensitive", "anonymize"),
    limitations=("Pages with redactions are converted to images, so their remaining text can't be selected.",
                 "Word search only finds real text: scanned pages need OCR first, or mark the areas by hand."),
))


# ---------------------------------------------------------------------------
# forms


def _field_kind(field) -> str:
    import pikepdf.form as pf

    if isinstance(field, pf.TextField):
        return "text"
    if isinstance(field, pf.CheckboxField):
        return "checkbox"
    if isinstance(field, pf.RadioButtonGroup):
        return "radio"
    if isinstance(field, pf.ChoiceField):
        return "choice"
    if isinstance(field, getattr(pf, "SignatureField", ())):
        return "signature"
    return "button"


def _form_fields(ctx: Ctx, password: str | None) -> list[dict]:
    import pikepdf.form as pf

    pdf = open_pike(ctx.input.path, password)
    if "/AcroForm" not in pdf.Root or not pdf.Root.AcroForm.get("/Fields"):
        return []
    frames = [frame_pypdf(p) for p in open_reader(ctx.input.path, password).pages]
    page_of = {}
    for pi, page in enumerate(pdf.pages):
        for a in page.obj.get("/Annots", []):
            page_of[a.objgen] = pi
    acro = getattr(pdf, "acroform", None) or pf.AcroForm(pdf)
    widgets: dict[str, list[dict]] = {}
    for fld in acro.fields:
        for ann in acro.get_annotations_for_field(fld):
            obj = ann.obj
            pi = page_of.get(obj.objgen)
            if pi is None or "/Rect" not in obj:
                continue
            x0, y0, x1, y1 = (float(v) for v in obj.Rect)
            f = frames[pi]
            u0, v0 = f.to_display(min(x0, x1), max(y0, y1))
            u1, v1 = f.to_display(max(x0, x1), min(y0, y1))
            widgets.setdefault(fld.fully_qualified_name, []).append(
                {"page": pi + 1, "x": round(min(u0, u1), 5), "y": round(min(v0, v1), 5),
                 "w": round(abs(u1 - u0), 5), "h": round(abs(v1 - v0), 5)})
    out = []
    for name, field in pf.Form(pdf).items():
        kind = _field_kind(field)
        entry: dict = {"name": name, "type": kind, "required": bool(getattr(field, "is_required", False)),
                       "read_only": bool(getattr(field, "is_read_only", False)), "widgets": widgets.get(name, [])}
        if kind == "text":
            entry.update(value=str(field.value or ""), multiline=bool(field.is_multiline), max_length=field.max_length)
        elif kind == "checkbox":
            entry.update(value=bool(field.checked))
        elif kind == "radio":
            opts = [str(o.on_value).lstrip("/") for o in field.options]
            entry.update(options=opts, value=str(field.value).lstrip("/") if field.value else "")
        elif kind == "choice":
            entry.update(options=[str(o.display_value or o.export_value) for o in field.options],
                         value=str(field.value or ""), multiselect=bool(field.is_multiselect))
        out.append(entry)
    return out


class FormDataOptions(PdfPasswordOptions):
    pass


def form_data(ctx: Ctx) -> None:
    o: FormDataOptions = ctx.options  # type: ignore[assignment]
    fields = _form_fields(ctx, o.password)
    if not fields:
        raise ConversionError("no_form", "This PDF has no fillable form fields. To add some, use Create a form.")
    out = ctx.default_out("json")
    out.write_text(json.dumps({"fields": fields}, indent=2, ensure_ascii=False), encoding="utf-8")
    ctx.info.update(fields=len(fields))
    ctx.add_output(out, "json")


register(Operation(
    id="pdf.form_data", category="documents", label="Export form data",
    description="List a PDF form's fields with their types, options and current values, as JSON.",
    inputs=("pdf",), outputs=("json",), cardinality="one_to_one", options=FormDataOptions, run=form_data,
    engines=("pikepdf", "pypdf"), slug="pdf-form-data", keywords=("form fields", "acroform", "export"),
))


FieldValue = Union[bool, str, list[str]]


class FillFormOptions(PdfPasswordOptions):
    values: dict[str, FieldValue] = Field(default_factory=dict, title="Field values",
                                          json_schema_extra=ui(widget="pdf-form-fill"))
    flatten: bool = Field(False, title="Flatten after filling",
                          description="Make the answers part of the page so they can't be changed.")


def fill_form(ctx: Ctx) -> None:
    import pikepdf.form as pf

    o: FillFormOptions = ctx.options  # type: ignore[assignment]
    if sum(len(v) if isinstance(v, (str, list)) else 1 for v in o.values.values()) > 2_000_000:
        raise ConversionError("invalid_option", "Those answers are too long.")
    pdf = open_pike(ctx.input.path, o.password)
    if "/AcroForm" not in pdf.Root or not pdf.Root.AcroForm.get("/Fields"):
        raise ConversionError("no_form", "This PDF has no fillable form fields. To add some, use Create a form.")
    form = dict(pf.Form(pdf, pf.DefaultAppearanceStreamGenerator).items())
    unknown, filled = [], 0
    for name, value in o.values.items():
        field = form.get(name)
        if field is None:
            unknown.append(name)
            continue
        kind = _field_kind(field)
        if getattr(field, "is_read_only", False):
            continue
        if kind == "text":
            field.value = value if isinstance(value, str) else ("Yes" if value is True else "")
        elif kind == "checkbox":
            field.checked = value is True or (isinstance(value, str) and value.lower() in ("true", "yes", "on", "1"))
        elif kind == "radio":
            choice = str(value).lstrip("/")
            match = next((op for op in field.options if str(op.on_value).lstrip("/") == choice), None)
            if match is None:
                raise ConversionError("invalid_option", f"“{choice}” isn't one of the choices for “{name}”.")
            match.select()
        elif kind == "choice":
            wanted = value if isinstance(value, list) else [str(value)]
            opts = {str(op.display_value or op.export_value): op for op in field.options}
            opts.update({str(op.export_value): op for op in field.options})
            bad = [v for v in wanted if v and v not in opts]
            if bad and not getattr(field, "allow_edit", False):
                raise ConversionError("invalid_option", f"“{bad[0]}” isn't one of the choices for “{name}”.")
            field.value = wanted[0] if wanted else ""
        else:
            continue
        filled += 1
    if unknown:
        ctx.warn("These fields don't exist in this PDF and were skipped: " + ", ".join(unknown[:10]) + ".")
    if o.flatten:
        ctx.stage("Flattening")
        pdf.generate_appearance_streams()
        pdf.flatten_annotations(mode="all")
        if "/AcroForm" in pdf.Root:
            del pdf.Root.AcroForm
        ctx.notice("The form was flattened: answers are part of the page and can't be changed.")
    out = ctx.default_out("pdf")
    pdf.save(out)
    ctx.info.update(filled=filled)
    ctx.add_output(out, "pdf")


register(Operation(
    id="pdf.fill_form", category="documents", label="Fill PDF form",
    description="Fill in a PDF form's text boxes, checkboxes, choices and radio buttons, and optionally flatten it.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=FillFormOptions, run=fill_form,
    engines=("pikepdf", "pypdf"), slug="fill-pdf-form", keywords=("form", "fill in", "fillable", "acroform"),
))


class NewField(BaseModel):
    type: Literal["text", "checkbox", "dropdown"]
    page: int = Field(..., ge=1)
    x: float = Field(..., **NORM)
    y: float = Field(..., **NORM)
    w: float = Field(..., **SIZE)
    h: float = Field(..., **SIZE)
    name: str = Field(..., pattern=r"^[A-Za-z0-9_\-. ]{1,64}$")
    options: list[str] = Field(default_factory=list, max_length=200)
    multiline: bool = False
    required: bool = False


class AddFieldsOptions(PdfPasswordOptions):
    fields: list[NewField] = Field(default_factory=list, max_length=1000, title="Form fields",
                                   json_schema_extra=ui(widget="pdf-editor", mode="form"))


def _checkbox_appearance(pdf, w: float, h: float, checked: bool):
    import pikepdf

    s = min(w, h)
    ops = [f"q 0.5 G 0.8 w 0.4 0.4 {w - 0.8:.2f} {h - 0.8:.2f} re S Q"]
    if checked:
        ops.append(f"q 0 G {max(1.2, s * 0.12):.2f} w 1 J 1 j {w * 0.22:.2f} {h * 0.52:.2f} m {w * 0.42:.2f} {h * 0.28:.2f} l "
                   f"{w * 0.8:.2f} {h * 0.78:.2f} l S Q")
    return pikepdf.Stream(pdf, " ".join(ops).encode(), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Form,
                          BBox=[0, 0, w, h])


def add_fields(ctx: Ctx) -> None:
    from pikepdf import Array, Dictionary, Name, String

    o: AddFieldsOptions = ctx.options  # type: ignore[assignment]
    if not o.fields:
        raise ConversionError("invalid_option", "Draw at least one field on a page.")
    pdf = open_pike(ctx.input.path, o.password)
    frames = [frame_pypdf(p) for p in open_reader(ctx.input.path, o.password).pages]
    n = len(pdf.pages)
    if "/AcroForm" not in pdf.Root:
        pdf.Root.AcroForm = pdf.make_indirect(Dictionary(Fields=Array()))
    acro = pdf.Root.AcroForm
    if "/Fields" not in acro:
        acro.Fields = Array()
    fonts = Dictionary(Helv=pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica,
                                                         Encoding=Name.WinAnsiEncoding)))
    acro.DR = Dictionary(Font=fonts)
    acro.DA = String("/Helv 0 Tf 0 g")
    acro.NeedAppearances = True
    existing = {str(f.get("/T", "")) for f in acro.Fields}
    for spec in o.fields:
        name = spec.name.strip()
        if name in existing:
            raise ConversionError("invalid_option", f"Two fields are called “{name}”. Give each field its own name.")
        existing.add(name)
        pi = check_page(spec.page, n)
        f = frames[pi]
        x0, y0, x1, y1 = f.rect_to_user(spec.x, spec.y, spec.w, spec.h)
        size = max(6.0, min(14.0, (spec.h * f.height) * 0.6))
        widget = Dictionary(Type=Name.Annot, Subtype=Name.Widget, T=String(name), Rect=Array([x0, y0, x1, y1]), F=4,
                            P=pdf.pages[pi].obj, MK=Dictionary(BC=Array([0.55, 0.55, 0.55]), BG=Array([1, 1, 1]),
                                                               R=f.rotation))
        flags = 2 if spec.required else 0
        if spec.type == "text":
            widget.FT = Name.Tx
            widget.V = String("")
            widget.DA = String(f"/Helv {0 if spec.multiline else round(size, 1)} Tf 0 g")
            flags |= (1 << 12) if spec.multiline else 0
        elif spec.type == "checkbox":
            rw, rh = abs(x1 - x0), abs(y1 - y0)
            if f.rotation in (90, 270):
                rw, rh = rh, rw
            widget.FT = Name.Btn
            widget.V = Name.Off
            widget.AS = Name.Off
            widget.AP = Dictionary(N=Dictionary(Yes=_checkbox_appearance(pdf, rw, rh, True),
                                                Off=_checkbox_appearance(pdf, rw, rh, False)))
        else:
            opts = [s.strip() for s in spec.options if s.strip()]
            if not opts:
                raise ConversionError("invalid_option", f"Add at least one choice to the dropdown “{name}”.")
            widget.FT = Name.Ch
            widget.Opt = Array([String(s) for s in opts])
            widget.V = String(opts[0])
            widget.DA = String(f"/Helv {round(size, 1)} Tf 0 g")
            flags |= 1 << 17  # combo box
        if flags:
            widget.Ff = flags
        ref = pdf.make_indirect(widget)
        page = pdf.pages[pi].obj
        if "/Annots" not in page:
            page.Annots = Array()
        page.Annots.append(ref)
        acro.Fields.append(ref)
    pdf.generate_appearance_streams()
    out = ctx.default_out("pdf")
    pdf.save(out)
    ctx.info.update(fields=len(o.fields))
    ctx.add_output(out, "pdf")


register(Operation(
    id="pdf.add_fields", category="documents", label="Create a form",
    description="Turn any PDF into a fillable form: draw text boxes, checkboxes and dropdowns where people should "
                "answer.",
    inputs=("pdf",), outputs=(), cardinality="transform", options=AddFieldsOptions, run=add_fields,
    engines=("pikepdf", "pypdf"), slug="create-pdf-form", keywords=("fillable", "form fields", "acroform", "text box"),
))
