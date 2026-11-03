"""Security: hostile inputs must be blocked. Canaries prove nothing was fetched or read."""

from __future__ import annotations

import http.server
import threading

import pytest
from conftest import TMP, convert
from fixtures.generate import path

from engine.validators.images import open_image

GREEN = (0, 255, 0)


class Canary:
    """A local HTTP server that records every request it receives."""

    def __init__(self):
        hits = self.hits = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                hits.append(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(path("image.png").read_bytes())

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


@pytest.fixture
def canary():
    c = Canary()
    yield c
    c.close()


@pytest.fixture
def green_file():
    from PIL import Image

    p = TMP / "secret-green.png"
    Image.new("RGB", (64, 64), GREEN).save(p)
    return p


def _has_green(img_path) -> bool:
    im = open_image(img_path).convert("RGB")
    return any(abs(r) < 40 and g > 200 and b < 40 for r, g, b in im.getdata())


def _svg(*refs: str) -> str:
    body = "".join(f'<image x="0" y="0" width="64" height="64" href="{r}" xlink:href="{r}"/>' for r in refs)
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="64" height="64">'
            f'<rect width="64" height="64" fill="#ff0000"/>{body}'
            f'<rect width="10" height="10" style="fill:url({refs[0]})"/></svg>')


@pytest.mark.parametrize("target", ["png", "pdf"])
def test_svg_cannot_fetch_urls_or_read_files(tmp_path, canary, green_file, target):
    svg = tmp_path / "evil.svg"
    svg.write_text(_svg(f"{canary.url}/ssrf", "http://169.254.169.254/latest/meta-data/", f"file://{green_file}",
                        str(green_file)))
    r = convert("image.svg_render", svg, target, formats=["svg"])
    assert r.ok, r.error
    assert canary.hits == []
    assert any("external reference" in n for n in r.notices)
    if target == "png":
        assert not _has_green(r.out)


def test_svg_script_and_foreignobject_removed(tmp_path):
    from engine.sanitize import sanitize_svg

    markup, removed = sanitize_svg(
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(2)</script>'
        b'<foreignObject><iframe src="http://x"/></foreignObject><a href="javascript:alert(3)"><rect/></a></svg>')
    assert "script" not in markup and "foreignObject" not in markup and "onload" not in markup and "javascript" not in markup
    assert removed >= 4


def test_xxe_in_svg_blocked(tmp_path, green_file):
    p = tmp_path / "xxe.svg"
    p.write_text(f'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file://{green_file}">]>'
                 '<svg xmlns="http://www.w3.org/2000/svg"><text>&x;</text></svg>')
    r = convert("image.svg_render", p, "png", formats=["svg"])
    assert not r.ok and r.error["code"] == "corrupt_input"


def test_sandbox_blocks_network_and_home(tmp_path):
    import sys
    from pathlib import Path

    from engine import sandbox

    iso = sandbox.isolation_mode()
    if iso.kind == "limits-only":
        pytest.skip("no OS-level isolation available on this host")
    r = sandbox.run_sync([sys.executable, "-I", "-c", "import socket; socket.create_connection(('1.1.1.1', 80), timeout=3)"],
                         job_dir=tmp_path, limits=sandbox.Limits(timeout_s=10))
    assert r.returncode != 0
    r = sandbox.run_sync(["/bin/sh", "-c", f"echo x > {Path.home()}/uc-escape-test"], job_dir=tmp_path,
                         limits=sandbox.Limits(timeout_s=10))
    assert r.returncode != 0 and not (Path.home() / "uc-escape-test").exists()


def test_sandbox_output_size_limit(tmp_path):
    import sys

    from engine import sandbox

    r = sandbox.run_sync([sys.executable, "-I", "-c", "open('big','wb').write(b'0'*(3*1024*1024))"],
                         job_dir=tmp_path, limits=sandbox.Limits(timeout_s=10, fsize_mb=1), cwd=tmp_path)
    assert r.returncode != 0
    assert not (tmp_path / "big").exists() or (tmp_path / "big").stat().st_size <= 1024 * 1024


def test_sandbox_timeout_kills_process_group(tmp_path):
    import sys
    import time

    from engine import sandbox

    t = time.time()
    r = sandbox.run_sync([sys.executable, "-I", "-c",
                          "import subprocess,time; subprocess.Popen(['sleep','30']); time.sleep(30)"],
                         job_dir=tmp_path, limits=sandbox.Limits(timeout_s=1))
    assert r.timed_out and time.time() - t < 5
    import subprocess

    out = subprocess.run(["pgrep", "-f", "sleep 30"], capture_output=True, text=True).stdout.strip()
    assert out == "", f"orphan survived: {out}"
