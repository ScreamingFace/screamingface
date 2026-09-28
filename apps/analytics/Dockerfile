# INVARIANT: builder and runtime Python minors match for the copied virtualenv.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY apps/analytics/pyproject.toml apps/analytics/uv.lock /app/
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/analytics/src /app/src
RUN uv sync --frozen --no-dev
FROM python:3.13-slim-bookworm
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ANALYTICS_HOST=0.0.0.0 ANALYTICS_PORT=9110
WORKDIR /app
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin analytics
COPY --from=builder /app /app
USER 10001:10001
EXPOSE 9110
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9110/healthz', timeout=2)"
ENTRYPOINT ["sf-analytics"]
