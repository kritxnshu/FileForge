"""The PDF tools section: organize, crop, resize, pages per sheet, page numbers, repair, extract images, metadata,
flatten, edit, sign, redact, forms (export, fill, create), compare, PDF/A, scan clean-up.

Every result is checked with a parser the tool didn't use to write it (pypdf, pikepdf, a PDFium render
checked pixel by pixel, Pillow), including on rotated pages, where placement mistakes would show.
"""

from __future__ import annotations

import base64
import json

import pytest
from conftest import convert
from fixtures.generate import KNOWN_SENTENCE, path

from engine import registry


def text_of(p) -> list[str]:
    from pypdf import PdfReader

    return [(pg.extract_text() or "") for pg in PdfReader(str(p)).pages]


def render(p, page: int = 0, scale: float = 1.0):
    import pypdfium2 as pdfium

    return pdfium.PdfDocument(str(p))[page].render(scale=scale).to_pil().convert("RGB")


def is_red(px) -> bool:
    r, g, b = px
    return r > 180 and g < 90 and b < 90


def data_url(name: str, mime: str = "image/png") -> str:
    return f"data:{mime};base64," + base64.b64encode(path(name).read_bytes()).decode()


def rotated_pdf(tmp_path, angle: int = 90):
    from pypdf import PdfReader, PdfWriter

    w = PdfWriter()
    for pg in PdfReader(str(path("document.pdf"))).pages:
        pg.rotate(angle)
        w.add_page(pg)
    out = tmp_path / f"rotated-{angle}.pdf"
    with out.open("wb") as f:
        w.write(f)
    return out


def needs(op_id: str):
    op = registry.get(op_id)
    missing = registry.missing_engines(op, *op.pairs()[0])
    return pytest.mark.skipif(bool(missing), reason=f"engine missing: {missing}")


# ---------------------------------------------------------------------------
# organize


@pytest.mark.verifies("pdf.organize:pdf->pdf")
def test_organize_reorders_rotates_duplicates_and_inserts_blank_pages():
    from pypdf import PdfReader

    r = convert("pdf.organize", path("document.pdf"), options={"pages": [
        {"source": 3}, {"source": None}, {"source": 1, "rotate": 90}, {"source": 1}]})
    assert r.ok, r.error
    pages = PdfReader(str(r.out)).pages
    texts = text_of(r.out)
    assert len(pages) == 4
    assert "Page 3 marker text" in texts[0]
    assert texts[1].strip() == ""
    assert "Quarterly Report" in texts[2] and pages[2].rotation == 90
    assert "Quarterly Report" in texts[3] and pages[3].rotation == 0  # the duplicate is independent
    assert r.info["removed"] == 1 and r.info["blank_pages"] == 1


@pytest.mark.verifies("neg:pdf.organize")
def test_organize_rejects_empty_or_missing_pages():
    r = convert("pdf.organize", path("document.pdf"), options={"pages": []})
    assert not r.ok and r.error["code"] == "invalid_option"
    r = convert("pdf.organize", path("document.pdf"), options={"pages": [{"source": 9}]})
    assert not r.ok and "Page 9 doesn't exist" in r.error["message"]
    r = convert("pdf.organize", path("document.pdf"), options={"pages": [{"source": None}]})
    assert not r.ok and "at least one page" in r.error["message"]


# ---------------------------------------------------------------------------
# crop, resize, pages per sheet


