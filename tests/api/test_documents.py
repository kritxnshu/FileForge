"""Documents & PDF: converter matrix + negative tests."""

from __future__ import annotations

import pytest
from conftest import convert, pairs_of
from fixtures.generate import KNOWN_SENTENCE, path

from engine.validators.docs import docx_text, pdf_text, validate_document, validate_pdf
from engine.validators.images import open_image, validate_image

S = KNOWN_SENTENCE


# --- LibreOffice -----------------------------------------------------------


@pytest.mark.parametrize("src,dst", pairs_of("doc.office"))
def test_office_matrix(src, dst):
    r = convert("doc.office", path(f"document.{src}"), dst, timeout=180)
    assert r.ok, r.error
    validate_document(r.out, dst, [S])
    if dst in ("docx", "odt", "pdf") and src != "txt":
        # the table survived too
        text = docx_text(r.out) if dst == "docx" else pdf_text(r.out)[1] if dst == "pdf" else None
        if text is not None:
            assert "Banana" in text and "12" in text


@pytest.mark.verifies("neg:doc.office")
def test_office_corrupt_fails_cleanly(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(path("document.docx").read_bytes()[:3000])
    r = convert("doc.office", bad, "pdf", formats=["docx"], timeout=180)
    assert not r.ok and r.error["code"] in ("engine_error", "corrupt_input")


# --- Pandoc ----------------------------------------------------------------


@pytest.mark.parametrize("src,dst", pairs_of("doc.pandoc"))
def test_pandoc_matrix(src, dst):
    r = convert("doc.pandoc", path(f"document.{src}"), dst)
    assert r.ok, r.error
    validate_document(r.out, dst, [S, "Quarterly Report"])
    if dst in ("docx",):
        assert "Banana" in docx_text(r.out)


@pytest.mark.verifies("neg:doc.pandoc")
def test_pandoc_never_fetches(tmp_path):
    from test_security import Canary

    c = Canary()
    try:
        p = tmp_path / "x.html"
        p.write_text(f'<html><body><p>{S}</p><img src="{c.url}/x.png"><img src="file:///etc/hosts"></body></html>')
        r = convert("doc.pandoc", p, "docx", formats=["html"])
        assert r.ok
        assert c.hits == []
    finally:
        c.close()


# --- HTML → PDF --------------------------------------------------------------


@pytest.mark.parametrize("src,dst", pairs_of("doc.html_to_pdf"))
def test_html_to_pdf_matrix(src, dst):
    r = convert("doc.html_to_pdf", path(f"document.{src}"), "pdf", {"page_size": "Letter", "margin_mm": 10})
    assert r.ok, r.error
    validate_pdf(r.out, pages=1, contains=[S, "Banana"])
    from pypdf import PdfReader

    box = PdfReader(r.out).pages[0].mediabox
    assert (round(float(box.width)), round(float(box.height))) == (612, 792)


@pytest.mark.verifies("neg:doc.html_to_pdf")
def test_html_to_pdf_blocks_ssrf_and_js(tmp_path):
    from test_security import Canary

    c = Canary()
    try:
        p = tmp_path / "evil.html"
        p.write_text(f"""<html><head><link rel=stylesheet href="{c.url}/s.css"></head><body>
            <p id=t>{S}</p><img src="{c.url}/i.png"><img src="http://169.254.169.254/latest/meta-data/">
            <iframe src="file:///etc/passwd"></iframe>
            <script>document.getElementById('t').textContent='JS RAN'; fetch('{c.url}/js')</script></body></html>""")
        r = convert("doc.html_to_pdf", p, "pdf", formats=["html"])
        assert r.ok, r.error
        assert c.hits == []
        _, text = pdf_text(r.out)
        assert S in text and "JS RAN" not in text and "root:" not in text
        assert any("not loaded" in n for n in r.notices)
    finally:
        c.close()


# --- PDF → images ------------------------------------------------------------


@pytest.mark.parametrize("src,dst", pairs_of("pdf.to_images"))
def test_pdf_to_images_matrix(src, dst):
    r = convert("pdf.to_images", path("document.pdf"), dst, {"dpi": 72})
    assert r.ok, r.error
    assert len(r.outputs) == 3
    for p, fmt in r.outputs:
        validate_image(p, dst, color_blocks=False)
        w, h = open_image(p).size
        assert abs(w - 595) <= 1 and abs(h - 842) <= 1  # A4 at 72 dpi (595.28 × 841.89 pt)
    assert [e for e in r.progress if e.get("total") == 3]  # real page-by-page progress


@pytest.mark.verifies("pdf.to_images:pdf->png")
def test_pdf_to_images_range_and_dpi():
    r = convert("pdf.to_images", path("document.pdf"), "png", {"dpi": 144, "pages": "2-3"})
    assert [p.name for p, _ in r.outputs] == ["page-002.png", "page-003.png"]
    w, h = open_image(r.outputs[0][0]).size
    assert abs(w - 1191) <= 1 and abs(h - 1684) <= 1


@pytest.mark.verifies("neg:pdf.to_images")
@pytest.mark.parametrize("name,opts,code", [
    ("encrypted.pdf", {}, "password_required"),
    ("encrypted.pdf", {"password": "nope"}, "wrong_password"),
    ("corrupt.pdf", {}, "corrupt_input"),
    ("document.pdf", {"pages": "9"}, "invalid_option"),
])
def test_pdf_to_images_negative(name, opts, code):
    r = convert("pdf.to_images", path(name), "png", opts, formats=["pdf"])
    assert not r.ok and r.error["code"] == code, r.error
    if code == "password_required":
        assert "password-protected" in r.error["message"] and "enter" in r.error["message"]


@pytest.mark.verifies("pdf.to_images:pdf->jpg")
def test_pdf_to_images_with_password():
    r = convert("pdf.to_images", path("encrypted.pdf"), "jpg", {"password": "secret", "dpi": 50})
    assert r.ok and len(r.outputs) == 3


# --- images → PDF ------------------------------------------------------------


@pytest.mark.parametrize("src,dst", pairs_of("pdf.from_images"))
def test_images_to_pdf_matrix(src, dst):
    r = convert("pdf.from_images", path(f"image.{src}"), "pdf")
    assert r.ok, r.error
    validate_pdf(r.out, pages=1)
    # render the page back and check the colour blocks
    back = convert("pdf.to_images", r.out, "png", {"dpi": 72}, formats=["pdf"])
    validate_image(back.out, "png", lossy=True)


@pytest.mark.verifies("pdf.from_images:jpg->pdf", "pdf.from_images:heic->pdf")
def test_images_to_pdf_multi_and_layout():
    r = convert("pdf.from_images", [path("image.jpg"), path("image.png"), path("rotated.heic")], "pdf",
                {"page_size": "A4", "margin_mm": 10})
    assert r.ok, r.error
    validate_pdf(r.out, pages=3)
    from pypdf import PdfReader

    pages = PdfReader(r.out).pages
    assert round(float(pages[0].mediabox.width)) == 595
    # JPEG embedded losslessly (DCT stream, byte-identical)
    import pikepdf

    with pikepdf.open(r.out) as pdf:
        img = next(iter(pdf.pages[0].images.values()))
        assert img.Filter == "/DCTDecode"
        assert img.read_raw_bytes() == path("image.jpg").read_bytes()


@pytest.mark.verifies("neg:pdf.from_images")
def test_images_to_pdf_corrupt():
    r = convert("pdf.from_images", [path("image.png"), path("truncated.png")], "pdf", formats=["png", "png"])
    assert not r.ok and r.error["code"] == "corrupt_input"


# --- page tools --------------------------------------------------------------


@pytest.mark.verifies("pdf.merge:pdf->pdf")
def test_merge_in_order():
    r = convert("pdf.merge", [path("other.pdf"), path("document.pdf")], "pdf")
    assert r.ok
    from pypdf import PdfReader

    pages = PdfReader(r.out).pages
    assert len(pages) == 5
    assert S in pages[2].extract_text() and "Page 2 marker" in pages[1].extract_text()


@pytest.mark.verifies("neg:pdf.merge")
def test_merge_encrypted_needs_password():
    r = convert("pdf.merge", [path("document.pdf"), path("encrypted.pdf")], "pdf")
    assert not r.ok and r.error["code"] == "password_required"


@pytest.mark.verifies("pdf.split:pdf->pdf")
@pytest.mark.parametrize("opts,expect", [
    ({"mode": "every_page"}, [1, 1, 1]),
    ({"mode": "ranges", "ranges": "1-2,3"}, [2, 1]),
    ({"mode": "chunks", "chunk_size": 2}, [2, 1]),
])
def test_split(opts, expect):
    r = convert("pdf.split", path("document.pdf"), "pdf", opts)
    assert r.ok, r.error
    assert [pdf_text(p)[0] for p, _ in r.outputs] == expect


@pytest.mark.verifies("neg:pdf.split")
def test_split_bad_range():
    r = convert("pdf.split", path("document.pdf"), "pdf", {"mode": "ranges", "ranges": "2-9"})
    assert not r.ok and "doesn't exist" in r.error["message"]


@pytest.mark.verifies("pdf.extract_pages:pdf->pdf", "neg:pdf.extract_pages")
def test_extract_pages():
    r = convert("pdf.extract_pages", path("document.pdf"), options={"pages": "3,1"})
    n, text = pdf_text(r.out)
    assert n == 2 and text.index("Page 3 marker") < text.index(S)
    assert not convert("pdf.extract_pages", path("document.pdf"), options={"pages": "x"}).ok


@pytest.mark.verifies("pdf.delete_pages:pdf->pdf", "neg:pdf.delete_pages")
def test_delete_pages():
    r = convert("pdf.delete_pages", path("document.pdf"), options={"pages": "2"})
    n, text = pdf_text(r.out)
    assert n == 2 and "Page 2 marker" not in text and "Page 3 marker" in text
    bad = convert("pdf.delete_pages", path("document.pdf"), options={"pages": "1-3"})
    assert not bad.ok and "Keep at least one" in bad.error["message"]


@pytest.mark.verifies("pdf.reorder:pdf->pdf", "neg:pdf.reorder")
def test_reorder():
    r = convert("pdf.reorder", path("document.pdf"), options={"order": "3,1,2"})
    from pypdf import PdfReader

    pages = PdfReader(r.out).pages
    assert "Page 3 marker" in pages[0].extract_text() and S in pages[1].extract_text()
    bad = convert("pdf.reorder", path("document.pdf"), options={"order": "1,1,2"})
    assert not bad.ok and "exactly once" in bad.error["message"]


@pytest.mark.verifies("pdf.rotate:pdf->pdf", "neg:pdf.rotate")
def test_rotate():
    r = convert("pdf.rotate", path("document.pdf"), options={"angle": 90, "pages": "2"})
    from pypdf import PdfReader

    assert [p.rotation for p in PdfReader(r.out).pages] == [0, 90, 0]
    assert not convert("pdf.rotate", path("corrupt.pdf"), options={}, formats=["pdf"]).ok


# --- watermark / security / compress -------------------------------------------


@pytest.mark.verifies("pdf.watermark:pdf->pdf", "neg:pdf.watermark")
def test_text_watermark():
    r = convert("pdf.watermark", path("document.pdf"), options={"text": "DRAFT-XYZ", "pages": "1-2"})
    from pypdf import PdfReader

    pages = PdfReader(r.out).pages
    assert "DRAFT-XYZ" in pages[0].extract_text() and "DRAFT-XYZ" in pages[1].extract_text()
    assert "DRAFT-XYZ" not in pages[2].extract_text() and S in pages[0].extract_text()
    assert not convert("pdf.watermark", path("encrypted.pdf"), options={}).ok


@pytest.mark.parametrize("src,dst", pairs_of("pdf.watermark_image"))
def test_image_watermark(src, dst):
    img = "image.png" if src == "pdf" else f"image.{src}"
    r = convert("pdf.watermark_image", [path("document.pdf"), path(img)], "pdf", {"opacity": 1, "scale": 0.5})
    assert r.ok, r.error
    validate_pdf(r.out, pages=3, contains=[S])
    import pikepdf

    with pikepdf.open(r.out) as pdf:
        assert len(pdf.pages[0].images) >= 1


@pytest.mark.verifies("neg:pdf.watermark_image")
def test_image_watermark_needs_both():
    r = convert("pdf.watermark_image", [path("document.pdf"), path("other.pdf")], "pdf")
    assert not r.ok and "one PDF and one image" in r.error["message"]


@pytest.mark.verifies("pdf.protect:pdf->pdf", "neg:pdf.protect")
def test_protect_aes256():
    import pikepdf

    r = convert("pdf.protect", path("document.pdf"), options={"password": "pw-123", "allow_copying": False})
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(r.out)
    with pikepdf.open(r.out, password="pw-123") as pdf:
        assert pdf.encryption.R == 6 and pdf.encryption.bits == 256 and "aes" in str(pdf.encryption.stream_method).lower()
    validate_pdf(r.out, contains=[S], password="pw-123")
    from engine.registry import get

    with pytest.raises(ValueError):
        get("pdf.protect").options.model_validate({"password": ""})


@pytest.mark.verifies("pdf.unlock:pdf->pdf")
def test_unlock_with_password():
    r = convert("pdf.unlock", path("encrypted.pdf"), options={"password": "secret"})
    import pikepdf

    with pikepdf.open(r.out) as pdf:
        assert not pdf.is_encrypted
    validate_pdf(r.out, contains=[S])


@pytest.mark.verifies("neg:pdf.unlock", "pdf.unlock:pdf->pdf")
@pytest.mark.parametrize("name,opts,code", [
    ("encrypted.pdf", {}, "password_required"),
    ("encrypted.pdf", {"password": "guess"}, "wrong_password"),
    ("restricted.pdf", {}, "confirmation_required"),
    ("document.pdf", {}, "not_encrypted"),
])
def test_unlock_negative(name, opts, code):
    r = convert("pdf.unlock", path(name), options=opts)
    assert not r.ok and r.error["code"] == code


@pytest.mark.verifies("pdf.unlock:pdf->pdf")
def test_unlock_restricted_with_confirmation():
    r = convert("pdf.unlock", path("restricted.pdf"), options={"confirm_authorized": True})
    assert r.ok
    import pikepdf

    with pikepdf.open(r.out) as pdf:
        assert not pdf.is_encrypted


@pytest.mark.verifies("pdf.compress:pdf->pdf")
def test_compress_pdf_shrinks_images():
    r = convert("pdf.compress", path("photos.pdf"), options={"level": "strong"})
    assert r.ok, r.error
    assert r.out.stat().st_size < path("photos.pdf").stat().st_size * 0.6
    validate_pdf(r.out, pages=4, contains=[S])


@pytest.mark.verifies("pdf.compress:pdf->pdf", "neg:pdf.compress")
def test_compress_pdf_never_larger():
    r = convert("pdf.compress", path("other.pdf"), options={"level": "light"})
    assert r.ok
    assert r.out.stat().st_size <= path("other.pdf").stat().st_size
    if r.info.get("returned_original"):
        assert r.out.read_bytes() == path("other.pdf").read_bytes() and r.warnings
    assert not convert("pdf.compress", path("encrypted.pdf")).ok


# --- extraction ----------------------------------------------------------------


@pytest.mark.parametrize("src,dst", pairs_of("pdf.to_text"))
def test_pdf_to_text_matrix(src, dst):
    r = convert("pdf.to_text", path("document.pdf"), dst)
    assert r.ok, r.error
    validate_document(r.out, dst, [S, "Page 3 marker"])
    if dst == "md":
        assert r.out.read_text().startswith("# Quarterly Report")


@pytest.mark.verifies("neg:pdf.to_text")
def test_pdf_to_text_scanned():
    r = convert("pdf.to_text", path("scanned.pdf"), "txt")
    assert not r.ok and r.error["code"] == "no_text" and "scan" in r.error["message"]


@pytest.mark.parametrize("src,dst", pairs_of("pdf.to_docx"))
def test_pdf_to_docx(src, dst):
    r = convert("pdf.to_docx", path("document.pdf"), "docx")
    assert r.ok, r.error
    from docx import Document

    d = Document(r.out)
    assert any(p.style.name.startswith("Heading") and "Quarterly Report" in p.text for p in d.paragraphs)
    assert S in " ".join(p.text for p in d.paragraphs)
    assert len(d.tables) == 1 and d.tables[0].cell(2, 0).text == "Banana" and d.tables[0].cell(2, 1).text == "12"
    assert "Page 3 marker" in docx_text(r.out)


@pytest.mark.verifies("neg:pdf.to_docx")
def test_pdf_to_docx_scanned():
    r = convert("pdf.to_docx", path("scanned.pdf"), "docx")
    assert not r.ok and r.error["code"] == "no_text"


@pytest.mark.parametrize("src,dst", pairs_of("pdf.to_tables"))
def test_pdf_tables(src, dst):
    r = convert("pdf.to_tables", path("document.pdf"), dst)
    assert r.ok, r.error
    if dst == "xlsx":
        from openpyxl import load_workbook

        ws = load_workbook(r.out).worksheets[0]
        rows = [[c.value for c in row] for row in ws.iter_rows()]
        assert rows[0] == ["Name", "Qty", "Price"] and rows[2] == ["Banana", 12, 0.25]
    else:
        import csv

        rows = list(csv.reader(r.out.open()))
        assert rows[2] == ["Banana", "12", "0.25"]


@pytest.mark.verifies("neg:pdf.to_tables")
def test_pdf_tables_none_found():
    r = convert("pdf.to_tables", path("other.pdf"), "xlsx")
    assert not r.ok and r.error["code"] == "no_tables" and "didn't find any tables" in r.error["message"]


# ---------------------------------------------------------------------------
# OCR (Experimental, ENABLE_OCR): needs ocrmypdf + tesseract

def _ocr_missing() -> list[str]:
    from engine import registry

    return registry.missing_engines(registry.get("pdf.ocr"), "pdf", "pdf")


@pytest.mark.verifies("pdf.ocr:pdf->pdf")
def test_ocr_makes_a_scanned_pdf_searchable():
    if _ocr_missing():
        pytest.skip(f"engine missing: {_ocr_missing()}")
    assert "fox" not in pdf_text(path("scanned.pdf"))[1].lower()  # image only: no text layer before
    r = convert("pdf.ocr", path("scanned.pdf"), timeout=180)
    assert r.ok, r.error
    validate_pdf(r.out, pages=1)
    text = pdf_text(r.out)[1].lower().replace(" ", "")
    assert "quickbrownfox" in text and "12345" in text


@pytest.mark.verifies("neg:pdf.ocr")
def test_ocr_refuses_a_pdf_that_already_has_text():
    if _ocr_missing():
        pytest.skip(f"engine missing: {_ocr_missing()}")
    r = convert("pdf.ocr", path("document.pdf"), timeout=180)
    assert not r.ok and r.error["code"] == "has_text"
    assert "Re-OCR" in r.error["message"]
    # with "Re-OCR" on, it runs anyway and the known text survives
    r = convert("pdf.ocr", path("document.pdf"), options={"force": True}, timeout=180)
    assert r.ok, r.error
    assert "quick brown fox" in pdf_text(r.out)[1].lower()
    # encrypted PDFs get a clear next step
    r = convert("pdf.ocr", path("encrypted.pdf"), options={"password": "secret"}, timeout=180)
    assert not r.ok and r.error["code"] == "password_required" and "Unlock PDF" in r.error["message"]
