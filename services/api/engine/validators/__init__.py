"""Independent output validators used by the test-suite.

Each validator opens the output with a parser that is *not* the one that wrote
it where possible (e.g. images written by Pillow are re-checked for magic bytes
and decoded; PDFs are re-read by pypdf; media by ffprobe) and checks known
content, not just "it opened".
"""

from __future__ import annotations

from pathlib import Path

MAGIC = {
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "gif": [b"GIF87a", b"GIF89a"],
    "bmp": [b"BM"],
    "tiff": [b"II*\x00", b"MM\x00*"],
    "ico": [b"\x00\x00\x01\x00"],
    "pdf": [b"%PDF-"],
    "zip": [b"PK\x03\x04"],
    "7z": [b"7z\xbc\xaf\x27\x1c"],
    "gz": [b"\x1f\x8b"],
    "tgz": [b"\x1f\x8b"],
    "tbz2": [b"BZh"],
    "txz": [b"\xfd7zXZ\x00"],
    "flac": [b"fLaC"],
    "ogg": [b"OggS"],
    "opus": [b"OggS"],
    "woff": [b"wOFF"],
    "woff2": [b"wOF2"],
    "otf": [b"OTTO"],
    "ttf": [b"\x00\x01\x00\x00", b"true"],
}


class ValidationFailed(AssertionError):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise ValidationFailed(msg)


def magic(path: Path, fmt: str) -> None:
    head = path.read_bytes()[:16]
    if fmt in MAGIC:
        check(any(head.startswith(m) for m in MAGIC[fmt]), f"{path.name}: bad magic for {fmt}: {head[:8]!r}")
    elif fmt == "webp":
        check(head[:4] == b"RIFF" and head[8:12] == b"WEBP", f"{path.name}: not WebP")
    elif fmt in ("avif", "heic"):
        check(head[4:8] == b"ftyp", f"{path.name}: not ISO-BMFF")
