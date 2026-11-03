"""Archives: repack between formats, extract, create ZIP, gzip/gunzip.

Every archive is hostile (SECURITY.md §Archives):
  * member names: absolute paths, drive letters, `..`, NUL bytes and very deep paths are rejected
  * member types: only regular files and directories; symlinks, hardlinks, devices and FIFOs are rejected
  * limits: entry count, total uncompressed bytes, per-entry compression ratio, path depth
  * bytes are counted while streaming; header sizes are never trusted
  * nested archives are never unpacked recursively (nesting depth is 1 by construction)
Readers: zipfile (ZIP), tarfile with filter="data" plus our own checks (TAR family),
libarchive (7Z, RAR — streaming); py7zr only for password-protected 7Z.
"""

from __future__ import annotations

import gzip
import io
import os
import shutil
import tarfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field

from ...context import ConversionError, Ctx
from ...formats import FORMATS, format_from_extension
from ...registry import NoOptions, Operation, Options, register, ui

ARCHIVES = ("zip", "tar", "tgz", "tbz2", "txz", "7z")
READABLE = (*ARCHIVES, "rar")
CHUNK = 1024 * 1024
MAX_PATH_DEPTH = 64


class Limits:
    def __init__(self, ctx: Ctx):
        self.entries = ctx.limit("archive_max_entries", 10_000)
        self.total = ctx.limit("archive_max_uncompressed_mb", 2000) * 1024 * 1024
        self.ratio = ctx.limit("archive_max_ratio", 100)
        self.archive_size = max(1, ctx.input.size)
        self.count = 0
        self.bytes = 0

    def entry(self) -> None:
        self.count += 1
        if self.count > self.entries:
            raise ConversionError("archive_limit", f"This archive has more than {self.entries:,} entries, which is more than we allow.")

    def add(self, n: int, entry_bytes: int, compressed: int | None, declared: int | None) -> None:
        self.bytes += n
        if self.bytes > self.total:
            raise ConversionError("archive_limit", f"This archive unpacks to more than {self.total // 1048576:,} MB, "
                                                   "which is more than we allow.")
        if declared is not None and entry_bytes > declared:
            raise ConversionError("unsafe_input", "An entry in this archive is larger than its header says. The archive is "
                                                  "damaged or crafted to mislead.")
        if compressed and entry_bytes > 1024 * 1024 and entry_bytes / compressed > self.ratio:
            raise ConversionError("archive_limit", f"An entry compresses more than {self.ratio}:1, which looks like a "
                                                   "decompression bomb. It wasn't unpacked.")
        if self.bytes > 8 * 1024 * 1024 and self.bytes / self.archive_size > self.ratio * 2:
            raise ConversionError("archive_limit", f"This archive expands more than {self.ratio * 2}:1 overall, which looks "
                                                   "like a decompression bomb. It wasn't unpacked.")


