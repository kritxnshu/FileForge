"""Fonts: WOFF/WOFF2 packaging matrix and experimental outline conversion, checked by reopening with fontTools."""

from __future__ import annotations

import pytest
from conftest import convert, pairs_of
from fixtures.generate import path

from engine.validators import magic

SOURCE = {"ttf": "font.ttf", "otf": "font.otf", "woff": "font.woff", "woff2": "font.woff2"}


def glyph_bounds(p):
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.ttLib import TTFont

    f = TTFont(str(p))
    gs = f.getGlyphSet()
    out = {}
    for g in ("A", "B", "C"):
        pen = BoundsPen(gs)
        gs[g].draw(pen)
        out[g] = tuple(round(v) for v in pen.bounds)
    return f, out


def source_for(src: str, dst: str) -> str:
    # web fonts unpack to the outline type they wrap: our WOFF/WOFF2 fixtures wrap TrueType
    if src in ("woff", "woff2") and dst == "otf":
        return "otf-" + src
    return SOURCE[src]


@pytest.fixture(scope="module", autouse=True)
def cff_webfonts():
    from fontTools.ttLib import TTFont

    for flavor in ("woff", "woff2"):
        f = TTFont(str(path("font.otf")))
        f.flavor = flavor
        f.save(str(path("font.otf").parent / f"otf-{flavor}.{flavor}"))


@pytest.mark.parametrize("src,dst", pairs_of("font.convert"))
def test_font_packaging(src, dst):
    name = source_for(src, dst)
    fx = path("font.otf").parent / f"{name}.{src}" if name.startswith("otf-") else path(name)
    r = convert("font.convert", fx, dst, formats=[src])
    assert r.ok, r.error
    magic(r.out, dst)
    f, bounds = glyph_bounds(r.out)
    assert f.flavor == ({"woff": "woff", "woff2": "woff2"}.get(dst))
    _, want = glyph_bounds(fx)
    assert bounds == want
    assert f["name"].getDebugName(1) in ("Fixture Sans", "Fixture Serif")
    assert f.getBestCmap()[0x41] == "A"


@pytest.mark.verifies("neg:font.convert")
def test_font_packaging_negative(tmp_path):
    r = convert("font.convert", path("font.woff"), "otf")
    assert not r.ok and r.error["code"] == "needs_outline_conversion"
    bad = tmp_path / "bad.ttf"
    bad.write_bytes(path("font.ttf").read_bytes()[:200])
    r = convert("font.convert", bad, "woff2", formats=["ttf"])
    assert not r.ok and r.error["code"] == "corrupt_input"


@pytest.mark.parametrize("src,dst", pairs_of("font.outlines"))
def test_outline_conversion(src, dst):
    r = convert("font.outlines", path(SOURCE[src]), dst)
    assert r.ok, r.error
    magic(r.out, dst)
    f, bounds = glyph_bounds(r.out)
    assert ("glyf" in f) == (dst == "ttf") and ("CFF " in f) == (dst == "otf")
    _, want = glyph_bounds(path(SOURCE[src]))
    for g in want:  # outlines preserved (CFF → TrueType approximates within tolerance)
        assert all(abs(a - b) <= 2 for a, b in zip(bounds[g], want[g])), (g, bounds[g], want[g])


@pytest.mark.verifies("neg:font.outlines")
def test_outline_conversion_negative():
    r = convert("font.outlines", path("font.ttf"), "otf", formats=["ttf"])
    assert r.ok
    r = convert("font.outlines", r.out, "otf", formats=["otf"])
    assert not r.ok and "already has PostScript" in r.error["message"]
