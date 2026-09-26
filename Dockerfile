# UGC Studio: one image for the API and the GPU worker.
# Model weights, projects and tool environments live in volumes (see docker-compose.yml), not in the image.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    UGC_MODELS=/data/models \
    UGC_OUTPUTS=/data/outputs \
    UGC_VENDOR=/data/vendor \
    HF_HOME=/data/hf \
    PATH=/app/.venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git build-essential nodejs npm libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /usr/local/bin/

WORKDIR /app
# 1. Python dependencies (cached layer): the LTX-2 packages are path dependencies of the project
COPY pyproject.toml uv.lock ./
COPY vendor/LTX-2 vendor/LTX-2
RUN uv python install 3.12 && uv sync --frozen --no-dev --no-install-project
# 2. the app
COPY README.md ./
COPY src src
RUN uv sync --frozen --no-dev
# 3. motion-graphics assets and the headless browser
RUN cd src/ugc_studio/motion && npm ci --no-audit --no-fund \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["entrypoint.sh"]
CMD ["ugc", "serve", "--host", "0.0.0.0", "--port", "8000", "--no-worker"]
