"""Fonts with fontTools: web-font packaging (WOFF/WOFF2, Full) and TrueType ↔ CFF outline conversion (Experimental)."""

from __future__ import annotations

from pydantic import Field

from ...context import ConversionError, Ctx
from ...registry import NoOptions, Operation, Options, register, ui

FLAVOR = {"woff": "woff", "woff2": "woff2", "ttf": None, "otf": None}


def _open(ctx: Ctx):
    from fontTools.ttLib import TTFont, TTLibError

    try:
        f = TTFont(str(ctx.input.path), lazy=False, recalcBBoxes=False, recalcTimestamp=False)
        f.getGlyphOrder()
        return f
    except (TTLibError, AssertionError, KeyError, ValueError, Exception) as e:
        raise ConversionError("corrupt_input", "This font file is damaged or isn't a valid font.") from e


def _outline(font) -> str:
    return "cff" if ("CFF " in font or "CFF2" in font) else "glyf"


def package(ctx: Ctx) -> None:
    font = _open(ctx)
    tgt = ctx.target
    kind = _outline(font)
    if tgt == "ttf" and kind == "cff":
        raise ConversionError("needs_outline_conversion", "This font has PostScript (CFF) outlines, so it unpacks to OTF, not TTF. "
                                                          "Choose OTF, or use “Convert font outlines”.")
    if tgt == "otf" and kind == "glyf":
        raise ConversionError("needs_outline_conversion", "This font has TrueType outlines, so it unpacks to TTF, not OTF. "
                                                          "Choose TTF, or use “Convert font outlines”.")
    font.flavor = FLAVOR[tgt]
    ctx.stage("Packaging font")
    out = ctx.default_out()
    try:
        font.save(str(out))
    except Exception as e:
        raise ConversionError("engine_error", "This font couldn't be repackaged.") from e
    ctx.notice("Outlines, hinting and metadata are unchanged; only the packaging changed.")
    ctx.add_output(out)


_PAIRS = (("ttf", "woff"), ("ttf", "woff2"), ("otf", "woff"), ("otf", "woff2"), ("woff", "woff2"), ("woff2", "woff"),
          ("woff", "ttf"), ("woff2", "ttf"), ("woff", "otf"), ("woff2", "otf"))

register(Operation(
    id="font.convert", category="utilities", label="Convert font",
    description="Package fonts for the web (WOFF, WOFF2) or unpack web fonts back to TTF/OTF.",
    inputs=("ttf", "otf", "woff", "woff2"), outputs=("ttf", "otf", "woff", "woff2"), cardinality="one_to_one",
    options=NoOptions, run=package, engines=("fonttools",), explicit_pairs=_PAIRS,
    pair_limitations={(s, t): ("Works when the web font wraps matching outlines (TrueType → TTF, CFF → OTF).",)
                      for s, t in _PAIRS if t in ("ttf", "otf")},
    keywords=("web font", "woff2", "typeface"),
))


class OutlineOptions(Options):
    max_error: float = Field(1.0, gt=0, le=10, title="Curve tolerance",
                             description="How far (in font units) converted curves may deviate. Lower is more accurate.",
                             json_schema_extra=ui(targets=("ttf",), advanced=True))


def outlines(ctx: Ctx) -> None:
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import newTable

    o: OutlineOptions = ctx.options  # type: ignore[assignment]
    font = _open(ctx)
    gs = font.getGlyphSet()
    order = font.getGlyphOrder()
    n = len(order)
    if ctx.target == "ttf":
        if _outline(font) != "cff":
            raise ConversionError("invalid_input", "This font already has TrueType outlines.")
        glyf = {}
        for k, name in enumerate(order):
            ctx.progress(k, n, stage=f"Converting glyph {k + 1} of {n}")
            pen = TTGlyphPen(None)
            gs[name].draw(Cu2QuPen(pen, o.max_error, reverse_direction=True))
            glyf[name] = pen.glyph()
        for t in ("CFF ", "CFF2", "VORG"):
            if t in font:
                del font[t]
        fb = FontBuilder(font=font)
        font["loca"] = newTable("loca")
        font["glyf"] = newTable("glyf")
        font["glyf"].glyphOrder = order
        font["glyf"].glyphs = glyf
        font["maxp"].tableVersion = 0x00010000
        for attr in ("maxZones", "maxTwilightPoints", "maxStorage", "maxFunctionDefs", "maxInstructionDefs",
                     "maxStackElements", "maxSizeOfInstructions", "maxComponentElements", "maxPoints", "maxContours",
                     "maxCompositePoints", "maxCompositeContours", "maxComponentDepth"):
            setattr(font["maxp"], attr, 0 if attr != "maxZones" else 1)
        font["head"].glyphDataFormat = 0
        font["head"].indexToLocFormat = 0
        font.sfntVersion = "\x00\x01\x00\x00"
        fb.font = font
        if font["post"].formatType == 3.0:
            font["post"].formatType = 2.0
            font["post"].extraNames = []
            font["post"].mapping = {}
            font["post"].glyphOrder = order
    else:
        if _outline(font) != "glyf":
            raise ConversionError("invalid_input", "This font already has PostScript (CFF) outlines.")
        upm = font["head"].unitsPerEm
        hmtx = font["hmtx"].metrics
        charstrings = {}
        for k, name in enumerate(order):
            ctx.progress(k, n, stage=f"Converting glyph {k + 1} of {n}")
            pen = T2CharStringPen(hmtx[name][0], gs)
            gs[name].draw(pen)  # quadratic curves become exact cubics
            charstrings[name] = pen.getCharString()
        ps = font["name"].getDebugName(6) or "Converted-Regular"
        for t in ("glyf", "loca", "fpgm", "prep", "cvt ", "gasp", "hdmx", "LTSH", "VDMX"):
            if t in font:
                del font[t]
        fb = FontBuilder(font=font, isTTF=False)
        fb.setupCFF(ps.replace(" ", ""), {"FullName": font["name"].getDebugName(4) or ps}, charstrings, {})
        font["maxp"] = newTable("maxp")
        font["maxp"].tableVersion = 0x00005000
        font["maxp"].numGlyphs = n
        font.sfntVersion = "OTTO"
        _ = upm
    out = ctx.default_out()
    font.flavor = None
    font.recalcBBoxes = True  # new outlines need fresh glyph and font bounding boxes
    font.save(str(out))
    ctx.notice("Outlines were converted; TrueType hinting doesn't carry over between outline formats.")
    ctx.add_output(out)


register(Operation(
    id="font.outlines", category="utilities", label="Convert font outlines",
    description="Convert between TrueType (TTF) and PostScript/CFF (OTF) outlines.", inputs=("ttf", "otf"),
    outputs=("ttf", "otf"), cardinality="one_to_one", options=OutlineOptions, run=outlines, engines=("fonttools",),
    support="experimental",
    limitations=("Hinting is dropped; CFF → TrueType approximates curves within the tolerance you set.",),
    keywords=("ttf to otf", "otf to ttf"),
))
