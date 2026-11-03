"""Format catalog: every file format the platform knows about.

A format id is the canonical lowercase name used everywhere (registry pairs,
API, UI routes). `exts[0]` is the extension written on outputs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Format:
    id: str
    label: str
    family: str  # image | document | pdf | spreadsheet | presentation | audio | video | archive | data | font | text
    exts: tuple[str, ...]
    mime: str

    @property
    def ext(self) -> str:
        return self.exts[0]


_F = Format
FORMATS: dict[str, Format] = {
    f.id: f
    for f in [
        # images
        _F("png", "PNG", "image", ("png",), "image/png"),
        _F("jpg", "JPG", "image", ("jpg", "jpeg", "jpe", "jfif"), "image/jpeg"),
        _F("webp", "WebP", "image", ("webp",), "image/webp"),
        _F("gif", "GIF", "image", ("gif",), "image/gif"),
        _F("bmp", "BMP", "image", ("bmp", "dib"), "image/bmp"),
        _F("tiff", "TIFF", "image", ("tiff", "tif"), "image/tiff"),
        _F("ico", "ICO", "image", ("ico",), "image/vnd.microsoft.icon"),
        _F("avif", "AVIF", "image", ("avif",), "image/avif"),
        _F("heic", "HEIC", "image", ("heic", "heif", "hif"), "image/heic"),
        _F("svg", "SVG", "image", ("svg",), "image/svg+xml"),
        # documents
        _F("pdf", "PDF", "pdf", ("pdf",), "application/pdf"),
        _F("docx", "Word (DOCX)", "document", ("docx",), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        _F("doc", "Word 97-2003 (DOC)", "document", ("doc",), "application/msword"),
        _F("odt", "OpenDocument Text", "document", ("odt",), "application/vnd.oasis.opendocument.text"),
        _F("rtf", "RTF", "document", ("rtf",), "application/rtf"),
        _F("txt", "Plain text", "text", ("txt", "text", "log"), "text/plain"),
        _F("md", "Markdown", "text", ("md", "markdown"), "text/markdown"),
        _F("html", "HTML", "text", ("html", "htm"), "text/html"),
        _F("epub", "EPUB", "document", ("epub",), "application/epub+zip"),
        # spreadsheets
        _F("xlsx", "Excel (XLSX)", "spreadsheet", ("xlsx",), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        _F("xls", "Excel 97-2003 (XLS)", "spreadsheet", ("xls",), "application/vnd.ms-excel"),
        _F("ods", "OpenDocument Spreadsheet", "spreadsheet", ("ods",), "application/vnd.oasis.opendocument.spreadsheet"),
        _F("csv", "CSV", "data", ("csv",), "text/csv"),
        _F("tsv", "TSV", "data", ("tsv", "tab"), "text/tab-separated-values"),
        # data
        _F("json", "JSON", "data", ("json",), "application/json"),
        _F("xml", "XML", "data", ("xml",), "application/xml"),
        _F("yaml", "YAML", "data", ("yaml", "yml"), "application/yaml"),
        _F("toml", "TOML", "data", ("toml",), "application/toml"),
        _F("sql", "SQL", "data", ("sql",), "application/sql"),
        _F("css", "CSS", "text", ("css",), "text/css"),
        _F("js", "JavaScript", "text", ("js", "mjs", "cjs"), "text/javascript"),
        # presentations
        _F("pptx", "PowerPoint (PPTX)", "presentation", ("pptx",), "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        _F("ppt", "PowerPoint 97-2003 (PPT)", "presentation", ("ppt",), "application/vnd.ms-powerpoint"),
        _F("odp", "OpenDocument Presentation", "presentation", ("odp",), "application/vnd.oasis.opendocument.presentation"),
        # audio
        _F("mp3", "MP3", "audio", ("mp3",), "audio/mpeg"),
        _F("wav", "WAV", "audio", ("wav",), "audio/wav"),
        _F("aac", "AAC", "audio", ("aac",), "audio/aac"),
        _F("flac", "FLAC", "audio", ("flac",), "audio/flac"),
        _F("ogg", "OGG Vorbis", "audio", ("ogg", "oga"), "audio/ogg"),
        _F("m4a", "M4A", "audio", ("m4a",), "audio/mp4"),
        _F("opus", "Opus", "audio", ("opus",), "audio/ogg; codecs=opus"),
        _F("wma", "WMA", "audio", ("wma",), "audio/x-ms-wma"),
        # video
        _F("mp4", "MP4", "video", ("mp4", "m4v"), "video/mp4"),
        _F("mov", "MOV", "video", ("mov", "qt"), "video/quicktime"),
        _F("mkv", "MKV", "video", ("mkv",), "video/x-matroska"),
        _F("webm", "WebM", "video", ("webm",), "video/webm"),
        _F("avi", "AVI", "video", ("avi",), "video/x-msvideo"),
        _F("flv", "FLV", "video", ("flv",), "video/x-flv"),
        _F("wmv", "WMV", "video", ("wmv",), "video/x-ms-wmv"),
        _F("3gp", "3GP", "video", ("3gp", "3g2"), "video/3gpp"),
        # archives
        _F("zip", "ZIP", "archive", ("zip",), "application/zip"),
        _F("tar", "TAR", "archive", ("tar",), "application/x-tar"),
        _F("tgz", "TAR.GZ", "archive", ("tar.gz", "tgz"), "application/gzip"),
        _F("tbz2", "TAR.BZ2", "archive", ("tar.bz2", "tbz2", "tbz"), "application/x-bzip2"),
        _F("txz", "TAR.XZ", "archive", ("tar.xz", "txz"), "application/x-xz"),
        _F("7z", "7Z", "archive", ("7z",), "application/x-7z-compressed"),
        _F("gz", "GZ", "archive", ("gz",), "application/gzip"),
        _F("rar", "RAR", "archive", ("rar",), "application/vnd.rar"),
        # fonts
        _F("ttf", "TrueType font", "font", ("ttf",), "font/ttf"),
        _F("otf", "OpenType font", "font", ("otf",), "font/otf"),
        _F("woff", "WOFF", "font", ("woff",), "font/woff"),
        _F("woff2", "WOFF2", "font", ("woff2",), "font/woff2"),
        # generic output type for files extracted from archives (never an upload/detection result)
        _F("bin", "File", "other", ("bin",), "application/octet-stream"),
    ]
}

# Text-like formats that may be reasonably interchanged by extension.
TEXT_FAMILY = {"txt", "md", "csv", "tsv", "json", "xml", "yaml", "toml", "html", "svg"}


def format_from_extension(name: str) -> str | None:
    lower = name.lower()
    # longest-suffix match so ".tar.gz" beats ".gz"
    best: tuple[int, str] | None = None
    for f in FORMATS.values():
        for ext in f.exts:
            if lower.endswith("." + ext) and (best is None or len(ext) > best[0]):
                best = (len(ext), f.id)
    return best[1] if best else None


def get(fid: str) -> Format:
    return FORMATS[fid]
