# INVARIANT: the builder and runtime Python minor MUST match. The runtime copies the builder's
# venv wholesale (`COPY --from=builder /app /app`, entered via PATH=/app/.venv/bin), and a venv is
# version-keyed — site-packages lives under lib/python<X.Y>/ and pyvenv.cfg names the interpreter
# that built it. A mismatch builds fine and then dies at import with ModuleNotFoundError.
# AIDEV-NOTE: Dependabot CANNOT keep these two in step. They are different images
# (ghcr.io/astral-sh/uv vs python) and it does not even recognise the uv tag as version-bearing,
# so grouping cannot pair them — proven by #491, which moved the runtime alone. It did the same to
# url4-cloud in #439. Base-image bumps here always need a human.
# AIDEV-NOTE: this app's CI does NOT build the image, so unlike url4-cloud there is no smoke step
# to catch a mismatch — it would surface at deploy. Treat edits here with corresponding care.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY apps/aigateway/pyproject.toml apps/aigateway/uv.lock /app/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY apps/aigateway/src /app/src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# Must track the builder's Python minor exactly — see the INVARIANT at the top of this file.
FROM python:3.13-slim-bookworm AS runtime

LABEL org.opencontainers.image.source="https://github.com/ScreamingFace/screamingface" \
      org.opencontainers.image.description="ScreamingFace AI Gateway" \
      org.opencontainers.image.licenses="MIT"

ENV AIGW_HOST=0.0.0.0 \
    AIGW_PORT=9105 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --system --uid 1000 --create-home app

COPY --from=builder --chown=app:app /app /app

USER app

EXPOSE 9105

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9105/healthz', timeout=3).read()" || exit 1

ENTRYPOINT ["aigateway"]