@pytest.mark.verifies("pdf.crop:pdf->pdf")
def test_crop_keeps_the_drawn_area_and_trims_margins(tmp_path):
    from pypdf import PdfReader

    r = convert("pdf.crop", path("document.pdf"), options={"area": {"x": 0.1, "y": 0.05, "w": 0.6, "h": 0.3}, "pages": "1"})
    assert r.ok, r.error
    pages = PdfReader(str(r.out)).pages
    assert float(pages[0].cropbox.width) == pytest.approx(0.6 * 595.27, abs=1)
    assert float(pages[0].cropbox.height) == pytest.approx(0.3 * 841.89, abs=1)
    assert float(pages[1].cropbox.height) == pytest.approx(841.89, abs=1)  # only page 1
    im = render(r.out)
    assert im.width / im.height == pytest.approx(0.6 * 595.27 / (0.3 * 841.89), rel=0.02)
    # the area is in display coordinates, so it works on rotated pages too
    rot = rotated_pdf(tmp_path, 90)
    r = convert("pdf.crop", rot, options={"area": {"x": 0, "y": 0, "w": 0.5, "h": 1}})
    assert r.ok, r.error
    im = render(r.out)
    assert im.width == pytest.approx(841.89 / 2, abs=2) and im.height == pytest.approx(595.27, abs=2)
    # margins
    r = convert("pdf.crop", path("document.pdf"), options={"margin_top_mm": 20, "margin_left_mm": 10})
    assert r.ok, r.error
    box = PdfReader(str(r.out)).pages[0].cropbox
    assert float(box.height) == pytest.approx(841.89 - 20 * 72 / 25.4, abs=1)
    assert float(box.width) == pytest.approx(595.27 - 10 * 72 / 25.4, abs=1)


@pytest.mark.verifies("neg:pdf.crop")
def test_crop_needs_an_area_and_a_sensible_size():
    r = convert("pdf.crop", path("document.pdf"), options={})
    assert not r.ok and r.error["code"] == "invalid_option"
    r = convert("pdf.crop", path("document.pdf"), options={"area": {"x": 0.5, "y": 0.5, "w": 0.001, "h": 0.001}})
    assert not r.ok and "smaller than 6 mm" in r.error["message"]


@pytest.mark.verifies("pdf.resize:pdf->pdf")
def test_resize_to_letter_and_landscape():
    from pypdf import PdfReader

    r = convert("pdf.resize", path("document.pdf"), options={"size": "Letter"})
    assert r.ok, r.error
    pg = PdfReader(str(r.out)).pages[0]
    assert (round(float(pg.mediabox.width)), round(float(pg.mediabox.height))) == (612, 792)
    assert KNOWN_SENTENCE in text_of(r.out)[0]
    r = convert("pdf.resize", path("document.pdf"), options={"size": "A5", "orientation": "landscape", "margin_mm": 10})
    assert r.ok, r.error
    pg = PdfReader(str(r.out)).pages[0]
    assert float(pg.mediabox.width) > float(pg.mediabox.height)


@pytest.mark.verifies("neg:pdf.resize")
def test_resize_encrypted_needs_password():
    r = convert("pdf.resize", path("encrypted.pdf"), options={})
    assert not r.ok and r.error["code"] == "password_required"


@pytest.mark.verifies("pdf.nup:pdf->pdf")
def test_pages_per_sheet():
    from pypdf import PdfReader

    r = convert("pdf.nup", path("document.pdf"), options={"per_sheet": 2, "border": True})
    assert r.ok, r.error
    pages = PdfReader(str(r.out)).pages
    assert len(pages) == 2  # 3 pages, 2 per sheet
    assert float(pages[0].mediabox.width) > float(pages[0].mediabox.height)  # 2-up is landscape
    t = text_of(r.out)
    assert "Quarterly Report" in t[0] and "Page 2 marker text" in t[0] and "Page 3 marker text" in t[1]
    r = convert("pdf.nup", path("document.pdf"), options={"per_sheet": 4})
    assert r.ok and len(PdfReader(str(r.out)).pages) == 1


@pytest.mark.verifies("neg:pdf.nup")
def test_pages_per_sheet_wrong_password():
    r = convert("pdf.nup", path("encrypted.pdf"), options={"password": "nope"})
    assert not r.ok and r.error["code"] == "wrong_password"


# ---------------------------------------------------------------------------
# page numbers, headers and footers


