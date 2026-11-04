"""Page geometry and drawing for tools that place things on pages (edit, sign, redact, crop, page numbers, forms).

The UI works in *display* coordinates: the page as it's rendered (crop box applied, /Rotate applied), normalised
to 0..1 from the top-left corner. PDF content lives in *user space*: points, origin at the bottom-left, before
rotation. `PageFrame` maps between the two for rotations of 0/90/180/270 degrees, so a box drawn on a page shown
rotated lands exactly where the user drew it, and text stamped on it reads upright.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path

from ...context import ConversionError


@dataclass(frozen=True)
class PageFrame:
    llx: float
    lly: float
    urx: float
    ury: float
    rotation: int  # 0, 90, 180 or 270, clockwise as displayed

    @property
    def cw(self) -> float:
        return self.urx - self.llx

    @property
    def ch(self) -> float:
        return self.ury - self.lly

    @property
    def width(self) -> float:
        """Displayed width in points."""
        return self.ch if self.rotation in (90, 270) else self.cw

    @property
    def height(self) -> float:
        return self.cw if self.rotation in (90, 270) else self.ch

    def matrix(self) -> tuple[float, float, float, float, float, float]:
        """Affine map from display points with a bottom-left origin (y up) to user space."""
        r = self.rotation
        if r == 90:
            return (0, 1, -1, 0, self.urx, self.lly)
        if r == 180:
            return (-1, 0, 0, -1, self.urx, self.ury)
        if r == 270:
            return (0, -1, 1, 0, self.llx, self.ury)
        return (1, 0, 0, 1, self.llx, self.lly)

    def to_user(self, u: float, v: float) -> tuple[float, float]:
        """Normalised display point (u → right, v → down) to user space."""
        ex, ey = u * self.width, (1 - v) * self.height
        a, b, c, d, e, f = self.matrix()
        return a * ex + c * ey + e, b * ex + d * ey + f

    def to_display(self, x: float, y: float) -> tuple[float, float]:
        """User-space point to normalised display coordinates (u → right, v → down)."""
        r = self.rotation
        if r == 90:
            dx, dy = y - self.lly, x - self.llx
        elif r == 180:
            dx, dy = self.urx - x, y - self.lly
        elif r == 270:
            dx, dy = self.ury - y, self.urx - x
        else:
            dx, dy = x - self.llx, self.ury - y
        return dx / self.width, dy / self.height

    def rect_to_user(self, u: float, v: float, w: float, h: float) -> tuple[float, float, float, float]:
        """Normalised display rectangle (top-left u, v; size w, h) to a user-space box (x0, y0, x1, y1)."""
        xs, ys = zip(*(self.to_user(a, b) for a, b in ((u, v), (u + w, v + h))))
        return min(xs), min(ys), max(xs), max(ys)


def _rotation(value) -> int:
    try:
        r = int(value) % 360
    except (TypeError, ValueError):
        return 0
    return r if r in (0, 90, 180, 270) else 0


def frame_pypdf(page) -> PageFrame:
    box = page.cropbox
    return PageFrame(float(box.left), float(box.bottom), float(box.right), float(box.top), _rotation(page.rotation))


def frame_pdfium(page) -> PageFrame:
    l, b, r, t = page.get_cropbox()
    return PageFrame(float(l), float(b), float(r), float(t), _rotation(page.get_rotation()))


def check_page(page_number: int, total: int) -> int:
    if page_number < 1 or page_number > total:
        raise ConversionError("invalid_option", f"Page {page_number} doesn't exist — this PDF has {total} page"
                                                f"{'s' if total != 1 else ''}.")
    return page_number - 1


# ---------------------------------------------------------------------------
# drawing on pages


def stamp(page, draw) -> None:
    """Draw on a pypdf page with reportlab, in display points (origin bottom-left, y up, rotation undone).

    `draw(canvas, frame)` sees a page of frame.width × frame.height points, upright as the user sees it.
    """
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas

    frame = frame_pypdf(page)
    mb = page.mediabox
    left, bottom = float(mb.left), float(mb.bottom)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(float(mb.width), float(mb.height)))
    a, b, cc, d, e, f = frame.matrix()
    c.transform(a, b, cc, d, e - left, f - bottom)
    draw(c, frame)
    c.save()
    buf.seek(0)
    page.merge_transformed_page(PdfReader(buf).pages[0], [1, 0, 0, 1, left, bottom])


# ---------------------------------------------------------------------------
# fonts

BASE_FONTS = {
    "helvetica": "Helvetica", "helvetica-bold": "Helvetica-Bold", "helvetica-italic": "Helvetica-Oblique",
    "times": "Times-Roman", "times-bold": "Times-Bold", "times-italic": "Times-Italic",
    "courier": "Courier", "courier-bold": "Courier-Bold",
}

# Unicode fallbacks for text the standard (Latin-1) fonts can't show. DejaVu ships in the Docker image.
UNICODE_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]


def _latin1(text: str) -> bool:
    try:
        text.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def font_for(text: str, font: str) -> str:
    """A registered reportlab font name able to draw `text`."""
    name = BASE_FONTS.get(font, "Helvetica")
    if _latin1(text):
        return name
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if "UCFallback" in pdfmetrics.getRegisteredFontNames():
        return "UCFallback"
    for p in [os.environ.get("UC_UNICODE_FONT", ""), *UNICODE_FONTS]:
        if p and Path(p).exists():
            try:
                pdfmetrics.registerFont(TTFont("UCFallback", p))
                return "UCFallback"
            except Exception:
                continue
    raise ConversionError("invalid_option", "This text uses characters the built-in fonts can't show, and no Unicode "
                                            "font is installed on this server.")


def hex_color(value: str, alpha: float = 1.0):
    from reportlab.lib.colors import Color, HexColor

    c = HexColor(value)
    return Color(c.red, c.green, c.blue, alpha=alpha)
