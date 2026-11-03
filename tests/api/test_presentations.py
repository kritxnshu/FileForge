"""Presentations: LibreOffice matrix, slides → images chain, images → PPTX, PDF → PPTX (image slides)."""

from __future__ import annotations

import pytest
from conftest import convert, pairs_of
from fixtures.generate import KNOWN_SENTENCE, path

from engine.validators.docs import pdf_text, pptx_text, validate_document
from engine.validators.images import open_image, validate_image


@pytest.mark.parametrize("src,dst", pairs_of("pres.office"))
def test_office_decks(src, dst):
    r = convert("pres.office", path(f"presentation.{src}"), dst, timeout=240)
    assert r.ok, r.error
    validate_document(r.out, dst, [KNOWN_SENTENCE, "Page 2 marker"])
    if dst == "pdf":
        assert pdf_text(r.out)[0] == 2
    if dst == "pptx":
        assert len(pptx_text(r.out)) == 2


@pytest.mark.verifies("neg:pres.office")
def test_office_decks_corrupt(tmp_path):
    bad = tmp_path / "bad.pptx"
    bad.write_bytes(path("presentation.pptx").read_bytes()[:4000])
    r = convert("pres.office", bad, "pdf", formats=["pptx"], timeout=240)
    assert not r.ok


@pytest.mark.parametrize("src,dst", pairs_of("pres.to_images"))
def test_slides_to_images_chain(src, dst):
    r = convert("pres.to_images", path(f"presentation.{src}"), dst, {"width": 640}, timeout=240)
    assert r.ok, r.error
    assert len(r.outputs) == 2
    for p, _ in r.outputs:
        validate_image(p, dst, color_blocks=False)
        assert open_image(p).width == 640
    # slide 2 has a red background: proves real rendering, not a placeholder
    assert open_image(r.outputs[1][0]).convert("RGB").getpixel((600, 340))[0] > 200
    stages = [e.get("stage", "") for e in r.progress]
    assert any("step 1 of 2" in s for s in stages) and any("Rendering slide 2 of 2" in s for s in stages)


@pytest.mark.verifies("neg:pres.to_images")
def test_slides_to_images_bad_range():
    r = convert("pres.to_images", path("presentation.pptx"), "png", {"slides": "5"}, timeout=240)
    assert not r.ok and "doesn't exist" in r.error["message"]


@pytest.mark.parametrize("src,dst", pairs_of("pres.from_images"))
def test_images_to_pptx(src, dst):
    r = convert("pres.from_images", [path(f"image.{src}"), path("image.png")], "pptx")
    assert r.ok, r.error
    from pptx import Presentation

    prs = Presentation(r.out)
    assert len(prs.slides) == 2
    pics = [sh for sh in prs.slides[0].shapes if sh.shape_type == 13]
    assert len(pics) == 1
    from io import BytesIO

    from PIL import Image

    im = Image.open(BytesIO(pics[0].image.blob)).convert("RGB")
    assert im.getpixel((int(im.width * 0.2), im.height // 2))[0] > 200  # the red block survived


@pytest.mark.verifies("neg:pres.from_images")
def test_images_to_pptx_corrupt():
    r = convert("pres.from_images", [path("truncated.png")], "pptx", formats=["png"])
    assert not r.ok and r.error["code"] == "corrupt_input"


@pytest.mark.verifies("pres.from_pdf:pdf->pptx")
def test_pdf_to_pptx_image_slides():
    r = convert("pres.from_pdf", path("document.pdf"), "pptx", {"dpi": 72})
    assert r.ok, r.error
    from pptx import Presentation

    prs = Presentation(r.out)
    assert len(prs.slides) == 3
    assert all(any(sh.shape_type == 13 for sh in s.shapes) for s in prs.slides)
    assert "Not editable" in prs.slides[0].notes_slide.notes_text_frame.text
    assert any("not editable" in w for w in r.warnings)


@pytest.mark.verifies("neg:pres.from_pdf")
def test_pdf_to_pptx_encrypted():
    r = convert("pres.from_pdf", path("encrypted.pdf"), "pptx")
    assert not r.ok and r.error["code"] == "password_required"
