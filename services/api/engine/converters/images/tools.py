"""Same-format image tools: resize, compress, metadata/DPI. Plus raster → HEIC (experimental)."""

from __future__ import annotations

import shutil
from typing import Literal

from PIL import Image, ImageOps
from pydantic import Field, model_validator

from ...context import ConversionError, Ctx
from ...registry import Operation, Options, register, ui
from .raster import PIL_FORMAT, has_alpha, normalize_mode, open_image

EDITABLE = ("png", "jpg", "webp", "gif", "bmp", "tiff", "avif")
LOSSY = ("jpg", "webp", "avif")


def _save(im: Image.Image, out, fmt: str, *, quality: int = 90, exif: bytes | None = None, icc: bytes | None = None,
          dpi: tuple[float, float] | None = None, png_optimize: bool = True, lossless: bool = False) -> None:
    kw: dict = {}
    if fmt == "jpg":
        kw.update(quality=quality, optimize=True, progressive=True)
    elif fmt == "webp":
        kw.update(quality=quality, method=6, lossless=lossless)
    elif fmt == "avif":
        kw.update(quality=quality, speed=6)
    elif fmt == "png":
        kw.update(optimize=png_optimize, compress_level=9)
    elif fmt == "tiff":
        kw.update(compression="tiff_lzw")
    if exif and fmt in ("jpg", "webp", "png", "tiff", "avif"):
        kw["exif"] = exif
    if icc and fmt in ("jpg", "webp", "png", "tiff", "avif"):
        kw["icc_profile"] = icc
    if dpi and fmt in ("jpg", "png", "tiff", "bmp"):
        kw["dpi"] = dpi
    im.save(out, PIL_FORMAT[fmt], **kw)


def _frames(src: Image.Image):
    n = getattr(src, "n_frames", 1)
    for i in range(n):
        src.seek(i)
        yield i, n, src.copy(), src.info.get("duration", 100)


def _save_animated(frames: list[Image.Image], durations: list[int], out, fmt: str, loop: int) -> None:
    if fmt == "gif":
        frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=durations, loop=loop, disposal=2)
    else:
        frames[0].save(out, "WEBP", save_all=True, append_images=frames[1:], duration=durations, loop=loop, quality=90)


# ---------------------------------------------------------------------------
# resize


class ResizeOptions(Options):
    mode: Literal["percent", "width", "height", "exact", "fit"] = Field(
        "percent", title="Resize by",
        description="percent: scale both sides; width/height: set one side and keep proportions; "
                    "fit: fit inside a box; exact: set both sides (may stretch).")
    percent: float = Field(50, gt=0, le=1000, title="Scale (%)", json_schema_extra=ui(unit="%"))
    width: int | None = Field(None, ge=1, le=20000, title="Width", json_schema_extra=ui(unit="px"))
    height: int | None = Field(None, ge=1, le=20000, title="Height", json_schema_extra=ui(unit="px"))
    quality: int = Field(90, ge=1, le=100, title="Quality", json_schema_extra=ui(widget="slider", targets=LOSSY))

    @model_validator(mode="after")
    def _need_dims(self):
        if self.mode in ("width", "exact", "fit") and not self.width:
            raise ValueError("width is required for this resize mode")
        if self.mode in ("height", "exact", "fit") and not self.height:
            raise ValueError("height is required for this resize mode")
        return self


def _target_size(w: int, h: int, o: ResizeOptions) -> tuple[int, int]:
    if o.mode == "percent":
        return max(1, round(w * o.percent / 100)), max(1, round(h * o.percent / 100))
    if o.mode == "width":
        return o.width, max(1, round(h * o.width / w))  # type: ignore[operator]
    if o.mode == "height":
        return max(1, round(w * o.height / h)), o.height  # type: ignore[operator]
    if o.mode == "exact":
        return o.width, o.height  # type: ignore[return-value]
    scale = min(o.width / w, o.height / h)  # type: ignore[operator]
    return max(1, round(w * scale)), max(1, round(h * scale))


