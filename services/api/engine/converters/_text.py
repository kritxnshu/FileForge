"""Shared text decoding for text-based inputs."""

from __future__ import annotations

from ..context import ConversionError


def decode(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is None:
            raise ConversionError("corrupt_input", "We couldn't work out this file's text encoding.") from None
        return str(best)
