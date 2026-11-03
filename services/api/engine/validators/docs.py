"""Document validators: open the output with an independent parser and check known content."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from . import check, magic


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def pdf_text(path: Path, password: str | None = None) -> tuple[int, str]:
    from pypdf import PdfReader

    r = PdfReader(str(path))
    if r.is_encrypted:
        r.decrypt(password or "")
    return len(r.pages), _norm(" ".join(p.extract_text() or "" for p in r.pages))


def validate_pdf(path: Path, *, pages: int | None = None, contains: list[str] = (), password: str | None = None) -> None:
    magic(path, "pdf")
    n, text = pdf_text(path, password)
    if pages is not None:
        check(n == pages, f"expected {pages} pages, got {n}")
    for c in contains:
        check(_norm(c) in text, f"PDF text missing {c!r}: {text[:300]!r}")


def docx_text(path: Path) -> str:
    from docx import Document

    d = Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return _norm(" ".join(parts))


def odf_text(path: Path) -> str:
    from odf import teletype
    from odf.opendocument import load
    from odf.text import H, P

    doc = load(str(path))
    return _norm(" ".join(teletype.extractText(p) for kind in (H, P) for p in doc.getElementsByType(kind)))


def doc_text(path: Path) -> str:
    import olefile

    with olefile.OleFileIO(str(path)) as ole:
        check(ole.exists("WordDocument"), "no WordDocument stream")
        streams = b"".join(ole.openstream(s).read() for s in ("WordDocument", "1Table", "0Table") if ole.exists(s))
    return _norm(streams.decode("utf-16-le", "ignore") + " " + streams.decode("latin-1", "ignore"))


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_text(path: Path) -> str:
    p = _Text()
    p.feed(path.read_text(encoding="utf-8"))
    return _norm(" ".join(p.parts))


def validate_document(path: Path, fmt: str, contains: list[str]) -> None:
    if fmt == "pdf":
        return validate_pdf(path, contains=contains)
    if fmt == "docx":
        magic(path, "zip")
        text = docx_text(path)
    elif fmt == "odt":
        magic(path, "zip")
        text = odf_text(path)
    elif fmt == "doc":
        text = doc_text(path)
    elif fmt == "rtf":
        raw = path.read_text(encoding="latin-1")
        check(raw.startswith("{\\rtf"), "not RTF")
        text = _norm(raw)
    elif fmt == "html":
        text = html_text(path)
    elif fmt in ("md", "txt"):
        text = _norm(path.read_text(encoding="utf-8").replace("\\", ""))
    else:
        raise AssertionError(f"no validator for {fmt}")
    for c in contains:
        check(_norm(c) in text, f"{fmt} output missing {c!r}: {text[:300]!r}")
