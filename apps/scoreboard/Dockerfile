# INVARIANT: the builder and runtime Python minor MUST match. The runtime copies the builder's
# venv wholesale (the two `COPY --from=builder` lines below, entered via
# PATH=/app/apps/scoreboard/.venv/bin), and a venv is version-keyed — site-packages lives under
# lib/python<X.Y>/ and pyvenv.cfg names the interpreter that built it. A mismatch builds fine and
# then dies at import with ModuleNotFoundError.
# AIDEV-NOTE: Dependabot CANNOT keep these two in step. They are different images
# (ghcr.io/astral-sh/uv vs python) and it does not even recognise the uv tag as version-bearing,
# so grouping cannot pair them — proven by #490, which moved the runtime alone. It did the same to
# url4-cloud in #439. Base-image bumps here always need a human.
# AIDEV-NOTE: this app's CI does NOT build the image, so unlike url4-cloud there is no smoke step
# to catch a mismatch — it would surface at deploy. Treat edits here with corresponding care.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# FEATURE: OME-1307 (E14) — the system registry fingerprints url4 text with `packages/url4`.
# INVARIANT: the build context is the REPO ROOT, not this dir. pyproject.toml path-depends on
# `url4` (../../packages/url4), which is outside this app's directory, so an app-scoped context
# cannot see it and `uv sync` fails. The repo layout is mirrored under /app so the editable
# install's relative paths stay valid at runtime (same pattern as
# apps/screamingface-engine/Dockerfile).
# All path dependencies must exist before `uv sync` resolves the lockfile.
COPY packages/url4 ./packages/url4
COPY apps/scoreboard/pyproject.toml apps/scoreboard/uv.lock ./apps/scoreboard/

WORKDIR /app/apps/scoreboard

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY apps/scoreboard/src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# Must track the builder's Python minor exactly — see the INVARIANT at the top of this file.
FROM python:3.13-slim-bookworm AS runtime

LABEL org.opencontainers.image.source="https://github.com/ScreamingFace/screamingface" \
      org.opencontainers.image.description="ScreamingFace benchmark scoreboard" \
      org.opencontainers.image.licenses="MIT"

ENV SCOREBOARD_HOST=0.0.0.0 \
    SCOREBOARD_PORT=9106 \
    SCOREBOARD_PORTAL_DIR=/app/web/portal \
    SCOREBOARD_PORTAL_ARTIFACTS_DIR=/app/web/artifacts \
    PATH="/app/apps/scoreboard/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/apps/scoreboard

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin scoreboard

# INVARIANT: same absolute layout as the builder — the editable `url4` install resolves through
# these paths.
COPY --from=builder --chown=scoreboard:scoreboard /app/packages/url4 /app/packages/url4
COPY --from=builder --chown=scoreboard:scoreboard /app/apps/scoreboard /app/apps/scoreboard
COPY --chown=scoreboard:scoreboard apps/scoreboard/portal /app/web/portal
COPY --chown=scoreboard:scoreboard apps/scoreboard/artifacts/livetruth-latest.jsonl /app/web/artifacts/livetruth-latest.jsonl
COPY --chown=scoreboard:scoreboard apps/scoreboard/artifacts/livetruth-latest.eval.jsonl /app/web/artifacts/livetruth-latest.eval.jsonl
COPY --chown=scoreboard:scoreboard apps/scoreboard/artifacts/livetruth-masking.dataset.jsonl /app/web/artifacts/livetruth-masking.dataset.jsonl

USER scoreboard

EXPOSE 9106

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9106/healthz', timeout=3).read()" || exit 1

ENTRYPOINT ["scoreboard"]
