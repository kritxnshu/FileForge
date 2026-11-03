"""Image tools: resize, compress, metadata, SVG rendering, tracing, HEIC output."""

from __future__ import annotations

import pytest
from conftest import convert, pairs_of
from fixtures.generate import KNOWN_SENTENCE, path

from engine.validators.images import open_image, validate_image

LOSSY = {"jpg", "webp", "avif"}


@pytest.mark.parametrize("src,dst", pairs_of("image.resize"))
def test_resize_matrix(src, dst):
    r = convert("image.resize", path(f"image.{src}"), options={"mode": "percent", "percent": 50})
    assert r.ok, r.error
    validate_image(r.out, src, size=(32, 32), lossy=True)


@pytest.mark.verifies("image.resize:png->png", "image.resize:gif->gif")
def test_resize_modes_and_animation():
    r = convert("image.resize", path("image.png"), options={"mode": "fit", "width": 20, "height": 10})
    assert open_image(r.out).size == (10, 10)
    r = convert("image.resize", path("animated.gif"), options={"mode": "width", "width": 16})
    im = open_image(r.out)
    assert im.size == (16, 16) and im.n_frames == 3


@pytest.mark.verifies("neg:image.resize")
def test_resize_rejects_missing_dims_and_huge_output():
    from engine.registry import get

    with pytest.raises(ValueError):
        get("image.resize").options.model_validate({"mode": "width"})
    r = convert("image.resize", path("image.png"), options={"mode": "percent", "percent": 1000})
    assert r.ok  # 640x640 is fine
    r = convert("image.resize", path("image.png"), options={"mode": "exact", "width": 20000, "height": 20000})
    assert not r.ok and r.error["code"] == "too_many_pixels"


@pytest.mark.parametrize("src,dst", pairs_of("image.compress"))
def test_compress_matrix(src, dst):
    r = convert("image.compress", path(f"image.{src}"), options={"quality": 40})
    assert r.ok, r.error
    assert r.out.stat().st_size <= path(f"image.{src}").stat().st_size
    validate_image(r.out, src, lossy=True)


@pytest.mark.verifies("image.compress:jpg->jpg")
def test_compress_never_returns_larger_file():
    # A tiny 64x64 JPG at q95 re-encoded at q100 would grow: we must return the original instead.
    r = convert("image.compress", path("image.jpg"), options={"quality": 100, "strip_metadata": False})
    assert r.ok
    if r.info.get("returned_original"):
        assert r.out.read_bytes() == path("image.jpg").read_bytes()
        assert any("original" in w for w in r.warnings)
    else:
        assert r.out.stat().st_size < path("image.jpg").stat().st_size


@pytest.mark.verifies("neg:image.compress")
def test_compress_corrupt():
    r = convert("image.compress", path("truncated.png"), formats=["png"])
    assert not r.ok and r.error["code"] == "corrupt_input"


@pytest.mark.parametrize("src,dst", pairs_of("image.metadata"))
def test_metadata_matrix(src, dst):
    r = convert("image.metadata", path("rotated.jpg") if src == "jpg" else path(f"image.{src}"),
                options={"strip_metadata": True, **({"dpi": 300} if src in ("jpg", "png", "tiff", "bmp") else {})})
    assert r.ok, r.error
    im = open_image(r.out)
    assert not im.getexif().get(0x0112)
    if src in ("jpg", "png", "tiff", "bmp"):
        assert round(im.info["dpi"][0]) == 300
    if src == "jpg":
        assert im.size == (32, 64)  # orientation baked in before EXIF was dropped
    else:
        validate_image(r.out, src, lossy=src in LOSSY)


@pytest.mark.verifies("neg:image.metadata")
def test_metadata_rejects_animated():
    r = convert("image.metadata", path("animated.webp"))
    assert not r.ok and r.error["code"] == "unsupported_input"


@pytest.mark.parametrize("src,dst", pairs_of("image.svg_render"))
def test_svg_render_matrix(src, dst):
    r = convert("image.svg_render", path("image.svg"), dst)
    assert r.ok, r.error
    if dst == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(r.out)
        assert len(reader.pages) == 1
        assert KNOWN_SENTENCE[:9] in reader.pages[0].extract_text()
        assert round(float(reader.pages[0].mediabox.width)) in (48, 64)  # 64 CSS px = 48 pt
    else:
        validate_image(r.out, dst, size=(64, 64), lossy=dst != "png", expect_alpha=dst != "jpg")


@pytest.mark.verifies("image.svg_render:svg->png")
def test_svg_dpi_scales_output():
    r = convert("image.svg_render", path("image.svg"), "png", {"dpi": 192})
    assert open_image(r.out).size == (128, 128)


@pytest.mark.verifies("neg:image.svg_render")
def test_svg_with_dtd_rejected(tmp_path):
    p = tmp_path / "x.svg"
    p.write_text('<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>')
    r = convert("image.svg_render", p, "png", formats=["svg"])
    assert not r.ok and r.error["code"] == "corrupt_input"


@pytest.mark.parametrize("src,dst", pairs_of("image.trace"))
def test_trace_matrix(src, dst):
    r = convert("image.trace", path(f"image.{src}"), "svg")
    assert r.ok, r.error
    from defusedxml import ElementTree as DET

    root = DET.parse(r.out).getroot()
    assert root.tag.endswith("svg")
    paths = [e for e in root.iter() if e.tag.endswith("path")]
    assert len(paths) >= 2  # real traced shapes, not an embedded bitmap
    assert not any(e.tag.endswith("image") for e in root.iter())
    # trace back: render the SVG and check the colour blocks survived
    out = convert("image.svg_render", r.out, "png", formats=["svg"])
    validate_image(out.out, "png", lossy=True)


@pytest.mark.verifies("neg:image.trace")
def test_trace_rejects_corrupt():
    r = convert("image.trace", path("truncated.png"), "svg", formats=["png"])
    assert not r.ok


@pytest.mark.parametrize("src,dst", pairs_of("image.to_heic"))
def test_to_heic_matrix(src, dst):
    r = convert("image.to_heic", path(f"image.{src}"), "heic")
    assert r.ok, r.error
    validate_image(r.out, "heic", lossy=True)


@pytest.mark.verifies("neg:image.to_heic")
def test_to_heic_corrupt():
    r = convert("image.to_heic", path("truncated.png"), "heic", formats=["png"])
    assert not r.ok and r.error["code"] == "corrupt_input"