def resize(ctx: Ctx) -> None:
    o: ResizeOptions = ctx.options  # type: ignore[assignment]
    fmt = ctx.input.format
    ctx.stage("Decoding")
    src = open_image(ctx, ctx.input.path)
    base = ImageOps.exif_transpose(src.copy()) or src
    w, h = base.size
    nw, nh = _target_size(w, h, o)
    from ...safety import max_image_pixels

    if nw * nh > max_image_pixels():
        raise ConversionError("too_many_pixels", f"{nw}×{nh} is more pixels than we allow. Choose a smaller size.")
    out = ctx.default_out(fmt)
    n = getattr(src, "n_frames", 1)
    if n > 1 and fmt in ("gif", "webp"):
        frames, durs = [], []
        for i, total, fr, d in _frames(src):
            frames.append(fr.convert("RGBA").resize((nw, nh), Image.Resampling.LANCZOS))
            durs.append(d)
            ctx.progress(i + 1, total, stage=f"Frame {i + 1} of {total}")
        _save_animated(frames, durs, out, fmt, src.info.get("loop", 0))
    else:
        ctx.stage("Resizing")
        im = normalize_mode(base, fmt, "#ffffff").resize((nw, nh), Image.Resampling.LANCZOS)
        _save(im, out, fmt, quality=o.quality, exif=None, icc=src.info.get("icc_profile"), dpi=src.info.get("dpi"))
    ctx.info.update(width=nw, height=nh, original_width=w, original_height=h)
    ctx.notice(f"Resized from {w}×{h} to {nw}×{nh} pixels.")
    ctx.add_output(out, fmt)


register(Operation(
    id="image.resize", category="images", label="Resize image",
    description="Change an image's pixel dimensions by percentage, width, height or a bounding box.",
    inputs=EDITABLE, outputs=(), cardinality="transform", options=ResizeOptions, run=resize,
    engines=("pillow",), format_engines={"avif": ("avif",)}, slug="resize-image",
    keywords=("scale", "shrink", "dimensions"),
))


# ---------------------------------------------------------------------------
# compress


class CompressOptions(Options):
    quality: int = Field(75, ge=1, le=100, title="Quality", description="Lower means a smaller file.",
                         json_schema_extra=ui(widget="slider", targets=LOSSY))
    max_dimension: int | None = Field(None, ge=16, le=20000, title="Longest side (optional)",
                                      description="Also shrink the image so its longest side is at most this many pixels.",
                                      json_schema_extra=ui(unit="px", advanced=True))
    reduce_colors: bool = Field(False, title="Reduce to 256 colors",
                                description="Much smaller PNGs for graphics and screenshots; not for photos.",
                                json_schema_extra=ui(targets=("png",)))
    strip_metadata: bool = Field(True, title="Strip metadata", description="Remove EXIF (camera, GPS) and other metadata.")


def compress(ctx: Ctx) -> None:
    o: CompressOptions = ctx.options  # type: ignore[assignment]
    fmt = ctx.input.format
    ctx.stage("Decoding")
    src = open_image(ctx, ctx.input.path)
    out = ctx.default_out(fmt)
    n = getattr(src, "n_frames", 1)
    if n > 1 and fmt in ("gif", "webp"):
        frames, durs = [], []
        for i, total, fr, d in _frames(src):
            fr = fr.convert("RGBA")
            if o.max_dimension:
                fr.thumbnail((o.max_dimension, o.max_dimension), Image.Resampling.LANCZOS)
            frames.append(fr)
            durs.append(d)
            ctx.progress(i + 1, total, stage=f"Frame {i + 1} of {total}")
        _save_animated(frames, durs, out, fmt, src.info.get("loop", 0))
    else:
        im = ImageOps.exif_transpose(src.copy()) or src
        if o.max_dimension and max(im.size) > o.max_dimension:
            im.thumbnail((o.max_dimension, o.max_dimension), Image.Resampling.LANCZOS)
        ctx.stage("Compressing")
        im = normalize_mode(im, fmt, "#ffffff")
        if fmt == "png" and o.reduce_colors:
            im = im.convert("RGBA").quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)
        exif = None if o.strip_metadata else src.info.get("exif")
        icc = src.info.get("icc_profile")
        _save(im, out, fmt, quality=o.quality, exif=exif, icc=icc)
    before, after = ctx.input.size, out.stat().st_size
    ctx.info.update(input_size=before, output_size=after)
    if after >= before:
        # Never hand back a bigger file labelled "compressed".
        shutil.copyfile(ctx.input.path, out)
        ctx.warn("We couldn't make this file any smaller, so this download is your original file, unchanged.")
        ctx.info["returned_original"] = True
        ctx.add_output(out, fmt, label="Your original file (already as small as we can make it)")
    else:
        ctx.notice(f"Reduced from {before:,} to {after:,} bytes ({round(100 * (before - after) / before)}% smaller).")
        ctx.add_output(out, fmt)


