# Multi-stage build following the uv Docker guide: dependencies are installed from the lockfile
# in a builder image, and only the resulting virtualenv is copied into a slim runtime image.
#
#   docker build -t baskd .
#   docker run --rm -p 8000:8000 -e BASKD_PROVIDER=memory baskd
#   docker run --rm -p 8000:8000 --env-file .env -v "$PWD/secrets:/run/secrets/baskd:ro" \
#       -e BASKD_GOOGLE_CREDENTIALS_FILE=/run/secrets/baskd/service-account.json baskd

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Dependencies first (cached unless pyproject.toml / uv.lock change) ...
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# ... then the project itself, installed as a regular (non-editable) package.
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable


FROM python:3.12-slim-bookworm AS runtime

RUN groupadd --system app && useradd --system --gid app --create-home app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8000

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '8000') + '/health', timeout=2).status == 200 else 1)"

# Shell form so platforms that inject $PORT (Cloud Run, Render, ...) are honoured.
CMD ["sh", "-c", "exec uvicorn baskd.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