@pytest.mark.verifies("pdf.page_numbers:pdf->pdf")
def test_page_numbers_text_position_and_unicode(tmp_path):
    r = convert("pdf.page_numbers", path("document.pdf"), options={"text": "Page {n} of {total}", "position": "bottom-right"})
    assert r.ok, r.error
    t = text_of(r.out)
    assert [f"Page {i} of 3" in t[i - 1] for i in (1, 2, 3)] == [True] * 3
    # skip the cover, start at 1; and a footer with non-Latin text
    r = convert("pdf.page_numbers", path("document.pdf"), options={"text": "Σελίδα {n}", "pages": "2-last"})
    assert r.ok, r.error
    t = text_of(r.out)
    assert "Σελίδα" not in t[0] and "Σελίδα 1" in t[1] and "Σελίδα 2" in t[2]
    # rotated pages: the number lands at the bottom right as displayed
    rot = rotated_pdf(tmp_path, 90)
    r = convert("pdf.page_numbers", rot, options={"text": "████", "position": "bottom-right", "size": 20, "color": "#ff0000"})
    assert r.ok, r.error
    im = render(r.out)
    w, h = im.size
    red = [(x, y) for x in range(0, w, 3) for y in range(0, h, 3) if is_red(im.getpixel((x, y)))]
    assert red, "no number drawn"
    assert min(x for x, _ in red) > w * 0.6 and min(y for _, y in red) > h * 0.8


@pytest.mark.verifies("neg:pdf.page_numbers")
def test_page_numbers_bad_range():
    r = convert("pdf.page_numbers", path("document.pdf"), options={"pages": "7"})
    assert not r.ok and "Page 7 doesn't exist" in r.error["message"]


# ---------------------------------------------------------------------------
# repair


@pytest.mark.verifies("pdf.repair:pdf->pdf")
def test_repair_rebuilds_a_broken_xref():
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    with pytest.raises(PdfReadError):
        PdfReader(str(path("broken-xref.pdf")), strict=True).pages[0]
    r = convert("pdf.repair", path("broken-xref.pdf"), formats=["pdf"])
    assert r.ok, r.error
    fixed = PdfReader(str(r.out), strict=True)
    assert len(fixed.pages) == 3 and KNOWN_SENTENCE in fixed.pages[0].extract_text()
    assert r.info["problems_fixed"] >= 1


@pytest.mark.verifies("neg:pdf.repair")
def test_repair_gives_up_cleanly_on_garbage():
    r = convert("pdf.repair", path("corrupt.pdf"), formats=["pdf"])
    assert not r.ok and r.error["code"] == "corrupt_input"


# ---------------------------------------------------------------------------
# extract images


@pytest.mark.verifies("pdf.extract_images:pdf->png")
def test_extract_images_png_and_jpeg_byte_for_byte(tmp_path):
    import img2pdf
    from PIL import Image

    r = convert("pdf.extract_images", path("photos.pdf"), "png")
    assert r.ok, r.error
    with Image.open(r.outputs[0][0]) as im:
        assert im.size == (2400, 1800)
    # JPEGs come out exactly as embedded
    src = tmp_path / "jpeg.pdf"
    src.write_bytes(img2pdf.convert(path("image.jpg").read_bytes()))
    r = convert("pdf.extract_images", src, "png", options={"min_size": 1})
    assert r.ok, r.error
    out, fmt = r.outputs[0]
    assert fmt == "jpg" and out.read_bytes() == path("image.jpg").read_bytes()


@pytest.mark.verifies("neg:pdf.extract_images")
def test_extract_images_none_found():
    r = convert("pdf.extract_images", path("document.pdf"), "png")
    assert not r.ok and r.error["code"] == "no_images" and "PDF to JPG" in r.error["message"]


# ---------------------------------------------------------------------------
# metadata and flatten


@pytest.mark.verifies("pdf.metadata:pdf->pdf")
def test_metadata_edit_and_remove():
    import pikepdf

    r = convert("pdf.metadata", path("document.pdf"), options={"title": "Annual review", "author": "Ada Lovelace"})
    assert r.ok, r.error
    with pikepdf.open(r.out) as pdf:
        assert str(pdf.docinfo["/Title"]) == "Annual review" and str(pdf.docinfo["/Author"]) == "Ada Lovelace"
        assert pdf.open_metadata()["dc:title"] == "Annual review"
    r2 = convert("pdf.metadata", r.out, options={"mode": "remove"}, formats=["pdf"])
    assert r2.ok, r2.error
    with pikepdf.open(r2.out) as pdf:
        assert len(pdf.docinfo.keys()) == 0 and "/Metadata" not in pdf.Root
    assert "Annual review" not in r2.out.read_bytes().decode("latin-1")


