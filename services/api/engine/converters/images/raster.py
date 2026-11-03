"""Raster image conversion with Pillow (+ pillow-heif for HEIC/HEIF input)."""

from __future__ import annotations

from typing import Literal

from PIL import Image, ImageOps
from pydantic import Field

from ...context import ConversionError, Ctx
from ...registry import Operation, Options, register, ui

RASTER = ("png", "jpg", "webp", "gif", "bmp", "tiff", "ico", "avif")
RASTER_IN = (*RASTER, "heic")
ALPHA_TARGETS = {"png", "webp", "gif", "tiff", "ico", "avif", "heic"}
ANIMATED_TARGETS = {"gif", "webp"}
QUALITY_TARGETS = ("jpg", "webp", "avif", "heic")
PIL_FORMAT = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP", "gif": "GIF", "bmp": "BMP", "tiff": "TIFF",
              "ico": "ICO", "avif": "AVIF", "heic": "HEIF"}
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


class ImageConvertOptions(Options):
    quality: int = Field(85, ge=1, le=100, title="Quality",
                         description="Higher is better quality and a larger file.",
                         json_schema_extra=ui(targets=QUALITY_TARGETS, widget="slider"))
    background: str = Field("#ffffff", pattern=r"^#[0-9a-fA-F]{6}$", title="Background color",
                            description="Used to fill transparent areas when the target format has no transparency.",
                            json_schema_extra=ui(widget="color", targets=("jpg", "bmp")))
    lossless: bool = Field(False, title="Lossless", description="Lossless WebP/AVIF encoding (larger files).",
                           json_schema_extra=ui(advanced=True, targets=("webp", "avif")))
    ico_sizes: list[Literal[16, 24, 32, 48, 64, 128, 256]] = Field(
        list(ICO_SIZES), title="Icon sizes", description="Sizes (px) to embed in the .ico file.",
        json_schema_extra=ui(widget="multiselect", targets=("ico",)))
    strip_metadata: bool = Field(False, title="Strip metadata",
                                 description="Remove EXIF (camera, GPS) and other metadata.",
                                 json_schema_extra=ui(advanced=True))


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def has_alpha(im: Image.Image) -> bool:
    return im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)


def normalize_mode(im: Image.Image, target: str, background: str) -> Image.Image:
    """Convert to a mode the target encoder accepts, flattening alpha when needed."""
    alpha = has_alpha(im)
    if im.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
        im = ImageOps.autocontrast(im.convert("I")).convert("L") if im.mode != "I;16" else im.point(lambda v: v / 256).convert("L")
    if im.mode == "CMYK" and target != "jpg":
        im = im.convert("RGB")
    if alpha and target not in ALPHA_TARGETS:
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, _hex(background))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    if alpha:
        return im.convert("RGBA") if im.mode != "RGBA" and target != "gif" else im
    if target == "jpg" and im.mode not in ("RGB", "L", "CMYK"):
        return im.convert("RGB")
    if target in ("bmp", "avif", "heic", "webp", "ico") and im.mode not in ("RGB", "L", "RGBA"):
        return im.convert("RGB")
    if im.mode not in ("RGB", "RGBA", "L", "LA", "P", "1", "CMYK"):
        return im.convert("RGB")
    return im


def save_kwargs(target: str, opts: ImageConvertOptions, im: Image.Image) -> dict:
    kw: dict = {}
    if target == "jpg":
        kw.update(quality=opts.quality, optimize=True, progressive=True)
    elif target == "webp":
        kw.update(quality=opts.quality, method=4, lossless=opts.lossless)
    elif target == "avif":
        kw.update(quality=100 if opts.lossless else opts.quality, speed=6)
    elif target == "heic":
        kw.update(quality=opts.quality)
    elif target == "png":
        kw.update(optimize=True)
    elif target == "tiff":
        kw.update(compression="tiff_lzw")
    if not opts.strip_metadata:
        if (exif := im.info.get("exif")) and target in ("jpg", "webp", "png", "tiff", "avif", "heic"):
            kw["exif"] = exif
        if (icc := im.info.get("icc_profile")) and target in ("jpg", "webp", "png", "tiff", "avif", "heic"):
            kw["icc_profile"] = icc
    return kw


