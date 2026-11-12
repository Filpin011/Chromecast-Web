# syntax=docker/dockerfile:1.7
# Chromecast Web — single image: Next.js static export served by the FastAPI backend.

############################
# 1) Frontend: static export
############################
FROM node:24-bookworm-slim AS frontend
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

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates tini fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt \
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
