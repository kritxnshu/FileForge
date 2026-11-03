"""Archives: repack matrix, extraction, create ZIP, gzip/gunzip, passwords, and every §7 safety limit."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest
from conftest import convert, pairs_of
from fixtures.generate import FIXTURE_FOR, KNOWN_SENTENCE, archive_members, path, rar4

EXPECTED = {n: d for n, d in archive_members()}


def read_archive(p: Path, fmt: str) -> dict[str, bytes]:
    """Independent readers: zipfile / tarfile / py7zr."""
    if fmt == "zip":
        with zipfile.ZipFile(p) as z:
            return {i.filename: z.read(i) for i in z.infolist() if not i.is_dir()}
    if fmt == "7z":
        import tempfile

        import py7zr

        with tempfile.TemporaryDirectory() as td, py7zr.SevenZipFile(p) as z:
            z.extractall(path=td)
            return {str(f.relative_to(td)): f.read_bytes() for f in Path(td).rglob("*") if f.is_file()}
    mode = {"tar": "r:", "tgz": "r:gz", "tbz2": "r:bz2", "txz": "r:xz"}[fmt]
    with tarfile.open(p, mode) as t:
        return {m.name: t.extractfile(m).read() for m in t if m.isfile()}


@pytest.mark.parametrize("src,dst", pairs_of("archive.convert"))
def test_repack_matrix(src, dst):
    r = convert("archive.convert", path(f"archive.{src}"), dst)
    assert r.ok, r.error
    assert read_archive(r.out, dst) == EXPECTED


@pytest.mark.parametrize("src,dst", pairs_of("archive.extract"))
def test_extract_matrix(src, dst):
    r = convert("archive.extract", path(f"archive.{src}"))
    assert r.ok, r.error
    got = {}
    for p, fmt in r.outputs:
        rel = str(p.relative_to(r.job_dir / "out" / "files"))
        got[rel] = p.read_bytes()
    assert got == EXPECTED
    fmts = {str(p.name): f for p, f in r.outputs}
    assert fmts == {"hello.txt": "txt", "data.csv": "csv", "blocks.png": "png"}


@pytest.mark.parametrize("src,dst", pairs_of("archive.create_zip"))
def test_create_zip(src, dst):
    fx = path(FIXTURE_FOR[src])
    r = convert("archive.create_zip", [fx, fx, path("image.png")], "zip", names=["a." + src, "a." + src, "b.png"],
                formats=[src, src, "png"])
    assert r.ok, r.error
    with zipfile.ZipFile(r.out) as z:
        assert z.namelist() == [f"a.{src}", f"a (2).{src}", "b.png"]
        assert z.read(f"a.{src}") == fx.read_bytes()


@pytest.mark.verifies("neg:archive.create_zip")
def test_create_zip_never_uses_paths_from_names():
    r = convert("archive.create_zip", [path("image.png")], "zip", names=["../../etc/evil.png"])
    with zipfile.ZipFile(r.out) as z:
        assert z.namelist() == ["evil.png"]


@pytest.mark.parametrize("src,dst", pairs_of("archive.gzip"))
def test_gzip(src, dst):
    import gzip

    fx = path(FIXTURE_FOR[src])
    r = convert("archive.gzip", fx, "gz", names=[f"report.{src}"], formats=[src])
    assert r.ok, r.error
    assert gzip.decompress(r.out.read_bytes()) == fx.read_bytes()
    back = convert("archive.gunzip", r.out, formats=["gz"])
    assert back.ok and back.out.read_bytes() == fx.read_bytes()
    assert back.outputs[0][1] in (src, {"tgz": "gz"}.get(src, src))  # original name restored from the gzip header


@pytest.mark.verifies("archive.gunzip:gz->gz", "neg:archive.gunzip", "neg:archive.gzip")
def test_gunzip_and_corrupt(tmp_path):
    r = convert("archive.gunzip", path("archive.gz"))
    assert r.ok and r.out.read_text().strip() == KNOWN_SENTENCE and r.outputs[0][1] == "txt"
    bad = tmp_path / "bad.gz"
    bad.write_bytes(path("archive.gz").read_bytes()[:30])
    r = convert("archive.gunzip", bad, formats=["gz"])
    assert not r.ok and r.error["code"] == "corrupt_input"
    bomb = tmp_path / "bomb.gz"
    import gzip

    bomb.write_bytes(gzip.compress(b"\0" * (40 * 1024 * 1024)))
    r = convert("archive.gunzip", bomb, formats=["gz"])
    assert not r.ok and r.error["code"] == "archive_limit"


# --- passwords -----------------------------------------------------------------


@pytest.mark.verifies("archive.extract:zip->zip", "archive.extract:7z->7z")
@pytest.mark.parametrize("name", ["encrypted.zip", "encrypted.7z"])
def test_password_archives(name):
    r = convert("archive.extract", path(name))
    assert not r.ok and r.error["code"] == "password_required"
    r = convert("archive.extract", path(name), options={"password": "wrong"})
    assert not r.ok and r.error["code"] in ("wrong_password", "corrupt_input")
    r = convert("archive.extract", path(name), options={"password": "secret"})
    assert r.ok, r.error
    assert r.out.read_text().strip() == KNOWN_SENTENCE


# --- security --------------------------------------------------------------------


def _zip_with(tmp_path, entries, name="evil.zip") -> Path:
    p = tmp_path / name
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in entries:
            z.writestr(n, d)
    return p


def _tar_with(tmp_path, infos) -> Path:
    p = tmp_path / "evil.tar"
    with tarfile.open(p, "w") as t:
        for info, data in infos:
            t.addfile(info, io.BytesIO(data) if data is not None else None)
    return p


def _assert_blocked(r, code="unsafe_input"):
    assert not r.ok, "hostile archive was accepted"
    assert r.error["code"] == code, r.error
    # the payload was written nowhere: not in the job, not next to it (the worker also deletes failed jobs' dirs)
    assert not [p for p in r.job_dir.parent.parent.rglob("evil.txt")]


@pytest.mark.verifies("neg:archive.extract", "neg:archive.convert")
@pytest.mark.parametrize("member", ["../../evil.txt", "/etc/evil.txt", "a/../../evil.txt", "C:\\evil.txt", "..\\..\\evil.txt"])
def test_zip_slip_blocked(tmp_path, member):
    p = _zip_with(tmp_path, [("ok.txt", b"fine"), (member, b"pwned")])
    for op, tgt in (("archive.extract", None), ("archive.convert", "tar")):
        r = convert(op, p, tgt, formats=["zip"])
        _assert_blocked(r)
    assert not list(tmp_path.parent.rglob("evil.txt"))


@pytest.mark.verifies("neg:archive.extract")
def test_rar_zip_slip_blocked(tmp_path):
    p = tmp_path / "evil.rar"
    p.write_bytes(rar4([("ok.txt", b"fine"), ("../../evil.txt", b"pwned")]))
    _assert_blocked(convert("archive.extract", p, formats=["rar"]))


@pytest.mark.verifies("neg:archive.extract")
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "chardev", "fifo"])
def test_tar_links_and_devices_blocked(tmp_path, kind):
    good = tarfile.TarInfo("ok.txt")
    good.size = 4
    bad = tarfile.TarInfo("link")
    if kind == "symlink":
        bad.type, bad.linkname = tarfile.SYMTYPE, "/etc/passwd"
    elif kind == "hardlink":
        bad.type, bad.linkname = tarfile.LNKTYPE, "ok.txt"
    elif kind == "chardev":
        bad.type, bad.devmajor, bad.devminor = tarfile.CHRTYPE, 1, 3
    else:
        bad.type = tarfile.FIFOTYPE
    p = _tar_with(tmp_path, [(good, b"fine"), (bad, None)])
    _assert_blocked(convert("archive.extract", p, formats=["tar"]))


@pytest.mark.verifies("neg:archive.extract")
def test_zip_symlink_entry_blocked(tmp_path):
    p = tmp_path / "ln.zip"
    with zipfile.ZipFile(p, "w") as z:
        info = zipfile.ZipInfo("link")
        info.external_attr = (0o120777 << 16)
        z.writestr(info, "/etc/passwd")
    _assert_blocked(convert("archive.extract", p, formats=["zip"]))


@pytest.mark.verifies("neg:archive.extract", "neg:archive.convert")
def test_zip_bomb_blocked(tmp_path):
    p = _zip_with(tmp_path, [("zeros.bin", b"\0" * (60 * 1024 * 1024))])
    assert p.stat().st_size < 200_000  # ~1000:1
    for op, tgt in (("archive.extract", None), ("archive.convert", "7z")):
        _assert_blocked(convert(op, p, tgt, formats=["zip"]), "archive_limit")


@pytest.mark.verifies("neg:archive.extract")
def test_tgz_bomb_blocked(tmp_path):
    info = tarfile.TarInfo("zeros.bin")
    info.size = 60 * 1024 * 1024
    p = tmp_path / "bomb.tgz"
    with tarfile.open(p, "w:gz") as t:
        t.addfile(info, io.BytesIO(b"\0" * info.size))
    _assert_blocked(convert("archive.extract", p, formats=["tgz"]), "archive_limit")


@pytest.mark.verifies("neg:archive.extract")
def test_entry_count_and_total_size_limits(tmp_path):
    p = _zip_with(tmp_path, [(f"f{i}.txt", b"x") for i in range(30)])
    _assert_blocked(convert("archive.extract", p, formats=["zip"], limits={"archive_max_entries": 20}), "archive_limit")
    p = _zip_with(tmp_path, [("a.bin", bytes(range(256)) * 8192)], name="big.zip")  # 2 MB, incompressible-ish
    _assert_blocked(convert("archive.extract", p, formats=["zip"], limits={"archive_max_uncompressed_mb": 1}), "archive_limit")


@pytest.mark.verifies("neg:archive.convert")
def test_corrupt_archives(tmp_path):
    for fx, fmt in (("archive.zip", "zip"), ("archive.7z", "7z"), ("archive.tgz", "tgz")):
        bad = tmp_path / f"bad.{fmt}"
        bad.write_bytes(path(fx).read_bytes()[: len(path(fx).read_bytes()) // 2])
        r = convert("archive.convert", bad, "zip" if fmt != "zip" else "tar", formats=[fmt])
        assert not r.ok and r.error["code"] == "corrupt_input", (fmt, r.error)
