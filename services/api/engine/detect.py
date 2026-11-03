"""Content-based format detection.

Binary formats: magic bytes, then a look inside ambiguous containers
(ZIP → OOXML/ODF/EPUB, OLE2 → DOC/XLS/PPT, ISO-BMFF → ftyp brand, RIFF,
EBML, ASF). Audio/video are confirmed with ffprobe (sandboxed, demuxer
whitelist, file protocol only).

Text formats: charset-normalizer, then parse attempts (JSON, XML/SVG/HTML,
YAML, CSV/TSV). Markdown and TXT go by extension.

If extension and content disagree, content wins and a warning is returned.
"""

from __future__ import annotations

import bz2
import csv
import gzip
import io
import json
import lzma
import re
import shutil
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import sandbox
from .formats import FORMATS, TEXT_FAMILY, format_from_extension

HEAD = 8192


@dataclass
class Detection:
    format: str | None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    info: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# binary signatures


def _iso_bmff(head: bytes) -> str | None:
    if head[4:8] != b"ftyp":
        return None
    size = int.from_bytes(head[0:4], "big")
    major = head[8:12]
    compat = {head[i : i + 4] for i in range(16, min(size, len(head)), 4)}
    brands = {major} | compat
    if major in (b"avif", b"avis"):
        return "avif"
    if major in (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"):
        if major in (b"mif1", b"msf1") and (b"avif" in brands or b"avis" in brands):
            return "avif"
        return "heic"
    if major in (b"M4A ", b"M4B ", b"M4P "):
        return "m4a"
    if major == b"qt  ":
        return "mov"
    if major[:3] in (b"3gp", b"3g2"):
        return "3gp"
    return "mp4"


def _zip_kind(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "mimetype" in names:
                mt = z.read("mimetype")[:100].decode("ascii", "replace").strip()
                return {
                    "application/vnd.oasis.opendocument.text": "odt",
                    "application/vnd.oasis.opendocument.spreadsheet": "ods",
                    "application/vnd.oasis.opendocument.presentation": "odp",
                    "application/epub+zip": "epub",
                }.get(mt, "zip")
            if "[Content_Types].xml" in names:
                if any(n.startswith("word/") for n in names):
                    return "docx"
                if any(n.startswith("xl/") for n in names):
                    return "xlsx"
                if any(n.startswith("ppt/") for n in names):
                    return "pptx"
            return "zip"
    except (zipfile.BadZipFile, OSError, ValueError):
        return "zip"


def _ole_kind(path: Path) -> tuple[str | None, str | None]:
    import olefile

    try:
        with olefile.OleFileIO(str(path)) as ole:
            streams = {"/".join(s) for s in ole.listdir()}
    except Exception:
        return None, "This Office file is damaged and can't be read."
    if "EncryptionInfo" in streams or "EncryptedPackage" in streams:
        return None, "This Office file is password-protected. Remove the password in Office and upload it again."
    if "WordDocument" in streams:
        return "doc", None
    if "Workbook" in streams or "Book" in streams:
        return "xls", None
    if "PowerPoint Document" in streams:
        return "ppt", None
    return None, "This looks like an old Office/OLE file of a type we don't support."


def _compressed_tar(head: bytes, path: Path, opener) -> bool:
    try:
        with opener(path) as f:
            block = f.read(512)
        return len(block) >= 262 and block[257:262] == b"ustar"
    except Exception:
        return False


def _mp3_or_aac(head: bytes) -> str | None:
    if head[:3] == b"ID3":
        return "mp3"
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        layer = (head[1] >> 1) & 0x3
        return "aac" if layer == 0 else "mp3"
    return None


def _binary(head: bytes, path: Path) -> tuple[str | None, str | None]:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", None
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg", None
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif", None
    if head[:2] == b"BM" and len(head) > 14:
        return "bmp", None
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff", None
    if head[:4] == b"\x00\x00\x01\x00" and len(head) > 6 and head[4:6] != b"\x00\x00":
        return "ico", None
    if head[:4] == b"RIFF":
        return {b"WEBP": "webp", b"WAVE": "wav", b"AVI ": "avi"}.get(head[8:12], None), None
    if (k := _iso_bmff(head)) is not None:
        return k, None
    if b"%PDF-" in head[:1024]:
        return "pdf", None
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return _zip_kind(path), None
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return _ole_kind(path)
    if head[:5] == b"{\\rtf":
        return "rtf", None
    if head[:6] == b"7z\xbc\xaf\x27\x1c":
        return "7z", None
    if head[:7] == b"Rar!\x1a\x07":
        return "rar", None
    if head[:2] == b"\x1f\x8b":
        return ("tgz" if _compressed_tar(head, path, gzip.open) else "gz"), None
    if head[:3] == b"BZh":
        return ("tbz2" if _compressed_tar(head, path, bz2.open) else None), (
            None if _compressed_tar(head, path, bz2.open) else "Standalone .bz2 files aren't supported; only .tar.bz2 archives."
        )
    if head[:6] == b"\xfd7zXZ\x00":
        return ("txz" if _compressed_tar(head, path, lzma.open) else None), (
            None if _compressed_tar(head, path, lzma.open) else "Standalone .xz files aren't supported; only .tar.xz archives."
        )
    if len(head) >= 262 and head[257:262] == b"ustar":
        return "tar", None
    if head[:4] == b"fLaC":
        return "flac", None
    if head[:4] == b"OggS":
        if b"OpusHead" in head[:256]:
            return "opus", None
        if b"\x01vorbis" in head[:256]:
            return "ogg", None
        return None, "This Ogg file doesn't contain Vorbis or Opus audio."
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return ("webm" if b"webm" in head[:64] else "mkv"), None
    if head[:3] == b"FLV":
        return "flv", None
    if head[:16] == bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c"):
        return "wmv", None  # refined to wma by ffprobe when there's no video
    if head[:4] in (b"\x00\x01\x00\x00", b"true"):
        return "ttf", None
    if head[:4] == b"OTTO":
        return "otf", None
    if head[:4] == b"wOFF":
        return "woff", None
    if head[:4] == b"wOF2":
        return "woff2", None
    if (k := _mp3_or_aac(head)) is not None:
        return k, None
    return None, None


# ---------------------------------------------------------------------------
# text


def _decode_text(path: Path, size: int) -> str | None:
    from charset_normalizer import from_bytes

    data = path.read_bytes() if size <= 16 * 1024 * 1024 else path.open("rb").read(16 * 1024 * 1024)
    if b"\x00" in data[:HEAD] and not (data[:2] in (b"\xff\xfe", b"\xfe\xff")):
        return None
    if not data:
        return ""
    best = from_bytes(data[: 2 * 1024 * 1024]).best()
    if best is None:
        return None
    try:
        return data.decode(best.encoding)
    except (UnicodeDecodeError, LookupError):
        return str(best)


_XML_ROOT = re.compile(r"<(?!\?|!)([A-Za-z_][\w:.-]*)")


def _text_kind(text: str, ext_fmt: str | None) -> str:
    stripped = text.lstrip("﻿ \t\r\n")
    if ext_fmt in ("md", "txt", "sql", "css", "js") and not stripped.startswith(("{", "[", "<")):
        return ext_fmt
    if stripped[:1] in ("{", "["):
        try:
            json.loads(stripped)
            return "json"
        except ValueError:
            pass
    if stripped.startswith("<"):
        low = stripped[:2048].lower()
        if low.startswith("<!doctype html") or re.search(r"<html[\s>]", low):
            return "html"
        m = _XML_ROOT.search(stripped[:4096])
        if m and m.group(1).split(":")[-1].lower() == "svg":
            return "svg"
        from defusedxml import ElementTree as DET

        try:
            DET.fromstring(stripped.encode("utf-8"), forbid_dtd=False)
            return "xml"
        except Exception:
            if re.search(r"<(body|head|div|p|span|table)[\s>]", low):
                return "html"
            if ext_fmt == "xml":
                return "xml"
    if ext_fmt == "toml":
        try:
            tomllib.loads(stripped)
            return "toml"
        except tomllib.TOMLDecodeError:
            pass
    if ext_fmt in ("yaml",):
        import yaml

        try:
            yaml.safe_load(stripped)
            return "yaml"
        except yaml.YAMLError:
            pass
    if ext_fmt in ("csv", "tsv") or ext_fmt is None:
        sample = stripped[:16384]
        lines = [ln for ln in sample.splitlines() if ln.strip()]
        if len(lines) >= 2:
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
                cols = {len(r) for r in csv.reader(io.StringIO("\n".join(lines[:20])), dialect)}
                if len(cols) == 1 and cols.pop() >= 2:
                    return "tsv" if dialect.delimiter == "\t" else "csv"
            except csv.Error:
                pass
        if ext_fmt in ("csv", "tsv"):
            return ext_fmt
    if ext_fmt is None and re.search(r"^[\w.-]+:\s", stripped, re.M):
        import yaml

        try:
            if isinstance(yaml.safe_load(stripped), (dict, list)):
                return "yaml"
        except yaml.YAMLError:
            pass
    if ext_fmt in ("md", "txt", "html", "rtf", "sql", "css", "js"):
        return ext_fmt
    return "txt"


# ---------------------------------------------------------------------------
# ffprobe confirmation

AV_DEMUXERS = "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi,flv,asf,wav,mp3,aac,flac,ogg,gif,image2,png_pipe"


def ffprobe(path: Path, job_dir: Path, timeout_s: float = 20) -> dict | None:
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    res = sandbox.run_sync(
        [exe, "-v", "error", "-protocol_whitelist", "file", "-format_whitelist", AV_DEMUXERS,
         "-show_format", "-show_streams", "-of", "json", str(path)],
        job_dir=job_dir,
        limits=sandbox.Limits(timeout_s=timeout_s, memory_mb=1024),
    )
    if not res.ok:
        return None
    try:
        return json.loads(res.stdout or b"{}")
    except ValueError:
        return None


_AV_FAMILY = {"audio", "video"}


def _refine_av(fmt: str, probe: dict) -> tuple[str | None, str | None]:
    streams = probe.get("streams", [])
    has_video = any(s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1 for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if not has_video and not has_audio:
        return None, "This file has no audio or video streams we can read."
    if fmt == "wmv" and not has_video:
        return "wma", None
    if fmt in ("mp4",) and not has_video:
        return "m4a", None
    if fmt == "webm" and not has_video:
        return "webm", None
    if fmt == "mkv" and not has_video:
        return "mkv", None
    return fmt, None


# ---------------------------------------------------------------------------


_EQUIVALENT = [{"txt", "md", "log"}, {"tgz", "gz"}, {"html", "xml"}, {"xml", "svg"}, {"mp4", "m4a", "mov", "3gp"}, {"mkv", "webm"},
               {"ttf", "otf"}, {"heic", "avif"}, {"csv", "tsv", "txt"}, {"wmv", "wma"}, {"ogg", "opus"}]


def _compatible(a: str, b: str) -> bool:
    return a == b or any(a in s and b in s for s in _EQUIVALENT)


def detect(path: Path, original_name: str, *, probe_dir: Path | None = None) -> Detection:
    size = path.stat().st_size
    ext_fmt = format_from_extension(original_name)
    if size == 0:
        return Detection(None, error="This file is empty.")
    with path.open("rb") as f:
        head = f.read(HEAD)

    fmt, err = _binary(head, path)
    if err:
        return Detection(None, error=err)
    det = Detection(fmt)

    if fmt is None:
        text = _decode_text(path, size)
        if text is None:
            return Detection(None, error="We couldn't identify this file's format from its content.")
        det.format = _text_kind(text, ext_fmt)

    assert det.format is not None
    if FORMATS[det.format].family in _AV_FAMILY:
        probe = ffprobe(path, probe_dir or path.parent)
        if probe is None:
            return Detection(None, error=f"This {FORMATS[det.format].label} file is damaged or truncated and can't be read.")
        refined, perr = _refine_av(det.format, probe)
        if perr:
            return Detection(None, error=perr)
        det.format = refined
        fmt_info = probe.get("format", {})
        try:
            det.info["duration_s"] = float(fmt_info.get("duration", 0) or 0)
        except ValueError:
            pass
        det.info["streams"] = [
            {k: s.get(k) for k in ("codec_type", "codec_name", "width", "height", "sample_rate", "channels")}
            for s in probe.get("streams", [])
        ]

    if ext_fmt and not _compatible(ext_fmt, det.format):
        det.warnings.append(
            f"The file extension says {FORMATS[ext_fmt].label}, but the content is {FORMATS[det.format].label}. "
            f"We'll treat it as {FORMATS[det.format].label}."
        )
    elif ext_fmt is None and det.format not in TEXT_FAMILY:
        pass
    return det
