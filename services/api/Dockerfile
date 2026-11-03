# API + worker image (one image, three commands: api, worker-fast, worker-heavy).
# Build from the repo root:  docker build -f services/api/Dockerfile -t universal-converter-api .
#
# Engines: FFmpeg (Debian build: GPL, includes libx264), LibreOffice (MPL), Pandoc (GPL), Chromium (via Playwright),
# bsdtar, bubblewrap. All CLI engines run as separate processes (THIRD_PARTY_LICENSES.md).

FROM python:3.12-slim-bookworm

ARG TARGETARCH
ARG PANDOC_VERSION=3.6.4
# Optional engines: OCR (Tesseract + OCRmyPDF, ENABLE_OCR) and CJK fonts for office documents.
ARG WITH_OCR=false
ARG WITH_CJK_FONTS=false

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    PATH=/opt/venv/bin:$PATH \
    HOME=/tmp

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
        ffmpeg libarchive-tools libarchive13 bubblewrap \
        libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
        fonts-liberation2 fonts-dejavu-core fonts-noto-core fontconfig \
    && if [ "$WITH_CJK_FONTS" = "true" ]; then apt-get install -y --no-install-recommends fonts-noto-cjk; fi \
    && if [ "$WITH_OCR" = "true" ]; then apt-get install -y --no-install-recommends \
         tesseract-ocr tesseract-ocr-eng tesseract-ocr-deu tesseract-ocr-fra tesseract-ocr-spa tesseract-ocr-ita \
         tesseract-ocr-por tesseract-ocr-nld; fi \
    && curl -fsSL -o /tmp/pandoc.deb \
         "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-${TARGETARCH:-amd64}.deb" \
    && apt-get install -y /tmp/pandoc.deb && rm /tmp/pandoc.deb \
    && rm -rf /var/lib/apt/lists/*

# uv pinned to the version that writes services/api/uv.lock (COPY --from can't take a build arg)
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

WORKDIR /app
COPY services/api/pyproject.toml services/api/uv.lock ./
RUN uv sync --frozen --no-default-groups --no-install-project $( [ "$WITH_OCR" = "true" ] && echo "--group ocr" ) \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* /tmp/*

COPY services/api/ ./

# Unprivileged runtime user; job processes run as this user too.
RUN useradd --system --uid 10001 --home-dir /tmp --shell /usr/sbin/nologin app \
    && mkdir -p /data && chown app:app /data
USER app

ENV STORAGE_DIR=/data \
    REDIS_URL=redis://redis:6379/0 \
    TRUSTED_PROXY_HOPS=1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1
# Client IPs for rate limits come from X-Forwarded-For, trusting exactly TRUSTED_PROXY_HOPS proxies (app/security.py).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
