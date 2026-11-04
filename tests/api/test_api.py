"""HTTP-level tests against the live API + real workers."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from conftest import upload, wait_job
from fixtures.generate import path

pytestmark = pytest.mark.live


def _sse_states(client: httpx.Client, job_id: str) -> list[dict]:
    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/events", timeout=60) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data:"):
                ev = json.loads(line[5:].strip())
                events.append(ev)
                if ev["state"] in ("succeeded", "failed", "cancelled", "expired"):
                    break
    return events


def test_health_reports_engines(client):
    h = client.get("/api/health").json()
    assert h["redis"] is True
    assert h["workers"]["fast"] >= 1 and h["workers"]["heavy"] >= 1
    assert h["engines"]["pillow"]["available"]
    assert h["isolation"]["mode"] in ("seatbelt", "bwrap", "limits-only")


def test_capabilities_from_registry(client):
    caps = client.get("/api/capabilities").json()
    ops = {o["id"]: o for o in caps["operations"]}
    assert "image.convert" in ops
    pairs = {(p["source"], p["target"]) for p in ops["image.convert"]["pairs"]}
    assert ("png", "jpg") in pairs
    schema = ops["image.convert"]["options_schema"]
    assert schema["properties"]["quality"]["maximum"] == 100
    assert caps["limits"]["retention_minutes"] == 60


def test_png_to_jpg_full_path(client, live):
    r = upload(client, path("image.png"))
    assert r.status_code == 200, r.text
    assert "uc_session" in r.cookies or client.cookies.get("uc_session")
    f = r.json()["files"][0]
    assert f["format"] == "png" and f["size"] == path("image.png").stat().st_size and not f["warnings"]

    r = client.post("/api/jobs", json={"file_ids": [f["id"]], "operation": "image.convert", "target": "jpg",
                                       "options": {"quality": 90}})
    assert r.status_code == 200, r.text
    job_id = r.json()["jobs"][0]["id"]
    events = _sse_states(client, job_id)
    assert events[-1]["state"] == "succeeded", events[-1]
    stages = [e["stage"] for e in events if e.get("stage")]
    assert len(stages) >= 2

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["outputs"][0]["name"] == "image.jpg"
    d = client.get(f"/api/jobs/{job_id}/files/0")
    assert d.status_code == 200
    assert d.content[:3] == b"\xff\xd8\xff"
    assert d.headers["content-disposition"].startswith("attachment;")
    assert d.headers["x-content-type-options"] == "nosniff"
    assert d.headers["content-type"] == "image/jpeg"

    # another browser session can't see it
    with httpx.Client(base_url=live.base) as other:
        upload(other, path("image.jpg"))  # gets its own cookie
        assert other.get(f"/api/jobs/{job_id}").status_code == 404
        assert other.get(f"/api/jobs/{job_id}/files/0").status_code == 404
        assert other.get(f"/api/uploads/{f['id']}/raw").status_code == 404
    with httpx.Client(base_url=live.base) as anon:
        assert anon.get(f"/api/jobs/{job_id}/files/0").status_code == 404

    # delete now: files are gone from disk and from the API
    job_dir = Path(live.env["STORAGE_DIR"]) / "jobs" / job_id
    assert job_dir.exists()
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert not job_dir.exists()
    assert client.get(f"/api/jobs/{job_id}/files/0").status_code == 404
    assert client.delete(f"/api/uploads/{f['id']}").status_code == 200
    assert not (Path(live.env["STORAGE_DIR"]) / "uploads" / f["id"]).exists()


def test_extension_mismatch_warns_and_content_wins(client):
    f = upload(client, path("png-named.jpg")).json()["files"][0]
    assert f["format"] == "png"
    assert f["warnings"] and "content is PNG" in f["warnings"][0]


def test_unidentifiable_file_rejected(client):
    f = upload(client, path("garbage.bin")).json()["files"][0]
    assert f["format"] is None and "couldn't identify" in f["error"]


def test_unsupported_pair_is_clear_4xx(client):
    f = upload(client, path("image.png")).json()["files"][0]
    r = client.post("/api/jobs", json={"file_ids": [f["id"]], "operation": "image.convert", "target": "docx"})
    assert r.status_code == 400
    msg = r.json()["error"]["message"]
    assert "isn't supported" in msg and "JPG" in msg


def test_invalid_options_422(client):
    f = upload(client, path("image.png")).json()["files"][0]
    r = client.post("/api/jobs", json={"file_ids": [f["id"]], "operation": "image.convert", "target": "jpg",
                                       "options": {"quality": 0}})
    assert r.status_code == 422 and "quality" in r.json()["error"]["message"]


def test_failed_job_has_actionable_error_and_no_outputs(client, live):
    f = upload(client, path("bomb.png")).json()["files"][0]
    job_id = client.post("/api/jobs", json={"file_ids": [f["id"]], "operation": "image.convert", "target": "jpg"}).json()["jobs"][0]["id"]
    j = wait_job(client, job_id)
    assert j["state"] == "failed" and j["error"]["code"] == "too_many_pixels"
    assert not (Path(live.env["STORAGE_DIR"]) / "jobs" / job_id).exists()


def test_batch_zip_contains_every_output(client):
    files = upload(client, path("image.png"), path("image.gif"), path("image.bmp")).json()["files"]
    r = client.post("/api/jobs", json={"file_ids": [f["id"] for f in files], "operation": "image.convert", "target": "webp"})
    body = r.json()
    assert len(body["jobs"]) == 3
    for j in body["jobs"]:
        assert wait_job(client, j["id"])["state"] == "succeeded"
    z = client.get(f"/api/batches/{body['batch_id']}/zip")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    names = sorted(zipfile.ZipFile(io.BytesIO(z.content)).namelist())
    assert names == ["image (2).webp", "image (3).webp", "image.webp"]


def test_path_traversal_filename_is_metadata_only(client, live):
    r = upload(client, path("image.png"), names=["../../../../etc/passwd.png"])
    f = r.json()["files"][0]
    assert f["name"] == "passwd.png"
    storage = Path(live.env["STORAGE_DIR"])
    assert (storage / "uploads" / f["id"] / "data").exists()
    assert not any(p.name == "passwd.png" for p in storage.rglob("*"))


def test_non_ascii_filename_content_disposition(client):
    f = upload(client, path("image.png"), names=["фото café.png"]).json()["files"][0]
    job = client.post("/api/jobs", json={"file_ids": [f["id"]], "operation": "image.convert", "target": "jpg"}).json()
    jid = job["jobs"][0]["id"]
    wait_job(client, jid)
    cd = client.get(f"/api/jobs/{jid}/files/0").headers["content-disposition"]
    assert "filename*=UTF-8''%D1%84%D0%BE%D1%82%D0%BE%20caf%C3%A9.jpg" in cd
    assert 'filename="' in cd and "\n" not in cd


def test_pdf_page_thumbnails_are_sandboxed_and_cached(client, live):
    f = upload(client, path("document.pdf")).json()["files"][0]
    r = client.get(f"/api/uploads/{f['id']}/pages")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pages"] == 3 and len(body["thumbnails"]) == 3
    png = client.get(body["thumbnails"][1])
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    cache = Path(live.env["STORAGE_DIR"]) / "uploads" / f["id"] / "thumbs"
    assert (cache / "pages.json").exists() and not (cache / "job").exists()
    # another session can't read them; non-PDFs are refused; encrypted PDFs give a clear error
    with httpx.Client(base_url=live.base) as other:
        assert other.get(body["thumbnails"][0]).status_code == 404
    img = upload(client, path("image.png")).json()["files"][0]
    assert client.get(f"/api/uploads/{img['id']}/pages").status_code == 400
    enc = upload(client, path("encrypted.pdf")).json()["files"][0]
    r = client.get(f"/api/uploads/{enc['id']}/pages")
    assert r.status_code == 422 and "password" in r.json()["error"]["message"]


def test_failure_logs_name_the_error_class_never_the_message():
    """Exception messages and engine stderr can quote file contents, so worker logs keep only the class."""
    import worker

    tb = 'Traceback (most recent call last):\n  File "/x.py", line 3, in f\nValueError: could not convert \'ACME salary 120000\''
    assert worker.error_class(tb) == "ValueError"
    assert worker.error_class("pikepdf._core.PdfError: object 12 0 is broken") == "pikepdf._core.PdfError"
    assert worker.error_class("[mp3 @ 0x1] Header missing\nConfidential paragraph text") == "unknown"
    assert worker.error_class(None) == "unknown"


def test_spreadsheet_result_table_preview(client, live):
    f = upload(client, path("data.csv")).json()["files"][0]
    jid = client.post("/api/jobs", json={"file_ids": [f["id"]], "operation": "sheet.import", "target": "xlsx",
                                         "options": {}}).json()["jobs"][0]["id"]
    assert wait_job(client, jid)["state"] == "succeeded"
    r = client.get(f"/api/jobs/{jid}/files/0/table")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows"][0] == ["Name", "Qty", "Price", "Note"] and len(body["rows"]) == 5
    assert body["rows"][2][:3] == ["Banana", "12", "0.25"] and body["rows"][4][0] == "Dürüm"
    assert body["truncated"] is False and body["sheet"]
    # cached next to the result, rendered in the sandbox (no job dir left behind)
    cache = Path(live.env["STORAGE_DIR"]) / "jobs" / jid / "previews" / "0"
    assert (cache / "table.json").exists() and not (cache / "tjob").exists()
    with httpx.Client(base_url=live.base) as other:
        assert other.get(f"/api/jobs/{jid}/files/0/table").status_code == 404
    img = upload(client, path("image.png")).json()["files"][0]
    jj = client.post("/api/jobs", json={"file_ids": [img["id"]], "operation": "image.convert", "target": "jpg",
                                        "options": {}}).json()["jobs"][0]["id"]
    assert wait_job(client, jj)["state"] == "succeeded"
    assert client.get(f"/api/jobs/{jj}/files/0/table").status_code == 400


def test_pdf_hub_lists_only_advertised_tools(client):
    caps = client.get("/api/capabilities").json()
    hub = caps["hubs"]["pdf"]
    advertised = {(o["id"], p["source"], p["target"]) for o in caps["operations"] for p in o["pairs"]}
    slugs = {t["slug"] for t in hub["tools"]}
    assert {"merge-pdf", "split-pdf", "compress-pdf", "word-to-pdf", "pdf-to-jpg"} <= slugs
    for t in hub["tools"]:
        assert any(op == t["op"] and s in t["sources"] for op, s, _ in advertised), t["slug"]
        assert t["group"] in {g["id"] for g in hub["groups"]}
    # feature-flagged tools stay out while their flag is off (this instance runs without ENABLE_AGPL_ENGINES)
    assert "pdf-to-pdfa" not in slugs
    word = next(t for t in hub["tools"] if t["slug"] == "word-to-pdf")
    assert word["target"] == "pdf" and {"docx", "doc", "odt", "rtf"} >= set(word["sources"]) and "docx" in word["sources"]
    assert any("AI" in x["title"] for x in hub["not_offered"])


def test_page_editor_view_and_form_fields(client, live):
    pdf = upload(client, path("document.pdf")).json()["files"][0]
    idx = client.get(f"/api/uploads/{pdf['id']}/pages").json()
    assert idx["sizes"][0] == [pytest.approx(595.28, abs=0.1), pytest.approx(841.89, abs=0.1)]
    r = client.get(f"/api/uploads/{pdf['id']}/view/1")
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image

    assert Image.open(io.BytesIO(r.content)).width == pytest.approx(595.28 * 110 / 72, abs=2)
    assert client.get(f"/api/uploads/{pdf['id']}/view/9").status_code == 422  # no such page
    with httpx.Client(base_url=live.base) as other:
        assert other.get(f"/api/uploads/{pdf['id']}/view/0").status_code == 404
    # form fields
    form = upload(client, path("form.pdf")).json()["files"][0]
    fields = client.get(f"/api/uploads/{form['id']}/form").json()["fields"]
    assert {f["name"] for f in fields} == {"full_name", "subscribe", "country", "plan"}
    r = client.get(f"/api/uploads/{pdf['id']}/form")
    assert r.status_code == 422 and "no fillable form fields" in r.json()["error"]["message"]
    img = upload(client, path("image.png")).json()["files"][0]
    assert client.get(f"/api/uploads/{img['id']}/form").status_code == 400


def test_oversized_job_options_rejected(client):
    f = upload(client, path("document.pdf")).json()["files"][0]
    big = {"objects": [{"type": "image", "page": 1, "x": 0, "y": 0, "w": 0.1, "h": 0.1,
                        "data": "data:image/png;base64," + "A" * 3_900_000}] * 5}
    r = client.post("/api/jobs", json={"file_ids": [f["id"]], "operation": "pdf.edit", "target": None, "options": big})
    assert r.status_code == 413 and "too large" in r.json()["error"]["message"]
