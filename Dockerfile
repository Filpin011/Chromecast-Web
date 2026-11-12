# syntax=docker/dockerfile:1.7
# Chromecast Web — single image: Next.js static export served by the FastAPI backend.

############################
# 1) Frontend: static export
############################
# The static export is architecture-independent: build it natively on the build host (no QEMU) even when the
# image targets linux/arm64.
FROM --platform=$BUILDPLATFORM node:24-bookworm-slim AS frontend
WORKDIR /src/frontend
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Same origin in production: NEXT_PUBLIC_API_BASE stays empty.
RUN npm run build

############################
# 2) Runtime: Python + ffmpeg + Chromium
############################
FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.source="https://github.com/Filpin011/Chromecast-Web" \
      org.opencontainers.image.title="Chromecast Web" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates tini fonts-dejavu-core libatomic1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt ./
# yt-dlp's YouTube extractor needs a JavaScript runtime (deno) and the EJS challenge-solver scripts; without them it
# falls back to a deprecated JS-less client that can lose formats or stop working. The `default` + `pin-deno` extras
# of the yt-dlp version pinned in requirements.txt bring both, at the versions that yt-dlp release was tested with
# (yt-dlp-ejs, and the `deno` wheel, whose binary lands in /usr/local/bin where yt-dlp looks first). One resolver
# pass, so the extras' dependencies are checked against the rest of requirements.txt.
RUN YTDLP_VERSION="$(sed -n 's/^yt-dlp==\([^ ;#]*\).*/\1/p' requirements.txt)"; \
    if [ -z "$YTDLP_VERSION" ]; then echo "requirements.txt must pin yt-dlp==<version>" >&2; exit 1; fi; \
    pip install -r requirements.txt "yt-dlp[default,pin-deno]==${YTDLP_VERSION}" \
 && deno --version \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/* \
 && chmod -R a+rX /ms-playwright

COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-deps .

COPY --from=frontend /src/frontend/out /app/frontend

RUN useradd --create-home --uid 1000 app \
 && mkdir -p /data \
 && chown -R app:app /data

ENV CAST_DRIVER=pychromecast \
    HOST=0.0.0.0 \
    PORT=8000 \
    DATA_DIR=/data \
    FRONTEND_DIR=/app/frontend \
    ENABLE_PLAYWRIGHT=true

USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health', timeout=4).read()" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app"]
