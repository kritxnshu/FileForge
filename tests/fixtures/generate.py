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
        f'<rect x="{IMG // 2}" y="16" width="{IMG // 2}" height="{IMG - 16}" fill="#0000ff"/>'
        f'<rect x="{IMG // 2}" y="0" width="{IMG // 2 - 16}" height="16" fill="#0000ff"/>'
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


@builder("big-gradient.png")
def _big(p: Path) -> None:
    """49 MP, compresses well (small upload) but takes seconds to encode — used for cancel/timeout tests."""
    from PIL import Image

    g = Image.linear_gradient("L").resize((7000, 7000))
    Image.merge("RGB", (g, g.rotate(90), g.rotate(180))).save(p, "PNG", optimize=False, compress_level=9)

# ---------------------------------------------------------------------------
# documents


def _soffice() -> str:
    sys.path.insert(0, str(HERE.parents[1] / "services" / "api"))
    from engine.registry import soffice_path

    exe = soffice_path()
    if not exe:
        raise RuntimeError("LibreOffice is needed to build legacy-format fixtures")
    return exe


def _lo_convert(src: Path, dst: Path, flt: str) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        prof = Path(td) / "prof"
        subprocess.run([_soffice(), "--headless", "--norestore", f"-env:UserInstallation={prof.as_uri()}",
                        "--convert-to", flt, "--outdir", td, str(src)], check=True, capture_output=True, timeout=180)
        produced = Path(td) / (src.stem + "." + flt.split(":")[0])
        shutil.move(produced, dst)


@builder("document.docx")
def _docx(p: Path) -> None:
    from docx import Document

    d = Document()
    d.add_heading("Quarterly Report", level=1)
    d.add_paragraph(KNOWN_SENTENCE)
    t = d.add_table(rows=len(KNOWN_TABLE), cols=3)
    for r, row in enumerate(KNOWN_TABLE):
        for c, v in enumerate(row):
            t.cell(r, c).text = str(v)
    d.add_paragraph("Second paragraph with ünïcödé text.")
    d.save(p)


for _ext, _flt in [("doc", 'doc:MS Word 97'), ("odt", "odt"), ("rtf", "rtf")]:
    def _mk(ext=_ext, flt=_flt):
        def build(p: Path) -> None:
            src = OUT / f"_src_{os.getpid()}.docx"
            shutil.copyfile(path("document.docx"), src)
            try:
                _lo_convert(src, p, flt)
            finally:
                src.unlink(missing_ok=True)
        return build
    builder(f"document.{_ext}")(_mk())


@builder("document.txt")
def _txt(p: Path) -> None:
    p.write_text(f"{KNOWN_SENTENCE}\n\nSecond paragraph with ünïcödé text.\n", encoding="utf-8")


@builder("document.md")
def _md(p: Path) -> None:
    rows = "\n".join("| " + " | ".join(str(c) for c in r) + " |" for r in KNOWN_TABLE[1:])
    p.write_text(f"# Quarterly Report\n\n{KNOWN_SENTENCE}\n\n| Name | Qty | Price |\n|---|---|---|\n{rows}\n\n"
                 "- item one\n- item two\n\n[a link](https://example.com)\n", encoding="utf-8")


@builder("document.html")
def _html(p: Path) -> None:
    rows = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in KNOWN_TABLE)
    p.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>Report</title></head><body>"
                 f"<h1>Quarterly Report</h1><p>{KNOWN_SENTENCE}</p><table>{rows}</table>"
                 "<ul><li>item one</li><li>item two</li></ul></body></html>", encoding="utf-8")


def _pdf(p: Path, pages: int = 3, table: bool = True) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet

    st = getSampleStyleSheet()
    story = [Paragraph("Quarterly Report", st["Title"]), Paragraph(KNOWN_SENTENCE, st["BodyText"])]
    if table:
        t = Table([[str(c) for c in r] for r in KNOWN_TABLE])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.8, colors.black)]))
        story.append(t)
    for i in range(2, pages + 1):
        story += [PageBreak(), Paragraph(f"Page {i} marker text", st["BodyText"])]
    SimpleDocTemplate(str(p), pagesize=A4).build(story)


builder("document.pdf")(lambda p: _pdf(p, 3))
builder("other.pdf")(lambda p: _pdf(p, 2, table=False))


@builder("encrypted.pdf")
def _enc(p: Path) -> None:
    import pikepdf

    with pikepdf.open(path("document.pdf")) as pdf:
        pdf.save(p, encryption=pikepdf.Encryption(user="secret", owner="owner-secret", R=6))


@builder("restricted.pdf")
def _restricted(p: Path) -> None:
    import pikepdf

    with pikepdf.open(path("document.pdf")) as pdf:
        pdf.save(p, encryption=pikepdf.Encryption(user="", owner="owner-secret", R=6,
                                                  allow=pikepdf.Permissions(extract=False, print_highres=False)))


@builder("scanned.pdf")
def _scanned(p: Path) -> None:
    """Image-only PDF: no text layer."""
    import img2pdf
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (800, 1100), "white")
    ImageDraw.Draw(im).text((60, 80), KNOWN_SENTENCE, fill="black")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    p.write_bytes(img2pdf.convert(buf.getvalue()))


@builder("photos.pdf")
def _photos(p: Path) -> None:
    """PDF with a large, noisy (poorly compressed) image + text: compressible."""
    import img2pdf
    from PIL import Image
    from pypdf import PdfReader, PdfWriter

    noise = Image.effect_noise((2400, 1800), 60).convert("RGB")
    noise = Image.blend(noise, Image.new("RGB", noise.size, (40, 120, 200)), 0.5)
    buf = io.BytesIO()
    noise.save(buf, "PNG")
    img_pdf = OUT / f"_img_{os.getpid()}.pdf"
    img_pdf.write_bytes(img2pdf.convert(buf.getvalue()))
    w = PdfWriter()
    for src in (path("document.pdf"), img_pdf):
        for pg in PdfReader(src).pages:
            w.add_page(pg)
    with p.open("wb") as f:
        w.write(f)
    img_pdf.unlink()


@builder("corrupt.pdf")
def _corrupt_pdf(p: Path) -> None:
    p.write_bytes(b"%PDF-1.7\n1 0 obj << /Type /Catalog /Pages 2 0 R >>\nendobj\n" + b"garbage" * 50)



if __name__ == "__main__":
    for n in available():
        print(path(n))
    sys.exit(0)
