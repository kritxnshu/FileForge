"""Neutralize external references in SVG and HTML before any engine renders them.

Both formats can make a renderer fetch URLs (SSRF, e.g. http://169.254.169.254) or
read local files (file:///etc/passwd). We parse with defusedxml (no DTDs, no
entities) and keep only same-document (#id) references and inline raster
`data:` images. Renderers are additionally run without network (sandbox) and,
for Chromium, with every request except data: aborted.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from defusedxml import ElementTree as DET

from .context import ConversionError

BLOCKED_TAGS = {"script", "foreignobject", "iframe", "object", "embed", "audio", "video", "handler", "listener", "link",
                "meta", "base"}
URL_ATTRS = {"href", "src", "xlink:href", "action", "formaction", "background", "poster", "data"}
SAFE_DATA = re.compile(r"^\s*data:image/(png|jpeg|jpg|gif|webp);base64,", re.I)
CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)
CSS_IMPORT = re.compile(r"@import[^;]*;?", re.I)


def _safe_ref(v: str) -> bool:
    v = v.strip()
    return v.startswith("#") or bool(SAFE_DATA.match(v))


def clean_css(css: str) -> tuple[str, int]:
    n = 0

    def repl(m: re.Match) -> str:
        nonlocal n
        if _safe_ref(m.group(2)):
            return m.group(0)
        n += 1
        return "none"

    css2, k = CSS_IMPORT.subn("", css)
    return CSS_URL.sub(repl, css2), n + k


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1].lower()


def sanitize_svg(data: bytes) -> tuple[str, int]:
    """Returns (safe SVG markup, number of references removed)."""
    try:
        root = DET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except Exception as e:
        raise ConversionError("corrupt_input", "This SVG isn't valid XML, or it uses DTDs/entities, which we don't allow.") from e
    if _local(root.tag) != "svg":
        raise ConversionError("corrupt_input", "This file doesn't have an <svg> root element.")
    removed = 0
    for parent in list(root.iter()):
        for child in list(parent):
            if isinstance(child.tag, str) and _local(child.tag) in BLOCKED_TAGS:
                parent.remove(child)
                removed += 1
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in list(el.attrib):
            local = _local(attr)
            val = el.attrib[attr]
            if local.startswith("on"):
                del el.attrib[attr]
                removed += 1
            elif local in URL_ATTRS or attr.endswith("}href"):
                if not _safe_ref(val):
                    del el.attrib[attr]
                    removed += 1
            elif local == "style" or ("url(" in val.lower()):
                el.attrib[attr], n = clean_css(val)
                removed += n
        if _local(el.tag) == "style" and el.text:
            el.text, n = clean_css(el.text)
            removed += n
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    return ET.tostring(root, encoding="unicode"), removed


def svg_size(markup: str) -> tuple[float, float] | None:
    root = ET.fromstring(markup)

    def num(v: str | None) -> float | None:
        if not v:
            return None
        m = re.match(r"^\s*([\d.]+)\s*(px|pt|mm|cm|in)?\s*$", v)
        if not m:
            return None
        f = float(m.group(1))
        return f * {"px": 1, None: 1, "pt": 96 / 72, "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96}[m.group(2)]

    w, h = num(root.get("width")), num(root.get("height"))
    if (w is None or h is None) and root.get("viewBox"):
        parts = re.split(r"[\s,]+", root.get("viewBox", "").strip())
        if len(parts) == 4:
            vw, vh = float(parts[2]), float(parts[3])
            if w is None and h is None:
                w, h = vw, vh
            elif w is None:
                w = h * vw / vh  # type: ignore[operator]
            else:
                h = w * vh / vw
    return (w, h) if w and h else None
