"""SVG → raster/PDF (resvg, Chromium) and raster → SVG tracing (vtracer, experimental)."""

from __future__ import annotations

import io
from typing import Literal

from PIL import Image
from pydantic import Field

from ...context import ConversionError, Ctx
from ...registry import Operation, Options, register, ui
from ...sanitize import sanitize_svg, svg_size
from .raster import PIL_FORMAT, normalize_mode, open_image


class SvgOptions(Options):
    width: int | None = Field(None, ge=1, le=16000, title="Output width",
                              description="Leave empty to use the SVG's own size (scaled by DPI).",
                              json_schema_extra=ui(unit="px", targets=("png", "jpg", "webp")))
    dpi: int = Field(96, ge=24, le=1200, title="DPI", description="96 renders at the SVG's natural size; 192 doubles it.",
                     json_schema_extra=ui(targets=("png", "jpg", "webp")))
    background: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$", title="Background color",
                                   description="Leave empty to keep transparency (JPG uses white).",
                                   json_schema_extra=ui(widget="color", advanced=True))
    quality: int = Field(90, ge=1, le=100, title="Quality", json_schema_extra=ui(widget="slider", targets=("jpg", "webp")))


MAX_SIDE = 16000


def svg_convert(ctx: Ctx) -> None:
    o: SvgOptions = ctx.options  # type: ignore[assignment]
    ctx.stage("Sanitizing")
    markup, removed = sanitize_svg(ctx.input.path.read_bytes())
    if removed:
        ctx.notice(f"Removed {removed} external reference{'s' if removed != 1 else ''} (links to other files or URLs aren't loaded).")
    size = svg_size(markup)
    if ctx.target == "pdf":
        from ...chromium import html_to_pdf

        ctx.stage("Rendering PDF")
        w, h = size or (800, 600)
        bg = f"background:{o.background};" if o.background else ""
        html = (f"<!doctype html><html><head><meta charset='utf-8'><style>@page{{size:{w}px {h}px;margin:0}}"
                f"html,body{{margin:0;padding:0;{bg}}}svg{{display:block;width:{w}px;height:{h}px}}</style></head>"
                f"<body>{markup}</body></html>")
        out = ctx.default_out("pdf")
        html_to_pdf(html, out, width=f"{w}px", height=f"{h}px", margin_mm=0, timeout_s=ctx.timeout_s / 2)
        ctx.notice("Vector shapes and text stay sharp at any zoom.")
        ctx.add_output(out, "pdf")
        return

    import resvg_py

    ctx.stage("Rendering")
    scale = o.dpi / 96
    kw: dict = {"svg_string": markup}
    if o.width:
        kw["width"] = o.width
    elif size and scale != 1:
        kw["width"] = max(1, round(size[0] * scale))
    if size:
        target_w = kw.get("width", size[0])
        if target_w > MAX_SIDE or target_w * size[1] / size[0] > MAX_SIDE:
            raise ConversionError("too_many_pixels", f"That output size is too large (max {MAX_SIDE}px per side).")
    bg = o.background or ("#ffffff" if ctx.target == "jpg" else None)
    if bg:
        kw["background"] = bg
    try:
        png = bytes(resvg_py.svg_to_bytes(**kw))
    except ValueError as e:
        raise ConversionError("corrupt_input", "This SVG couldn't be rendered. It may be empty or invalid.") from e
    im = Image.open(io.BytesIO(png))
    im.load()
    out = ctx.default_out()
    im = normalize_mode(im, ctx.target, bg or "#ffffff")
    kw2 = {"quality": o.quality} if ctx.target in ("jpg", "webp") else {}
    im.save(out, PIL_FORMAT[ctx.target], **kw2)
    ctx.info.update(width=im.width, height=im.height)
    ctx.add_output(out)


register(Operation(
    id="image.svg_render", category="images", label="Render SVG",
    description="Render SVG vector graphics to PNG, JPG or WebP at any size, or to a vector PDF. External files and URLs are never loaded.",
    inputs=("svg",), outputs=("png", "jpg", "webp", "pdf"), cardinality="one_to_one", options=SvgOptions,
    run=svg_convert, engines=("resvg", "pillow"), format_engines={"pdf": ("chromium",)}, memory_mb=None,
    pair_limitations={("svg", "pdf"): ("Rendered by a browser engine; SVG filters and fonts may differ slightly.",)},
    keywords=("vector", "rasterize"),
))


# ---------------------------------------------------------------------------


class TraceOptions(Options):
    colormode: Literal["color", "binary"] = Field("color", title="Colors", description="binary traces black-and-white line art.")
    detail: Literal["low", "medium", "high"] = Field("medium", title="Detail",
                                                     description="Higher detail keeps small shapes but makes larger files.")


def trace(ctx: Ctx) -> None:
    import vtracer

    o: TraceOptions = ctx.options  # type: ignore[assignment]
    src = open_image(ctx, ctx.input.path)
    if src.width * src.height > 16_000_000:
        raise ConversionError("too_many_pixels", "Tracing works on images up to 16 megapixels. Resize it first.")
    im = src.convert("RGBA")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    speckle, precision = {"low": (16, 4), "medium": (4, 6), "high": (2, 8)}[o.detail]
    ctx.stage("Tracing shapes")
    svg = vtracer.convert_raw_image_to_svg(buf.getvalue(), img_format="png", colormode=o.colormode, hierarchical="stacked",
                                           mode="spline", filter_speckle=speckle, color_precision=precision)
    out = ctx.default_out("svg")
    out.write_text(svg)
    ctx.notice("This is a traced vector approximation of your image, not the original artwork.")
    ctx.add_output(out, "svg")


register(Operation(
    id="image.trace", category="images", label="Trace to vector",
    description="Trace a raster image into SVG paths (vector tracing). Works best on logos and flat graphics.",
    inputs=("png", "jpg", "webp", "gif", "bmp", "tiff"), outputs=("svg",), cardinality="one_to_one", options=TraceOptions,
    run=trace, engines=("vtracer", "pillow"), support="experimental",
    limitations=("Tracing approximates shapes; photos produce large, stylized SVGs.",),
    keywords=("vectorize", "svg"),
))
