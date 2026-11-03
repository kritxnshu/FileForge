"""Headless Chromium for HTML/SVG → PDF, locked down against SSRF and local file reads.

* content is injected with `set_content` (never navigated to a URL)
* JavaScript disabled
* every request except `data:` URIs is aborted
* runs inside the job sandbox (no network at the OS level as well)
"""

from __future__ import annotations

from pathlib import Path

from .context import ConversionError


def html_to_pdf(html: str, out: Path, *, page_size: str | None = "A4", width: str | None = None, height: str | None = None,
                margin_mm: float = 12, landscape: bool = False, background: bool = True, timeout_s: float = 60) -> list[str]:
    from playwright.sync_api import Error as PwError
    from playwright.sync_api import sync_playwright

    blocked: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--disable-gpu", "--no-first-run", "--disable-extensions",
                                              "--disable-background-networking", "--dns-prefetch-disable"])
            try:
                ctx = browser.new_context(java_script_enabled=False, offline=False, bypass_csp=False,
                                          service_workers="block", accept_downloads=False)

                def route(r):
                    url = r.request.url
                    if url.startswith("data:"):
                        r.continue_()
                    else:
                        blocked.append(url[:200])
                        r.abort()

                ctx.route("**/*", route)
                page = ctx.new_page()
                page.set_default_timeout(timeout_s * 1000)
                page.set_content(html, wait_until="load")
                m = f"{margin_mm}mm"
                kw: dict = {"print_background": background, "margin": {"top": m, "bottom": m, "left": m, "right": m}}
                if width and height:
                    kw.update(width=width, height=height)
                else:
                    kw.update(format=page_size or "A4", landscape=landscape)
                page.pdf(path=str(out), **kw)
            finally:
                browser.close()
    except PwError as e:
        raise ConversionError("engine_error", "The page renderer couldn't lay out this file. It may be damaged or too large to render.") from e
    return blocked
