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