register(Operation(
    id="image.compress", category="images", label="Compress image",
    description="Make an image file smaller by re-encoding it, optionally shrinking it and removing metadata.",
    inputs=("png", "jpg", "webp", "gif", "avif", "tiff"), outputs=(), cardinality="transform", options=CompressOptions,
    run=compress, engines=("pillow",), format_engines={"avif": ("avif",)}, slug="compress-image",
    keywords=("optimize", "reduce size", "smaller"),
))


# ---------------------------------------------------------------------------
# metadata / DPI


class MetadataOptions(Options):
    strip_metadata: bool = Field(True, title="Strip metadata", description="Remove EXIF (camera, GPS, date) and comments.")
    dpi: int | None = Field(None, ge=1, le=4800, title="Set DPI (optional)",
                            description="Print resolution stored in the file. Doesn't change pixels.",
                            json_schema_extra=ui(unit="dpi", targets=("jpg", "png", "tiff", "bmp")))


def metadata(ctx: Ctx) -> None:
    o: MetadataOptions = ctx.options  # type: ignore[assignment]
    fmt = ctx.input.format
    src = open_image(ctx, ctx.input.path)
    if getattr(src, "n_frames", 1) > 1 and fmt in ("gif", "webp"):
        raise ConversionError("unsupported_input", "Editing metadata of animated images isn't supported.")
    ctx.stage("Rewriting")
    im = ImageOps.exif_transpose(src.copy()) or src
    im = normalize_mode(im, fmt, "#ffffff")
    out = ctx.default_out(fmt)
    exif = None if o.strip_metadata else src.info.get("exif")
    dpi = (o.dpi, o.dpi) if o.dpi else src.info.get("dpi")
    # lossless where possible so only metadata changes
    _save(im, out, fmt, quality=95, exif=exif, icc=src.info.get("icc_profile"), dpi=dpi, lossless=fmt == "webp")
    if o.strip_metadata:
        ctx.notice("Removed EXIF and other metadata.")
    if o.dpi:
        ctx.notice(f"Set print resolution to {o.dpi} DPI.")
    if fmt in ("jpg", "avif"):
        ctx.notice("JPG and AVIF are re-encoded at high quality to rewrite metadata.")
    ctx.add_output(out, fmt)


register(Operation(
    id="image.metadata", category="images", label="Strip metadata / set DPI",
    description="Remove EXIF data such as GPS location and camera details, or set the print resolution.",
    inputs=("jpg", "png", "webp", "tiff", "avif", "bmp"), outputs=(), cardinality="transform", options=MetadataOptions,
    run=metadata, engines=("pillow",), format_engines={"avif": ("avif",)}, slug="image-metadata",
    keywords=("exif", "gps", "privacy", "dpi", "remove metadata"),
))


# ---------------------------------------------------------------------------
# raster → HEIC (experimental: encoder and patent constraints)


class HeicOptions(Options):
    quality: int = Field(85, ge=1, le=100, title="Quality", json_schema_extra=ui(widget="slider"))


def to_heic(ctx: Ctx) -> None:
    import pillow_heif

    pillow_heif.register_heif_opener()
    o: HeicOptions = ctx.options  # type: ignore[assignment]
    src = open_image(ctx, ctx.input.path)
    if getattr(src, "n_frames", 1) > 1:
        ctx.notice("HEIC output keeps only the first frame.")
        src.seek(0)
    im = ImageOps.exif_transpose(src.copy()) or src
    im = im.convert("RGBA") if has_alpha(im) else im.convert("RGB")
    ctx.stage("Encoding HEIC")
    out = ctx.default_out("heic")
    im.save(out, "HEIF", quality=o.quality)
    ctx.add_output(out, "heic")


register(Operation(
    id="image.to_heic", category="images", label="Convert to HEIC",
    description="Encode images as HEIC (HEVC). Experimental: encoder support and patent licensing vary by platform.",
    inputs=("png", "jpg", "webp", "gif", "bmp", "tiff", "avif"), outputs=("heic",), cardinality="one_to_one",
    options=HeicOptions, run=to_heic, engines=("pillow", "pillow-heif"), format_engines={"avif": ("avif",)},
    support="experimental",
    limitations=("HEVC encoding is subject to patent licensing; some viewers can't open these files.",),
))
