"""Shared PDF helpers: password-aware opening and page-range parsing."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field

from ...context import ConversionError
from ...registry import Options, ui

PASSWORD_HINT = "This PDF is password-protected — enter its password under Advanced settings to continue."


class PdfPasswordOptions(Options):
    password: str | None = Field(None, title="PDF password", max_length=256,
                                 description="Only needed if the PDF is password-protected.",
                                 json_schema_extra=ui(widget="password", advanced=True))


def open_reader(path: Path, password: str | None):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        r = PdfReader(str(path), strict=False)
    except (PdfReadError, ValueError, OSError, KeyError) as e:
        raise ConversionError("corrupt_input", "This PDF is damaged and can't be read.") from e
    if r.is_encrypted:
        if password:
            if r.decrypt(password) == 0:
                raise ConversionError("wrong_password", "That password is incorrect for this PDF. Check it and try again.")
        elif r.decrypt("") == 0:
            raise ConversionError("password_required", PASSWORD_HINT)
    try:
        _ = len(r.pages)
    except Exception as e:
        raise ConversionError("corrupt_input", "This PDF is damaged and can't be read.") from e
    return r


def open_pike(path: Path, password: str | None):
    import pikepdf

    try:
        return pikepdf.open(str(path), password=password or "")
    except pikepdf.PasswordError as e:
        if password:
            raise ConversionError("wrong_password", "That password is incorrect for this PDF. Check it and try again.") from e
        raise ConversionError("password_required", PASSWORD_HINT) from e
    except pikepdf.PdfError as e:
        raise ConversionError("corrupt_input", "This PDF is damaged and can't be read.") from e


def open_pdfium(path: Path, password: str | None):
    import pypdfium2 as pdfium

    try:
        return pdfium.PdfDocument(str(path), password=password or None)
    except pdfium.PdfiumError as e:
        msg = str(e).lower()
        if "password" in msg:
            if password:
                raise ConversionError("wrong_password", "That password is incorrect for this PDF. Check it and try again.") from e
            raise ConversionError("password_required", PASSWORD_HINT) from e
        raise ConversionError("corrupt_input", "This PDF is damaged and can't be read.") from e


_RANGE = re.compile(r"^\s*(\d+|last)\s*(?:-\s*(\d+|last)\s*)?$", re.I)


def parse_ranges(spec: str | None, n: int, *, allow_empty: bool = True) -> list[int]:
    """'1-3,7,last' → zero-based indices. Empty/None → all pages."""
    if not spec or not spec.strip():
        if allow_empty:
            return list(range(n))
        raise ConversionError("invalid_option", "Enter the pages to use, e.g. 1-3,7.")
    out: list[int] = []
    for part in spec.split(","):
        if not part.strip():
            continue
        m = _RANGE.match(part)
        if not m:
            raise ConversionError("invalid_option", f"“{part.strip()}” isn't a valid page or range. Use a format like 1-3,7.")

        def num(v: str) -> int:
            return n if v.lower() == "last" else int(v)

        a = num(m.group(1))
        b = num(m.group(2)) if m.group(2) else a
        if a < 1 or b < 1 or a > n or b > n:
            raise ConversionError("invalid_option", f"Page {max(a, b)} doesn't exist — this PDF has {n} page{'s' if n != 1 else ''}.")
        step = 1 if b >= a else -1
        out.extend(range(a - 1, b - 1 + step, step))
    if not out:
        raise ConversionError("invalid_option", "No pages selected.")
    return out


RANGE_FIELD = dict(pattern=r"^[\d\s,\-lastLAST]*$", max_length=500)
