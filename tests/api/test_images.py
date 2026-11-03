"""Image operations: converter matrix + negative tests."""

from __future__ import annotations

import pytest
from conftest import convert, pairs_of
from fixtures.generate import path

from engine.converters.images.raster import ALPHA_TARGETS
from engine.validators.images import open_image, validate_image

ALPHA_FIXTURES = {"png", "webp", "gif", "tiff", "ico", "avif", "heic"}
LOSSY = {"jpg", "webp", "avif", "heic"}


@pytest.mark.parametrize("src,dst", pairs_of("image.convert"))
def test_image_convert_matrix(src, dst):
    r = convert("image.convert", path(f"image.{src}"), dst)
    assert r.ok, r.error
    expect_alpha = None
    if src in ALPHA_FIXTURES:
        expect_alpha = dst in ALPHA_TARGETS
    validate_image(r.out, dst, expect_alpha=expect_alpha, lossy=bool({src, dst} & LOSSY))
    if src in ALPHA_FIXTURES and dst not in ALPHA_TARGETS:
        assert any("transparen" in n for n in r.notices)


@pytest.mark.verifies("image.convert:gif->webp", "image.convert:webp->gif")
@pytest.mark.parametrize("src,dst", [("gif", "webp"), ("webp", "gif")])
def test_animation_preserved(src, dst):
    r = convert("image.convert", path(f"animated.{src}"), dst)
    assert r.ok, r.error
    im = open_image(r.out)
    assert im.n_frames == 3
    durations = []
    for i in range(3):
        im.seek(i)
        im.load()  # WebP fills per-frame info on load
        durations.append(im.info.get("duration"))
    assert durations == [100, 200, 300]
    assert any("frames" in n for n in r.notices)


@pytest.mark.verifies("image.convert:gif->png")
def test_animation_to_static_uses_first_frame():
    r = convert("image.convert", path("animated.gif"), "png")
    assert r.ok
    im = open_image(r.out)
    assert getattr(im, "n_frames", 1) == 1
    assert im.convert("RGB").getpixel((5, 5)) == (255, 0, 0)
    assert any("first" in n for n in r.notices)


@pytest.mark.verifies("image.convert:jpg->png", "image.convert:heic->jpg")
@pytest.mark.parametrize("name,dst", [("rotated.jpg", "png"), ("rotated.heic", "jpg")])
def test_exif_orientation_applied(name, dst):
    r = convert("image.convert", path(name), dst)
    assert r.ok, r.error
    assert open_image(r.out).size == (32, 64)


@pytest.mark.verifies("image.convert:png->jpg")
def test_background_color_option():
    r = convert("image.convert", path("image.png"), "jpg", {"background": "#00ff00"})
    validate_image(r.out, "jpg", expect_alpha=False, background=(0, 255, 0), lossy=True)


@pytest.mark.verifies("image.convert:png->ico")
def test_ico_sizes():
    r = convert("image.convert", path("image.png"), "ico", {"ico_sizes": [16, 32, 256]})
    assert open_image(r.out).info["sizes"] == {(16, 16), (32, 32), (256, 256)}


@pytest.mark.verifies("image.convert:png->jpg")
def test_quality_changes_size():
    lo = convert("image.convert", path("image.png"), "jpg", {"quality": 10}).out.stat().st_size
    hi = convert("image.convert", path("image.png"), "jpg", {"quality": 100}).out.stat().st_size
    assert lo < hi


# --- negative ---------------------------------------------------------------


@pytest.mark.verifies("neg:image.convert")
def test_truncated_image_fails_cleanly():
    r = convert("image.convert", path("truncated.png"), "jpg", formats=["png"])
    assert not r.ok
    assert r.error["code"] == "corrupt_input"
    assert "damaged" in r.error["message"] or "truncated" in r.error["message"]
    assert not any((r.job_dir / "out").iterdir())


@pytest.mark.verifies("neg:image.convert")
def test_pixel_bomb_rejected():
    r = convert("image.convert", path("bomb.png"), "jpg")
    assert not r.ok
    assert r.error["code"] == "too_many_pixels"
    assert "megapixels" in r.error["message"]


@pytest.mark.verifies("neg:image.convert")
def test_invalid_option_rejected():
    from engine.registry import get

    with pytest.raises(Exception):
        get("image.convert").options.model_validate({"quality": 500})
    with pytest.raises(Exception):
        get("image.convert").options.model_validate({"unknown_option": 1})
