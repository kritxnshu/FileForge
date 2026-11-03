"""Fixture generator. Every fixture holds *known content* so tests can check it
survived conversion. Generated files are cached in tests/fixtures/generated/.

Run directly to (re)build everything:  python tests/fixtures/generate.py
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "generated"
STATIC = HERE / "static"

KNOWN_SENTENCE = "The quick brown fox jumps over the lazy dog 12345"
KNOWN_TABLE = [["Name", "Qty", "Price"], ["Apple", 3, 1.5], ["Banana", 12, 0.25], ["Cherry", 7, 4.0]]
RED, BLUE = (255, 0, 0), (0, 0, 255)
IMG = 64  # square, so ICO padding doesn't move the colour blocks

_BUILDERS: dict[str, Callable[[Path], None]] = {}


def builder(name: str):
    def deco(fn):
        _BUILDERS[name] = fn
        return fn

    return deco


def path(name: str) -> Path:
    """Return the fixture path, generating it on first use."""
    if (STATIC / name).exists():
        return STATIC / name
    p = OUT / name
    if not p.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        if name not in _BUILDERS:
            raise KeyError(f"no fixture builder for {name}")
        tmp = OUT / f".tmp-{os.getpid()}-{name}"
        _BUILDERS[name](tmp)
        tmp.replace(p)
    return p


def available() -> list[str]:
    return sorted(_BUILDERS)


# ---------------------------------------------------------------------------
# images


def base_image(alpha: bool = True):
    from PIL import Image

    im = Image.new("RGBA", (IMG, IMG), RED + (255,))
    im.paste(Image.new("RGBA", (IMG // 2, IMG), BLUE + (255,)), (IMG // 2, 0))
    if alpha:
        im.paste(Image.new("RGBA", (16, 16), (0, 0, 0, 0)), (IMG - 16, 0))
    return im


def _save_image(fmt: str, alpha: bool):
    def build(p: Path) -> None:
        from PIL import Image

        im = base_image(alpha)
        if fmt == "JPEG":
            im = im.convert("RGB")
            im.save(p, "JPEG", quality=95)
        elif fmt == "BMP":
            im.convert("RGB").save(p, "BMP")
        elif fmt == "GIF":
            im.save(p, "GIF")
        elif fmt == "ICO":
            im.save(p, "ICO", sizes=[(16, 16), (32, 32), (64, 64)])
        elif fmt == "HEIF":
            import pillow_heif

            pillow_heif.register_heif_opener()
            im.save(p, "HEIF", quality=95)
        elif fmt == "AVIF":
            im.save(p, "AVIF", quality=95)
        elif fmt == "TIFF":
            im.save(p, "TIFF", compression="tiff_lzw")
        else:
            im.save(p, fmt, **({"lossless": True} if fmt == "WEBP" else {}))
        Image.open(p).load()

    return build


for _name, _fmt, _alpha in [
    ("image.png", "PNG", True), ("image.jpg", "JPEG", False), ("image.webp", "WEBP", True),
    ("image.gif", "GIF", True), ("image.bmp", "BMP", False), ("image.tiff", "TIFF", True),
    ("image.ico", "ICO", True), ("image.avif", "AVIF", True), ("image.heic", "HEIF", True),
]:
    builder(_name)(_save_image(_fmt, _alpha))


def _animated(fmt: str):
    def build(p: Path) -> None:
        from PIL import Image

        frames = [Image.new("RGBA", (IMG, IMG), c + (255,)) for c in (RED, (0, 255, 0), BLUE)]
        frames[0].save(p, fmt, save_all=True, append_images=frames[1:], duration=[100, 200, 300], loop=0,
                       **({"lossless": True} if fmt == "WEBP" else {}))

    return build


builder("animated.gif")(_animated("GIF"))
builder("animated.webp")(_animated("WEBP"))


@builder("rotated.jpg")
def _rotated(p: Path) -> None:
    """64x32 pixels stored landscape with EXIF orientation 6 (display = portrait 32x64)."""
    from PIL import Image

    im = Image.new("RGB", (64, 32), RED)
    exif = Image.Exif()
    exif[0x0112] = 6
    im.save(p, "JPEG", exif=exif.tobytes(), quality=95)


@builder("rotated.heic")
def _rotated_heic(p: Path) -> None:
    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    im = Image.new("RGB", (64, 32), RED)
    exif = Image.Exif()
    exif[0x0112] = 6
    im.save(p, "HEIF", exif=exif.tobytes(), quality=95)


@builder("image.svg")
def _svg(p: Path) -> None:
    p.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{IMG}" height="{IMG}" viewBox="0 0 {IMG} {IMG}">'
        f'<rect x="0" y="0" width="{IMG // 2}" height="{IMG}" fill="#ff0000"/>'
        f'<rect x="{IMG // 2}" y="0" width="{IMG // 2}" height="{IMG}" fill="#0000ff"/>'
        f'<rect x="{IMG - 16}" y="0" width="16" height="16" fill="#ffffff" fill-opacity="0"/>'
        f'<text x="2" y="60" font-size="6" fill="#ffffff">{KNOWN_SENTENCE[:9]}</text></svg>'
    )


@builder("bomb.png")
def _bomb(p: Path) -> None:
    """A tiny PNG that claims 20000x20000 pixels (400 MP > 100 MP cap)."""
    import struct
    import zlib

    w = h = 20000
    raw = zlib.compress(b"\x00" * (w // 8 + 1) * 16, 9)

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    p.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 1, 0, 0, 0, 0))
                  + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


@builder("truncated.png")
def _truncated(p: Path) -> None:
    data = path("image.png").read_bytes()
    p.write_bytes(data[: len(data) // 2])


@builder("png-named.jpg")
def _mismatch(p: Path) -> None:
    shutil.copyfile(path("image.png"), p)


@builder("garbage.bin")
def _garbage(p: Path) -> None:
    p.write_bytes(bytes((i * 7919 + 13) % 256 for i in range(4096)))


if __name__ == "__main__":
    for n in available():
        print(path(n))
    sys.exit(0)