@pytest.mark.verifies("neg:pdf.metadata")
def test_metadata_needs_something_to_change():
    r = convert("pdf.metadata", path("document.pdf"), options={"mode": "edit"})
    assert not r.ok and r.error["code"] == "invalid_option"


@pytest.mark.verifies("pdf.flatten:pdf->pdf")
def test_flatten_form():
    from pypdf import PdfReader

    filled = convert("pdf.fill_form", path("form.pdf"), options={"values": {"full_name": "Grace Hopper"}})
    assert filled.ok, filled.error
    r = convert("pdf.flatten", filled.out, formats=["pdf"])
    assert r.ok, r.error
    rd = PdfReader(str(r.out))
    assert not rd.get_fields() and not rd.pages[0].get("/Annots")
    assert "Grace Hopper" in rd.pages[0].extract_text()


@pytest.mark.verifies("neg:pdf.flatten")
def test_flatten_nothing_to_do():
    r = convert("pdf.flatten", path("document.pdf"))
    assert not r.ok and r.error["code"] == "nothing_to_flatten"


# ---------------------------------------------------------------------------
# edit and sign


@pytest.mark.verifies("pdf.edit:pdf->pdf")
def test_edit_draws_every_object_type_where_placed(tmp_path):
    import pikepdf

    objs = [
        {"type": "text", "page": 1, "x": 0.1, "y": 0.03, "text": "Reviewed by Ada\nSecond line", "size": 16},
        {"type": "text", "page": 1, "x": 0.1, "y": 0.9, "text": "Zoë — Ελληνικά", "size": 12},
        {"type": "image", "page": 1, "x": 0.7, "y": 0.05, "w": 0.2, "h": 0.1, "data": data_url("image.png")},
        {"type": "rect", "page": 2, "x": 0.6, "y": 0.6, "w": 0.2, "h": 0.1, "fill": "#ff0000", "stroke": None},
        {"type": "ellipse", "page": 2, "x": 0.1, "y": 0.7, "w": 0.2, "h": 0.1},
        {"type": "highlight", "page": 2, "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.05},
        {"type": "whiteout", "page": 3, "x": 0.0, "y": 0.0, "w": 1, "h": 0.2},
        {"type": "arrow", "page": 2, "x1": 0.2, "y1": 0.4, "x2": 0.5, "y2": 0.45},
        {"type": "path", "page": 2, "points": [[0.1, 0.9], [0.2, 0.92], [0.3, 0.9]], "color": "#ff0000", "width": 6},
    ]
    r = convert("pdf.edit", path("document.pdf"), options={"objects": objs})
    assert r.ok, r.error
    t = text_of(r.out)
    assert "Reviewed by Ada" in t[0] and "Second line" in t[0] and "Ελληνικά" in t[0]
    with pikepdf.open(r.out) as pdf:
        assert len(pdf.pages[0].images) >= 1
    im = render(r.out, 1)
    assert is_red(im.getpixel((int(0.7 * im.width), int(0.65 * im.height))))  # rect centre
    assert is_red(im.getpixel((int(0.2 * im.width), int(0.92 * im.height))))  # freehand stroke
    band = render(r.out, 2).crop((0, 0, 595, int(841 * 0.18)))  # white-out covers the top of page 3 when viewed
    assert band.getextrema() == ((255, 255), (255, 255), (255, 255))
    # rotated page: a box drawn at the top-left as displayed is at the top-left of the render
    rot = rotated_pdf(tmp_path, 90)
    r = convert("pdf.edit", rot, options={"objects": [
        {"type": "rect", "page": 1, "x": 0.05, "y": 0.05, "w": 0.2, "h": 0.15, "fill": "#ff0000", "stroke": None}]})
    assert r.ok, r.error
    im = render(r.out)
    assert im.width > im.height
    assert is_red(im.getpixel((int(0.15 * im.width), int(0.12 * im.height))))
    assert not is_red(im.getpixel((int(0.85 * im.width), int(0.12 * im.height))))


@pytest.mark.verifies("neg:pdf.edit")
def test_edit_rejects_empty_missing_pages_and_bad_images():
    r = convert("pdf.edit", path("document.pdf"), options={"objects": []})
    assert not r.ok and r.error["code"] == "invalid_option"
    r = convert("pdf.edit", path("document.pdf"), options={"objects": [{"type": "text", "page": 9, "x": 0, "y": 0, "text": "x"}]})
    assert not r.ok and "Page 9 doesn't exist" in r.error["message"]
    r = convert("pdf.edit", path("document.pdf"), options={"objects": [
        {"type": "image", "page": 1, "x": 0, "y": 0, "w": 0.1, "h": 0.1, "data": "data:image/png;base64,bm90IGFuIGltYWdl"}]})
    assert not r.ok and "couldn't be read" in r.error["message"]


@pytest.mark.verifies("pdf.sign:pdf->pdf")
def test_sign_places_signature_and_date():
    import pikepdf

    r = convert("pdf.sign", path("document.pdf"), options={"objects": [
        {"type": "image", "page": 3, "x": 0.55, "y": 0.8, "w": 0.3, "h": 0.08, "data": data_url("image.png")},
        {"type": "text", "page": 3, "x": 0.55, "y": 0.9, "text": "3 November 2026", "size": 10}]})
    assert r.ok, r.error
    with pikepdf.open(r.out) as pdf:
        assert len(pdf.pages[2].images) == 1 and len(pdf.pages[0].images) == 0
    assert "3 November 2026" in text_of(r.out)[2]
    assert any("visual signature" in n for n in r.notices)


@pytest.mark.verifies("neg:pdf.sign")
def test_sign_needs_a_signature():
    r = convert("pdf.sign", path("document.pdf"), options={"objects": [{"type": "text", "page": 1, "x": 0, "y": 0, "text": "x"}]})
    assert not r.ok and "signature" in r.error["message"]


# ---------------------------------------------------------------------------
# redact


@pytest.mark.verifies("pdf.redact:pdf->pdf")
def test_redact_removes_words_and_areas_from_the_file():
    r = convert("pdf.redact", path("document.pdf"), options={
        "search": "quick brown fox\nzebra", "areas": [{"page": 3, "x": 0, "y": 0, "w": 1, "h": 0.2}]})
    assert r.ok, r.error
    t = text_of(r.out)
    assert len(t) == 3
    joined = " ".join(t).lower()
    assert "quick brown" not in joined and "page 3 marker" not in joined
    assert "Page 2 marker text" in t[1]  # untouched pages keep their text
    assert any("zebra" in w for w in r.warnings)
    assert r.info["pages_redacted"] == 2
    # the sentence's place on page 1 is now black
    im = render(r.out, 0)
    dark = sum(1 for x in range(0, im.width, 4) for y in range(0, int(im.height * 0.25), 4) if sum(im.getpixel((x, y))) < 60)
    assert dark > 50


@pytest.mark.verifies("neg:pdf.redact")
def test_redact_needs_something_found():
    r = convert("pdf.redact", path("document.pdf"), options={"search": "zebra"})
    assert not r.ok and r.error["code"] == "not_found" and "OCR" in r.error["message"]
    r = convert("pdf.redact", path("document.pdf"), options={})
    assert not r.ok and r.error["code"] == "invalid_option"


# ---------------------------------------------------------------------------
# forms


@pytest.mark.verifies("pdf.form_data:pdf->json")
def test_form_data_lists_fields_with_types_and_positions():
    r = convert("pdf.form_data", path("form.pdf"), "json")
    assert r.ok, r.error
    fields = {f["name"]: f for f in json.loads(r.out.read_text())["fields"]}
    assert {k: v["type"] for k, v in fields.items()} == {"full_name": "text", "subscribe": "checkbox",
                                                         "country": "choice", "plan": "radio"}
    assert fields["country"]["options"] == ["India", "France", "Japan"] and fields["country"]["value"] == "India"
    assert sorted(fields["plan"]["options"]) == ["basic", "pro"]
    w = fields["full_name"]["widgets"][0]
    assert w["page"] == 1 and w["x"] == pytest.approx(160 / 595.27, abs=0.002) and w["y"] == pytest.approx(1 - 750 / 841.89, abs=0.002)


@pytest.mark.verifies("neg:pdf.form_data")
def test_form_data_no_form():
    r = convert("pdf.form_data", path("document.pdf"), "json")
    assert not r.ok and r.error["code"] == "no_form"


@pytest.mark.verifies("pdf.fill_form:pdf->pdf")
def test_fill_form_every_field_type_and_flatten():
    from pypdf import PdfReader

    values = {"full_name": "Ada Lovelace", "subscribe": True, "country": "Japan", "plan": "pro", "nonexistent": "x"}
    r = convert("pdf.fill_form", path("form.pdf"), options={"values": values})
    assert r.ok, r.error
    f = PdfReader(str(r.out)).get_fields()
    assert f["full_name"]["/V"] == "Ada Lovelace" and f["country"]["/V"] == "Japan"
    assert str(f["subscribe"]["/V"]) != "/Off" and str(f["plan"]["/V"]) == "/pro"
    assert any("nonexistent" in w for w in r.warnings)
    r = convert("pdf.fill_form", path("form.pdf"), options={"values": values, "flatten": True})
    assert r.ok, r.error
    rd = PdfReader(str(r.out))
    assert not rd.get_fields() and "Ada Lovelace" in rd.pages[0].extract_text() and "Japan" in rd.pages[0].extract_text()


@pytest.mark.verifies("neg:pdf.fill_form")
def test_fill_form_rejects_bad_choices_and_non_forms():
    r = convert("pdf.fill_form", path("form.pdf"), options={"values": {"country": "Mars"}})
    assert not r.ok and "Mars" in r.error["message"]
    r = convert("pdf.fill_form", path("document.pdf"), options={"values": {"a": "b"}})
    assert not r.ok and r.error["code"] == "no_form"


@pytest.mark.verifies("pdf.add_fields:pdf->pdf")
def test_create_form_then_fill_it(tmp_path):
    from pypdf import PdfReader

    fields = [
        {"type": "text", "page": 1, "x": 0.1, "y": 0.5, "w": 0.4, "h": 0.03, "name": "email"},
        {"type": "checkbox", "page": 1, "x": 0.1, "y": 0.55, "w": 0.03, "h": 0.02, "name": "agree"},
        {"type": "dropdown", "page": 2, "x": 0.1, "y": 0.3, "w": 0.3, "h": 0.03, "name": "size", "options": ["S", "M", "L"]},
    ]
    r = convert("pdf.add_fields", path("document.pdf"), options={"fields": fields})
    assert r.ok, r.error
    data = convert("pdf.form_data", r.out, "json", formats=["pdf"])
    assert data.ok, data.error
    got = {f["name"]: f for f in json.loads(data.out.read_text())["fields"]}
    assert {k: v["type"] for k, v in got.items()} == {"email": "text", "agree": "checkbox", "size": "choice"}
    w = got["email"]["widgets"][0]
    assert (w["page"], w["x"], w["y"], w["w"]) == (1, pytest.approx(0.1, abs=0.002), pytest.approx(0.5, abs=0.002), pytest.approx(0.4, abs=0.002))
    assert got["size"]["widgets"][0]["page"] == 2 and got["size"]["options"] == ["S", "M", "L"]
    filled = convert("pdf.fill_form", r.out, options={"values": {"email": "ada@example.com", "agree": True, "size": "M"},
                                                       "flatten": True}, formats=["pdf"])
    assert filled.ok, filled.error
    t = text_of(filled.out)
    assert "ada@example.com" in t[0] and "M" in t[1]
    assert KNOWN_SENTENCE in t[0]
    # on a rotated page the field is placed where it was drawn, as displayed
    rot = rotated_pdf(tmp_path)
    r = convert("pdf.add_fields", rot, options={"fields": [fields[0]]})
    assert r.ok, r.error
    data = convert("pdf.form_data", r.out, "json", formats=["pdf"])
    w = json.loads(data.out.read_text())["fields"][0]["widgets"][0]
    assert (w["x"], w["y"], w["w"]) == (pytest.approx(0.1, abs=0.002), pytest.approx(0.5, abs=0.002), pytest.approx(0.4, abs=0.002))
    assert len(PdfReader(str(r.out)).pages) == 3


@pytest.mark.verifies("neg:pdf.add_fields")
def test_create_form_rejects_duplicates_and_empty_dropdowns():
    f = {"type": "text", "page": 1, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.03, "name": "a"}
    r = convert("pdf.add_fields", path("document.pdf"), options={"fields": [f, f]})
    assert not r.ok and "Two fields" in r.error["message"]
    r = convert("pdf.add_fields", path("document.pdf"), options={"fields": [{**f, "type": "dropdown", "options": []}]})
    assert not r.ok and "choice" in r.error["message"]


# ---------------------------------------------------------------------------
# compare


@pytest.mark.verifies("pdf.compare:pdf->pdf")
def test_compare_reports_changed_pages_and_words():
    r = convert("pdf.compare", [path("document.pdf"), path("document-changed.pdf")], "pdf",
                names=["v1.pdf", "v2.pdf"])
    assert r.ok, r.error
    assert r.info["changed_pages"] == [2]
    t = text_of(r.out)
    summary = t[0]
    assert "1 of 3 pages differ" in summary and "v1.pdf" in summary and "v2.pdf" in summary
    assert "Removed:" in summary and "marker" in summary and "Added:" in summary and "revised" in summary
    assert len(t) == 2  # summary + one side-by-side page
    same = convert("pdf.compare", [path("document.pdf"), path("document.pdf")], "pdf")
    assert same.ok and same.info["changed_pages"] == [] and any("No differences" in n for n in same.notices)


@pytest.mark.verifies("neg:pdf.compare")
def test_compare_needs_two_pdfs():
    r = convert("pdf.compare", [path("document.pdf")], "pdf")
    assert not r.ok and r.error["code"] == "invalid_input"


# ---------------------------------------------------------------------------
# PDF/A (Ghostscript; AGPL flag only hides it in the UI)


@needs("pdf.to_pdfa")
@pytest.mark.verifies("pdf.to_pdfa:pdf->pdf")
def test_to_pdfa_marks_identification_output_intent_and_embeds_fonts():
    import pikepdf

    r = convert("pdf.to_pdfa", path("document.pdf"), timeout=180)
    assert r.ok, r.error
    with pikepdf.open(r.out) as pdf:
        meta = pdf.open_metadata()
        assert meta["pdfaid:part"] == "2" and meta["pdfaid:conformance"] == "B"
        assert len(pdf.Root.OutputIntents) == 1
        for page in pdf.pages:
            for _, font in page.resources.get("/Font", {}).items():
                desc = font.get("/FontDescriptor") or font.get("/DescendantFonts", [{}])[0].get("/FontDescriptor")
                assert desc is not None and any(k in desc for k in ("/FontFile", "/FontFile2", "/FontFile3"))
    assert KNOWN_SENTENCE in text_of(r.out)[0]


@needs("pdf.to_pdfa")
def test_to_pdfa_of_an_encrypted_pdf_with_its_password():
    import pikepdf

    # the job decrypts in-process, so the password never reaches Ghostscript's command line
    r = convert("pdf.to_pdfa", path("encrypted.pdf"), options={"password": "secret"}, timeout=180)
    assert r.ok, r.error
    with pikepdf.open(r.out) as pdf:  # no password needed: PDF/A forbids encryption
        assert not pdf.is_encrypted and pdf.open_metadata()["pdfaid:part"] == "2"


@needs("pdf.to_pdfa")
@pytest.mark.verifies("neg:pdf.to_pdfa")
def test_to_pdfa_wrong_password():
    r = convert("pdf.to_pdfa", path("encrypted.pdf"), options={"password": "nope"}, timeout=180)
    assert not r.ok


# ---------------------------------------------------------------------------
# scan clean-up (images → PDF)


@pytest.mark.verifies("pdf.from_images:jpg->pdf")
def test_scan_cleanup_makes_grayscale_pages():
    import pikepdf
    from pikepdf import PdfImage

    for mode, colorspace in (("document", "/DeviceGray"), ("bw", "/DeviceGray")):
        r = convert("pdf.from_images", path("image.jpg"), "pdf", options={"enhance": mode})
        assert r.ok, r.error
        with pikepdf.open(r.out) as pdf:
            img = PdfImage(next(iter(pdf.pages[0].images.values())))
            assert str(img.colorspace) == colorspace
            if mode == "bw":
                assert img.bits_per_component == 1
