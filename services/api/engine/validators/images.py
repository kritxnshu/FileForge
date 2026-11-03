from __future__ import annotations

from pathlib import Path

from . import check, magic

PIL_FMT = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP", "gif": "GIF", "bmp": "BMP", "tiff": "TIFF", "ico": "ICO",
           "avif": "AVIF", "heic": "HEIF"}


def _close(a, b, tol: int) -> bool:
    return all(abs(int(x) - int(y)) <= tol for x, y in zip(a[:3], b[:3]))


def open_image(path: Path):
    from PIL import Image

    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    im = Image.open(path)
    im.load()
    return im


def validate_image(path: Path, fmt: str, *, expect_alpha: bool | None = None, background=(255, 255, 255),
                   lossy: bool = False, frames: int | None = None, size: tuple[int, int] | None = None,
                   color_blocks: bool = True) -> None:
    """Format, dimensions, alpha, and the known red/blue colour blocks."""
    magic(path, fmt)
    im = open_image(path)
    check(im.format == PIL_FMT[fmt], f"decoded as {im.format}, expected {PIL_FMT[fmt]}")
    if frames is not None:
        check(getattr(im, "n_frames", 1) == frames, f"expected {frames} frames, got {getattr(im, 'n_frames', 1)}")
    if fmt == "ico":
        sizes = im.info.get("sizes") or set()
        check(len(sizes) >= 3, f"ICO should hold multiple sizes, has {sizes}")
        check((256, 256) in sizes or max(sizes)[0] >= 64, f"ICO largest size too small: {sizes}")
        im.size = max(sizes)  # type: ignore[misc]
        im.load()
    if size:
        check(im.size == size, f"size {im.size} != {size}")
    if not color_blocks:
        return
    w, h = im.size
    rgba = im.convert("RGBA")
    tol = 40 if lossy else 6
    red = rgba.getpixel((int(w * 0.2), int(h * 0.5)))
    blue = rgba.getpixel((int(w * 0.65), int(h * 0.75)))
    check(_close(red, (255, 0, 0), tol), f"left block should be red, got {red}")
    check(_close(blue, (0, 0, 255), tol), f"right block should be blue, got {blue}")
    if expect_alpha is not None:
        corner = rgba.getpixel((int(w * 0.9), int(h * 0.1)))
        if expect_alpha:
            check(corner[3] < 32, f"top-right corner should be transparent, got {corner}")
        else:
            check(corner[3] == 255 and _close(corner, background, tol), f"corner should be flattened to {background}, got {corner}")
