"""Limits, rate limiting, retention, cancel and timeout — against a live instance with tiny limits."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
from conftest import start_live, stop_live, upload, wait_job
from fixtures.generate import path

pytestmark = pytest.mark.live

LIMITS = {
    "MAX_FILE_SIZE_MB": "1",
    "MAX_VIDEO_SIZE_MB": "2",
    "MAX_BATCH_FILES": "3",
    "MAX_BATCH_TOTAL_MB": "3",
    "RATE_LIMIT_JOBS_PER_10MIN": "6",
    "FILE_RETENTION_MINUTES": "0.05",  # 3 seconds
    "SWEEP_INTERVAL_S": "0.5",
    "JOB_TIMEOUT_FAST_S": "1",
}


@pytest.fixture(scope="module")
def tiny(redis_server):
    lv = start_live({**LIMITS, "REDIS_URL": redis_server.replace("/0", "/1")}, name="tiny")
    yield lv
    stop_live(lv)


def storage(lv) -> Path:
    return Path(lv.env["STORAGE_DIR"])


def _big_bytes(mb: float) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * int(mb * 1024 * 1024)


def test_oversized_upload_413_and_nothing_kept(tiny):
    with tiny.client() as c:
        r = c.post("/api/uploads", files=[("files", ("big.png", _big_bytes(1.5), "image/png"))])
        assert r.status_code == 413
        assert "1 MB" in r.json()["error"]["message"]
    assert list((storage(tiny) / "uploads").iterdir()) == []


def test_oversized_upload_aborts_mid_stream(tiny):
    """No Content-Length: the server must stop reading once the limit is crossed."""

    def gen():
        boundary = b"xyzBOUNDARY"
        yield b"--" + boundary + b'\r\nContent-Disposition: form-data; name="files"; filename="a.png"\r\n\r\n'
        yield b"\x89PNG\r\n\x1a\n"
        for _ in range(64):  # 4 MB in 64 KB chunks
            yield b"\x00" * 65536
        yield b"\r\n--" + boundary + b"--\r\n"

    with tiny.client() as c:
        r = c.post("/api/uploads", content=gen(), headers={"Content-Type": "multipart/form-data; boundary=xyzBOUNDARY"})
    assert r.status_code == 413
    assert list((storage(tiny) / "uploads").iterdir()) == []


def test_too_many_files_rejected(tiny):
    with tiny.client() as c:
        r = upload(c, *[path("image.png")] * 4)
        assert r.status_code == 413 and "at most 3 files" in r.json()["error"]["message"]


def test_job_rate_limit_429_with_retry_after(tiny):
    with tiny.client() as c:
        f = upload(c, path("image.png")).json()["files"][0]
        codes = []
        for _ in range(8):
            r = c.post("/api/jobs", json={"file_ids": [f["id"]], "operation": "image.convert", "target": "gif"})
            codes.append(r.status_code)
            if r.status_code == 429:
                assert int(r.headers["Retry-After"]) > 0
                assert "rate limit" in r.json()["error"]["message"]
                break
        assert 429 in codes


def test_files_expire_and_are_deleted(tiny):
    with httpx.Client(base_url=tiny.base, timeout=30) as c:
        f = upload(c, path("image.png")).json()["files"][0]
        upload_dir = storage(tiny) / "uploads" / f["id"]
        assert upload_dir.exists()
        time.sleep(4.5)  # retention 3 s + sweep interval 0.5 s
        assert not upload_dir.exists()
        assert c.get(f"/api/uploads/{f['id']}").status_code == 404


def test_succeeded_job_expires(tiny):
    with httpx.Client(base_url=tiny.base, timeout=30) as c:
        f = upload(c, path("image.png")).json()["files"][0]
        r = c.post("/api/jobs", json={"file_ids": [f["id"]], "operation": "image.convert", "target": "jpg"})
        if r.status_code == 429:
            pytest.skip("rate limit window from previous test")
        jid = r.json()["jobs"][0]["id"]
        assert wait_job(c, jid)["state"] == "succeeded"
        assert (storage(tiny) / "jobs" / jid).exists()
        time.sleep(4.5)
        assert not (storage(tiny) / "jobs" / jid).exists()
        assert c.get(f"/api/jobs/{jid}").json()["state"] == "expired"
        assert c.get(f"/api/jobs/{jid}/files/0").status_code == 404


def test_timeout_kills_process_and_fails_cleanly(tiny, redis_server):
    with httpx.Client(base_url=tiny.base, timeout=30) as c:
        f = upload(c, path("big-gradient.png")).json()["files"][0]
        assert f["format"] == "png", f
        r = c.post("/api/jobs", json={"file_ids": [f["id"]], "operation": "image.convert", "target": "webp",
                                       "options": {"quality": 100, "lossless": True}})  # ~4 s of encoding
        if r.status_code == 429:
            pytest.skip("rate limit window from previous test")
        jid = r.json()["jobs"][0]["id"]
        t0 = time.time()
        j = wait_job(c, jid, timeout=30)
        assert j["state"] == "failed", j
        assert j["error"]["code"] == "timeout"
        assert "longer than 1 seconds" in j["error"]["message"]
        assert time.time() - t0 < 10
        assert not (storage(tiny) / "jobs" / jid).exists()


def test_cancel_kills_job_and_cleans_up(client, live):
    f = upload(client, path("big-gradient.png")).json()["files"][0]
    jid = client.post("/api/jobs", json={"file_ids": [f["id"]], "operation": "image.convert", "target": "webp",
                                         "options": {"quality": 100, "lossless": True}}).json()["jobs"][0]["id"]
    end = time.time() + 20
    while client.get(f"/api/jobs/{jid}").json()["state"] != "running" and time.time() < end:
        time.sleep(0.05)
    r = client.post(f"/api/jobs/{jid}/cancel")
    assert r.json()["state"] == "cancelled"
    time.sleep(1.5)
    j = client.get(f"/api/jobs/{jid}").json()
    assert j["state"] == "cancelled" and not j["outputs"]
    assert not (Path(live.env["STORAGE_DIR"]) / "jobs" / jid).exists()


def test_delete_session_removes_everything(live):
    with live.client() as c:
        f = upload(c, path("image.png")).json()["files"][0]
        jid = c.post("/api/jobs", json={"file_ids": [f["id"]], "operation": "image.convert", "target": "jpg"}).json()["jobs"][0]["id"]
        wait_job(c, jid)
        r = c.delete("/api/session").json()
        assert r["deleted_files"] >= 1 and r["deleted_jobs"] >= 1
        st = Path(live.env["STORAGE_DIR"])
        assert not (st / "jobs" / jid).exists() and not (st / "uploads" / f["id"]).exists()
        assert c.get(f"/api/jobs/{jid}").status_code == 404