def safe_name(raw: str) -> str | None:
    """Normalize a member name; None for the archive root. Raises on anything unsafe."""
    name = raw.replace("\\", "/")
    if "\x00" in name:
        raise ConversionError("unsafe_input", "This archive contains a file name with a NUL byte.")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":") or name.startswith("//"):
        raise ConversionError("unsafe_input", f"This archive contains an absolute path (“{raw[:80]}”), which isn't allowed.")
    parts = [p for p in PurePosixPath(name).parts if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ConversionError("unsafe_input", f"This archive contains a path that escapes its folder (“{raw[:80]}”), "
                                              "which isn't allowed (zip slip).")
    if len(parts) > MAX_PATH_DEPTH or len(name) > 1024:
        raise ConversionError("unsafe_input", "This archive contains paths nested too deeply.")
    return "/".join(parts) or None


@dataclass
class Member:
    name: str
    is_dir: bool
    size: int | None
    compressed: int | None


def _copy(src, dst: Path, m: Member, lim: Limits) -> None:
    n = 0
    with dst.open("wb") as f:
        while chunk := src.read(CHUNK):
            n += len(chunk)
            lim.add(len(chunk), n, m.compressed, m.size)
            f.write(chunk)


def _reject_type(name: str, kind: str) -> None:
    raise ConversionError("unsafe_input", f"This archive contains a {kind} (“{name[:80]}”). Links and device files "
                                          "aren't allowed in archives we unpack.")


def extract_all(ctx: Ctx, path: Path, fmt: str, dest: Path, password: str | None = None) -> list[tuple[str, Path]]:
    """Unpack into dest with every check applied. Returns [(member name, file path)] for regular files."""
    lim = Limits(ctx)
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    files: list[tuple[str, Path]] = []

    def target(name: str) -> Path:
        p = (root / name).resolve()
        if root not in p.parents and p != root:
            raise ConversionError("unsafe_input", "This archive contains a path that escapes its folder (zip slip).")
        return p

    def emit_file(m: Member, stream) -> None:
        t = target(m.name)
        if t.exists():
            raise ConversionError("unsafe_input", f"This archive contains “{m.name[:80]}” more than once.")
        t.parent.mkdir(parents=True, exist_ok=True)
        _copy(stream, t, m, lim)
        files.append((m.name, t))
        if lim.count % 25 == 0:
            ctx.progress(stage=f"Unpacking: {lim.count:,} entries", force=True)

    try:
        if fmt == "zip":
            with zipfile.ZipFile(path) as z:
                infos = z.infolist()
                for info in infos:  # validate the whole central directory before writing anything
                    safe_name(info.filename)
                    mode = (info.external_attr >> 16) & 0o170000
                    if mode == 0o120000:
                        _reject_type(info.filename, "symbolic link")
                    if mode and mode not in (0o100000, 0o040000):
                        _reject_type(info.filename, "special file")
                if len(infos) > lim.entries:
                    raise ConversionError("archive_limit", f"This archive has more than {lim.entries:,} entries, which is more than we allow.")
                for info in infos:
                    lim.entry()
                    name = safe_name(info.filename)
                    if name is None or info.is_dir():
                        if name:
                            target(name).mkdir(parents=True, exist_ok=True)
                        continue
                    m = Member(name, False, info.file_size, info.compress_size or None)
                    try:
                        with z.open(info, pwd=password.encode() if password else None) as src:
                            emit_file(m, src)
                    except RuntimeError as e:
                        if "password" in str(e).lower() or "encrypted" in str(e).lower():
                            raise ConversionError("password_required" if not password else "wrong_password",
                                                  "This archive is password-protected — enter its password to continue."
                                                  if not password else "That password is incorrect for this archive.") from e
                        raise
        elif fmt in ("tar", "tgz", "tbz2", "txz"):
            mode = {"tar": "r:", "tgz": "r:gz", "tbz2": "r:bz2", "txz": "r:xz"}[fmt]
            with tarfile.open(path, mode) as t:
                for info in t:
                    lim.entry()
                    if info.issym():
                        _reject_type(info.name, "symbolic link")
                    if info.islnk():
                        _reject_type(info.name, "hard link")
                    if info.ischr() or info.isblk() or info.isfifo() or info.isdev():
                        _reject_type(info.name, "device file")
                    if not (info.isfile() or info.isdir()):
                        _reject_type(info.name, "special entry")
                    name = safe_name(info.name)
                    tarfile.data_filter(info, str(root))  # the stdlib's own checks, on top of ours
                    if name is None or info.isdir():
                        if name:
                            target(name).mkdir(parents=True, exist_ok=True)
                        continue
                    src = t.extractfile(info)
                    if src is None:
                        continue
                    emit_file(Member(name, False, info.size, None), src)
        elif fmt == "7z" and password:
            import py7zr

            import lzma

            try:
                with py7zr.SevenZipFile(path, password=password) as z:
                    infos = z.list()
                    declared = 0
                    for info in infos:
                        lim.entry()
                        safe_name(info.filename)
                        if getattr(info, "is_symlink", False):
                            _reject_type(info.filename, "symbolic link")
                        declared += info.uncompressed or 0
                    if declared > lim.total:
                        raise ConversionError("archive_limit", "This archive unpacks to more than we allow.")
                    z.extractall(path=root)
            except (lzma.LZMAError, py7zr.exceptions.Bad7zFile, py7zr.exceptions.CrcError) as e:
                raise ConversionError("wrong_password", "That password is incorrect for this archive.") from e
            for p in sorted(root.rglob("*")):
                if p.is_symlink():
                    _reject_type(p.name, "symbolic link")
                if p.is_file():
                    lim.add(p.stat().st_size, p.stat().st_size, None, None)
                    files.append((str(p.relative_to(root)), p))
        else:  # 7z, rar via libarchive (streaming)
            import libarchive

            kw = {"passphrase": password} if password else {}
            with libarchive.file_reader(str(path), **kw) as arc:
                for entry in arc:
                    lim.entry()
                    if entry.issym:
                        _reject_type(entry.pathname, "symbolic link")
                    if entry.islnk:
                        _reject_type(entry.pathname, "hard link")
                    if entry.isblk or entry.ischr or entry.isfifo or entry.issock:
                        _reject_type(entry.pathname, "device file")
                    name = safe_name(entry.pathname)
                    if name is None or entry.isdir:
                        if name:
                            target(name).mkdir(parents=True, exist_ok=True)
                        continue
                    if not entry.isfile and entry.filetype not in (0, None):
                        _reject_type(entry.pathname, "special entry")
                    # filetype 0: no Unix type recorded (e.g. RAR made on Windows) — written as a plain file
                    declared = entry.size if entry.size and entry.size > 0 else None
                    t = target(name)
                    if t.exists():
                        raise ConversionError("unsafe_input", f"This archive contains “{name[:80]}” more than once.")
                    t.parent.mkdir(parents=True, exist_ok=True)
                    n = 0
                    with t.open("wb") as f:
                        for block in entry.get_blocks():
                            n += len(block)
                            lim.add(len(block), n, None, declared)
                            f.write(block)
                    files.append((name, t))
    except ConversionError:
        raise
    except (zipfile.BadZipFile, tarfile.TarError, EOFError, gzip.BadGzipFile) as e:
        raise ConversionError("corrupt_input", f"This {FORMATS[fmt].label} archive is damaged or truncated.") from e
    except NotImplementedError as e:
        raise ConversionError("unsupported_input", "This archive uses a compression or encryption method we can't read "
                                                   "(for example AES-encrypted ZIP).") from e
    except tarfile.FilterError as e:
        raise ConversionError("unsafe_input", "This archive contains an entry that isn't safe to unpack.") from e
    except Exception as e:
        msg = str(e).lower()
        if "passphrase" in msg or "password" in msg or "encrypt" in msg:
            raise ConversionError("password_required" if not password else "wrong_password",
                                  "This archive is password-protected — enter its password to continue." if not password
                                  else "That password is incorrect, or this archive's encryption isn't supported.") from e
        if type(e).__module__.startswith(("libarchive", "py7zr", "lzma", "_lzma", "bz2", "_bz2", "zlib")) or isinstance(e, (OSError, ValueError)):
            raise ConversionError("corrupt_input", f"This {FORMATS[fmt].label} archive is damaged, truncated, or uses "
                                                   "features we can't read.") from e
        raise
    ctx.info.update(entries=lim.count, unpacked_bytes=lim.bytes)
    return files


def pack(ctx: Ctx, files: list[tuple[str, Path]], fmt: str, out: Path) -> None:
    n = len(files)
    if fmt == "zip":
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for k, (name, p) in enumerate(files):
                ctx.progress(k, n, stage=f"Packing {k + 1} of {n}")
                z.write(p, name)
    elif fmt in ("tar", "tgz", "tbz2", "txz"):
        mode = {"tar": "w", "tgz": "w:gz", "tbz2": "w:bz2", "txz": "w:xz"}[fmt]
        with tarfile.open(out, mode, format=tarfile.PAX_FORMAT) as t:
            for k, (name, p) in enumerate(files):
                ctx.progress(k, n, stage=f"Packing {k + 1} of {n}")
                info = t.gettarinfo(str(p), arcname=name)
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                with p.open("rb") as f:
                    t.addfile(info, f)
    elif fmt == "7z":
        import py7zr

        with py7zr.SevenZipFile(out, "w") as z:
            for k, (name, p) in enumerate(files):
                ctx.progress(k, n, stage=f"Packing {k + 1} of {n}")
                z.write(p, name)
    else:
        raise ConversionError("unsupported", f"Can't create {fmt} archives.")
    ctx.progress(n, n, stage="Packed", force=True)


class ArchiveOptions(Options):
    password: str | None = Field(None, max_length=256, title="Archive password",
                                 description="Only needed if the archive is password-protected.",
                                 json_schema_extra=ui(widget="password", advanced=True))


def repack(ctx: Ctx) -> None:
    o: ArchiveOptions = ctx.options  # type: ignore[assignment]
    ctx.stage("Unpacking")
    files = extract_all(ctx, ctx.input.path, ctx.input.format, ctx.work_dir / "x", o.password)
    if not files:
        raise ConversionError("empty_archive", "This archive has no files in it.")
    out = ctx.default_out()
    pack(ctx, files, ctx.target, out)
    ctx.notice(f"Repacked {len(files):,} file{'s' if len(files) != 1 else ''}.")
    ctx.add_output(out)


_REPACK = tuple((s, t) for s in ARCHIVES for t in ARCHIVES if s != t) + tuple(("rar", t) for t in ARCHIVES)

register(Operation(
    id="archive.convert", category="archives", label="Convert archive",
    description="Repack an archive into another format. Every entry is checked before it's unpacked.",
    inputs=READABLE, outputs=ARCHIVES, cardinality="one_to_one", options=ArchiveOptions, run=repack,
    engines=("py7zr",), format_engines={"rar": ("libarchive",), "7z": ("libarchive",)}, heavy_over_mb=50,
    explicit_pairs=_REPACK,
    pair_support={("rar", t): "partial" for t in ARCHIVES},
    pair_limitations={("rar", t): ("RAR is read-only here (libarchive); some RAR5 features such as encryption may fail.",)
                      for t in ARCHIVES},
    limitations=("Links, device files, absolute paths and “..” paths are refused; size, entry-count and compression-ratio "
                 "limits apply.",),
    keywords=("zip", "tar", "7z", "rar", "compress", "unzip"),
))


def extract(ctx: Ctx) -> None:
    o: ArchiveOptions = ctx.options  # type: ignore[assignment]
    ctx.stage("Unpacking")
    files = extract_all(ctx, ctx.input.path, ctx.input.format, ctx.out_dir / "files", o.password)
    if not files:
        raise ConversionError("empty_archive", "This archive has no files in it.")
    for name, p in files:
        fmt = format_from_extension(name) or "bin"
        ctx.add_output(p, fmt, label=name, name=PurePosixPath(name).name, allow_empty=True)
    ctx.notice(f"Unpacked {len(files):,} file{'s' if len(files) != 1 else ''}. Download them one by one, or all as a ZIP.")


register(Operation(
    id="archive.extract", category="archives", label="Extract files",
    description="Open an archive, see what's inside, and download the files one by one or all together.",
    inputs=(*READABLE,), outputs=(), cardinality="one_to_many", options=ArchiveOptions, run=extract,
    engines=("py7zr",), format_engines={"rar": ("libarchive",), "7z": ("libarchive",)}, heavy_over_mb=50,
    explicit_pairs=tuple((f, f) for f in READABLE), slug="extract",
    pair_support={("rar", "rar"): "partial"},
    pair_limitations={("rar", "rar"): ("RAR is read-only here (libarchive); some RAR5 features such as encryption may fail.",)},
    keywords=("unzip", "unrar", "open archive", "list contents"),
))


# ---------------------------------------------------------------------------
# create ZIP / gzip / gunzip


ANY = tuple(f for f in FORMATS if f != "bin")


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        base, dot, ext = n.rpartition(".")
        cand = n
        while cand in seen:
            seen[n] = seen.get(n, 1) + 1
            cand = f"{base} ({seen[n]}).{ext}" if dot else f"{n} ({seen[n]})"
        seen[cand] = 1
        out.append(cand)
    return out


class CreateZipOptions(Options):
    level: Literal["store", "normal", "max"] = Field("normal", title="Compression",
                                                     description="store: no compression (fastest; best for photos/videos).")


def create_zip(ctx: Ctx) -> None:
    o: CreateZipOptions = ctx.options  # type: ignore[assignment]
    names = _unique([PurePosixPath(i.name).name or f"file{i.index + 1}.{FORMATS[i.format].ext}" for i in ctx.inputs])
    out = ctx.default_out("zip")
    comp = zipfile.ZIP_STORED if o.level == "store" else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(out, "w", compression=comp, compresslevel=9 if o.level == "max" else 6) as z:
        for k, (inp, name) in enumerate(zip(ctx.inputs, names)):
            ctx.progress(k, len(names), stage=f"Adding file {k + 1} of {len(names)}")
            z.write(inp.path, name)
    ctx.add_output(out, "zip")


register(Operation(
    id="archive.create_zip", category="archives", label="Create ZIP",
    description="Put your files into a single ZIP archive.", inputs=ANY, outputs=("zip",), cardinality="many_to_one",
    options=CreateZipOptions, run=create_zip, max_inputs=100, slug="create-zip", keywords=("zip files", "bundle", "compress"),
))


def gzip_file(ctx: Ctx) -> None:
    out = ctx.default_out("gz")
    name = (PurePosixPath(ctx.input.name).name or f"file.{FORMATS[ctx.input.format].ext}").encode("latin-1", "replace")
    with ctx.input.path.open("rb") as src, out.open("wb") as raw:
        with gzip.GzipFile(filename=name.decode("latin-1"), mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            shutil.copyfileobj(src, gz, CHUNK)
    ctx.add_output(out, "gz", name=(ctx.input.name or "file") + ".gz")


register(Operation(
    id="archive.gzip", category="archives", label="Compress with GZIP",
    description="Compress a single file to .gz.", inputs=tuple(f for f in ANY if f not in ("gz", "tgz")), outputs=("gz",),
    cardinality="one_to_one", options=NoOptions, run=gzip_file, slug="gzip",
    keywords=("gz", "compress"),
))


def gunzip(ctx: Ctx) -> None:
    lim = Limits(ctx)
    lim.entry()
    with ctx.input.path.open("rb") as raw:
        head = raw.read(10)
        fname = ""
        if len(head) == 10 and head[3] & 0x08:  # FNAME present
            buf = bytearray()
            while (b := raw.read(1)) and b != b"\x00" and len(buf) < 1024:
                buf += b
            fname = buf.decode("latin-1", "replace")
    base = PurePosixPath(fname.replace("\\", "/")).name if fname else ""
    if not base:
        base = ctx.input.name[:-3] if ctx.input.name.lower().endswith(".gz") else "file"
    out = ctx.out_path("decompressed.bin")
    m = Member(base, False, None, ctx.input.size)
    try:
        with gzip.open(ctx.input.path, "rb") as src:
            _copy(src, out, m, lim)
    except (OSError, EOFError) as e:
        raise ConversionError("corrupt_input", "This .gz file is damaged or truncated.") from e
    fmt = format_from_extension(base) or "bin"
    ctx.add_output(out, fmt, label=base, name=base, allow_empty=True)


register(Operation(
    id="archive.gunzip", category="archives", label="Decompress GZIP",
    description="Get the original file back out of a .gz file.", inputs=("gz",), outputs=(), cardinality="one_to_many",
    options=NoOptions, run=gunzip, explicit_pairs=(("gz", "gz"),), slug="gunzip",
    keywords=("gz", "decompress", "extract"),
))
