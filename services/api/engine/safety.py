"""Process-wide safety settings for job processes + exception classification."""

from __future__ import annotations

import os


def max_image_pixels() -> int:
    return int(os.environ.get("MAX_IMAGE_PIXELS", "100000000"))


def apply_global_limits(limits: dict) -> None:
    from PIL import Image

    px = int(limits.get("max_image_pixels") or max_image_pixels())
    Image.MAX_IMAGE_PIXELS = px  # >px warns, >2*px raises; we turn the warning into an error below
    import warnings

    warnings.simplefilter("error", Image.DecompressionBombWarning)
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except Exception:
        pass


def classify_exception(e: BaseException) -> tuple[str, str]:
    name = type(e).__name__
    mod = type(e).__module__ or ""
    text = str(e).lower()
    try:
        from PIL import Image, UnidentifiedImageError

        if isinstance(e, (Image.DecompressionBombError, Image.DecompressionBombWarning)):
            return "too_many_pixels", (
                f"This image has more pixels than we allow ({max_image_pixels() // 1_000_000} megapixels). "
                "Resize it and try again."
            )
        if isinstance(e, UnidentifiedImageError):
            return "corrupt_input", "This image is damaged or in a format variant we can't read."
    except ImportError:
        pass
    if "password" in text or "encrypt" in text:
        return "password_required", "This file is password-protected — enter the password to continue."
    if isinstance(e, (EOFError,)) or "truncated" in text or "unexpected end" in text:
        return "corrupt_input", "This file is truncated or damaged and can't be converted."
    if mod.startswith(("pypdf", "pikepdf", "pypdfium2")):
        return "corrupt_input", "This PDF is damaged and can't be read."
    if mod.startswith(("zipfile", "openpyxl", "docx", "pptx", "xlrd")) or name in ("BadZipFile", "KeyError"):
        return "corrupt_input", "This file is damaged or isn't a valid document of its type."
    if isinstance(e, OSError) and getattr(e, "errno", None) == 27:  # EFBIG from RLIMIT_FSIZE
        return "too_large", "The converted output would be larger than we allow."
    if isinstance(e, (ValueError, OSError, SyntaxError)):
        return "corrupt_input", "This file is damaged or uses features we can't read."
    return "internal", "Something went wrong while converting this file. Try again, or try a different file."
