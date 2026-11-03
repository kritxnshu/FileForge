"""Browser-only utilities (runtime="client"); implementations in apps/web/src/lib/tools/utils.ts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ...registry import Operation, Options, register, ui

IMAGES = ("png", "jpg", "gif", "webp", "svg", "avif", "bmp", "ico")


def client(**kw) -> Operation:
    kw.setdefault("runtime", "client")
    kw.setdefault("cardinality", "transform")
    return register(Operation(**kw))


class ImageB64Options(Options):
    output: Literal["data_uri", "base64", "css", "html"] = Field("data_uri", title="Output as",
                                                                  description="css: background-image rule; html: <img> tag.")


client(id="util.image_base64", category="utilities", label="Image to Base64",
       description="Turn an image into a Base64 string or data URI for CSS, HTML or JSON.", inputs=IMAGES, outputs=("txt",),
       cardinality="one_to_one", options=ImageB64Options, keywords=("data uri", "inline image", "base64"))


class ColorOptions(Options):
    contrast_with: str = Field("#ffffff", pattern=r"^#[0-9a-fA-F]{6}$", title="Check contrast against",
                               json_schema_extra=ui(widget="color"))


client(id="util.color", category="utilities", label="Color converter",
       description="Convert colors between HEX, RGB, HSL and OKLCH, and check contrast for accessibility.",
       inputs=("txt",), outputs=(), options=ColorOptions, slug="color-converter",
       keywords=("hex to rgb", "rgb to hex", "hsl", "oklch", "contrast ratio", "wcag"))


class UnitOptions(Options):
    from_unit: Literal["px", "in", "cm", "mm", "pt"] = Field("px", title="From")
    dpi: float = Field(96, gt=0, le=4800, title="DPI", description="Pixels per inch. Screens use 96 by convention.")


client(id="util.units", category="utilities", label="Length unit converter",
       description="Convert between pixels, inches, centimeters, millimeters and points.", inputs=("txt",), outputs=(),
       options=UnitOptions, slug="unit-converter", keywords=("px to cm", "inches", "points", "dpi"))


class ByteOptions(Options):
    from_unit: Literal["B", "KB", "MB", "GB", "TB", "KiB", "MiB", "GiB", "TiB"] = Field("MB", title="From")


client(id="util.bytes", category="utilities", label="File size converter",
       description="Convert between bytes, KB, MB, GB and TB, with decimal (1000) and binary (1024) units side by side.",
       inputs=("txt",), outputs=(), options=ByteOptions, slug="bytes-converter", keywords=("mb to gb", "kib", "mib"))


class QrOptions(Options):
    error_correction: Literal["L", "M", "Q", "H"] = Field("M", title="Error correction",
                                                          description="Higher levels survive more damage but make denser codes.")
    size: int = Field(512, ge=64, le=4096, title="Size", json_schema_extra=ui(unit="px", targets=("png",)))
    margin: int = Field(4, ge=0, le=16, title="Quiet zone", description="Blank border, in modules (4 is standard).")
    foreground: str = Field("#000000", pattern=r"^#[0-9a-fA-F]{6}$", title="Color", json_schema_extra=ui(widget="color"))
    background: str = Field("#ffffff", pattern=r"^#[0-9a-fA-F]{6}$", title="Background", json_schema_extra=ui(widget="color"))


client(id="util.qr", category="utilities", label="QR code generator",
       description="Make a QR code for a link or text, as PNG or SVG.", inputs=("txt",), outputs=("png", "svg"),
       cardinality="one_to_one", options=QrOptions, keywords=("qr", "barcode", "link"))
