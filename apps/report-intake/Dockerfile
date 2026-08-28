# INVARIANT: the builder and runtime Python minor MUST match. The runtime copies the builder's
# venv wholesale (`COPY --from=builder /app /app`, entered via PATH=/app/.venv/bin), and a venv is
# version-keyed — site-packages lives under lib/python<X.Y>/ and pyvenv.cfg names the interpreter
# that built it. A mismatch builds fine and then dies at import with ModuleNotFoundError.
# AIDEV-NOTE: Dependabot CANNOT keep these two in step. They are different images
# (ghcr.io/astral-sh/uv vs python) and it does not even recognise the uv tag as version-bearing,
# so grouping cannot pair them — it moved the runtime alone in #490 and #439. Base-image bumps
# here always need a human.
# Unlike aigateway and scoreboard, THIS app's CI builds the image and starts it (see
# report-intake-tests.yml's `image` job), so a mismatch fails a PR instead of a deploy.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY apps/report-intake/pyproject.toml apps/report-intake/uv.lock /app/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY apps/report-intake/src /app/src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# Must track the builder's Python minor exactly — see the INVARIANT at the top of this file.
FROM python:3.13-slim-bookworm AS runtime

LABEL org.opencontainers.image.source="https://github.com/openmined/screamingface" \
      org.opencontainers.image.description="ScreamingFace report-intake service" \
      org.opencontainers.image.licenses="MIT"

ENV REPORT_INTAKE_HOST=0.0.0.0 \
    REPORT_INTAKE_PORT=9109 \
    REPORT_INTAKE_DATABASE_URL=sqlite:///data/report-intake.sqlite3 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# /data, not /app: the service user needs ONE writable directory and it must not be the one
# holding the venv it executes. `WORKDIR` creates /app as root and `COPY --chown` only re-owns
# the copied contents, not the directory itself — so the default database path used to be one
# the service user could not create a file in. That failed in a way worth naming: the sqlite
# client raises while opening, tortoise-orm 1.1.8 leaves its connection lock held (see
# reports/store.py's STORAGE_TIMEOUT_S), and /readyz HUNG instead of answering 503. Caught by
# this app's image job, which is the argument for having one.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin report-intake \
    && install -d -o report-intake -g report-intake /data

COPY --from=builder --chown=report-intake:report-intake /app /app

USER report-intake

EXPOSE 9109

# /healthz, never /readyz: this is the container's liveness signal, and readiness fails closed
# until `tortoise migrate` has been run against this container's database — this service never
# migrates itself (see Settings.database_url). A HEALTHCHECK on /readyz would mark a container
# unhealthy for the entirely normal state of "deployed, schema not applied yet".
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9109/healthz', timeout=3).read()" || exit 1

ENTRYPOINT ["report-intake"]