def open_image(ctx: Ctx, path) -> Image.Image:
    try:
        im = Image.open(path)
        im.load()
    except Image.DecompressionBombError:
        raise
    except Exception as e:
        raise ConversionError("corrupt_input", "This image is damaged or truncated and can't be read.") from e
    return im


def _save_ico(im: Image.Image, path, sizes: list[int]) -> None:
    im = im.convert("RGBA")
    side = max(im.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    if side != 256:
        canvas = canvas.resize((256, 256), Image.Resampling.LANCZOS)
    canvas.save(path, "ICO", sizes=[(s, s) for s in sorted(set(sizes))])


def convert_image(ctx: Ctx) -> None:
    opts: ImageConvertOptions = ctx.options  # type: ignore[assignment]
    target = ctx.target
    ctx.stage("Decoding")
    src = open_image(ctx, ctx.input.path)
    n_frames = getattr(src, "n_frames", 1)
    animated = n_frames > 1 and ctx.input.format in ("gif", "webp", "png", "avif")
    out = ctx.default_out()

    if animated and target in ANIMATED_TARGETS:
        frames, durations = [], []
        for i in range(n_frames):
            src.seek(i)
            fr = ImageOps.exif_transpose(src.copy()) if i == 0 else src.copy()
            frames.append(normalize_mode(fr.convert("RGBA"), target, opts.background))
            durations.append(src.info.get("duration", 100) or 100)
            ctx.progress(i + 1, n_frames, stage=f"Frame {i + 1} of {n_frames}")
        ctx.stage("Encoding")
        kw = save_kwargs(target, opts, src)
        kw.pop("exif", None)
        kw.pop("icc_profile", None)
        loop = src.info.get("loop", 0)
        if target == "gif":
            frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=durations, loop=loop,
                           disposal=2, optimize=False)
        else:
            frames[0].save(out, "WEBP", save_all=True, append_images=frames[1:], duration=durations, loop=loop, **kw)
        ctx.info["frames"] = n_frames
        ctx.notice(f"Kept all {n_frames} animation frames and their timing.")
    else:
        if n_frames > 1:
            src.seek(0)
            what = "pages" if ctx.input.format == "tiff" else "animation frames"
            ctx.notice(f"{ctx.target.upper()} can't hold multiple {what}, so only the first one was converted.")
        im = ImageOps.exif_transpose(src)
        if im is None:
            im = src
        ctx.stage("Encoding")
        flat_needed = has_alpha(im) and target not in ALPHA_TARGETS
        im2 = normalize_mode(im, target, opts.background)
        if flat_needed:
            ctx.notice(f"{target.upper()} has no transparency; transparent areas were filled with {opts.background}.")
        if target == "ico":
            _save_ico(im2, out, list(opts.ico_sizes))
        else:
            im2.save(out, PIL_FORMAT[target], **save_kwargs(target, opts, im))
    ctx.info["input_size"] = ctx.input.size
    ctx.add_output(out)


register(Operation(
    id="image.convert",
    category="images",
    label="Convert image",
    description="Works across all common raster formats, keeping transparency and animation wherever the target format supports them.",
    inputs=RASTER_IN,
    outputs=RASTER,
    cardinality="one_to_one",
    options=ImageConvertOptions,
    run=convert_image,
    engines=("pillow",),
    format_engines={"avif": ("avif",), "heic": ("pillow-heif",)},
    pair_limitations={
        **{(s, t): ("Animated images keep only their first frame in this format.",)
           for s in ("gif", "webp") for t in RASTER if t not in ANIMATED_TARGETS and t != s},
        **{(s, "jpg"): ("JPG has no transparency; transparent areas are filled with the background color.",)
           for s in ("png", "webp", "gif", "tiff", "ico", "avif", "heic")},
    },
    keywords=("photo", "picture", "image converter"),
))
