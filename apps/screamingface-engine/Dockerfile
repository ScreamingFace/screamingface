# syntax=docker/dockerfile:1.7
# screamingface-engine image — ONE artifact, TWO modes (`screamingface_engine.cli`):
#   screamingface-engine serve   the control plane: mints tokens, upgrades REST→WS, schedules Runner Jobs
#   screamingface-engine run     one url4 evaluation, streamed to NATS, then exit — what a Job runs
#
# This replaces the former pair of images. The run mode's dependencies were already a strict
# subset of the serving mode's, so a single image costs no new package — only the serving-side
# ones now sitting unused on a Job's disk. `.claude/scripts/check_layering.py` keeps the two
# halves' IMPORT graphs disjoint, which is what actually holds a Job's cold start down.
#
# INVARIANT: the build context is the REPO ROOT, not this dir:
#   docker build -f apps/screamingface-engine/Dockerfile -t screamingface-engine:dev .
# WHY: pyproject.toml path-depends on `url4` (../../packages/url4), which carries both the
# `url4.streaming` wire contract and the engine, and is outside this app's directory, so an
# app-scoped context cannot see it and `uv sync` fails. The repo layout is mirrored under /app so
# the editable install's relative paths stay valid at runtime.
#
# The runtime shape matches BOTH the helm chart's securityContext (deploy/helm/values.yaml) and
# what the runner pool's Deployment hardens each worker pod with: non-root uid/gid 1000 owning
# the venv, `runAsNonRoot: true`-compatible, read-only rootfs, tini as PID 1 so a drain or a
# stop tears a run down promptly with a clean SIGTERM.
# INVARIANT: the builder and runtime Python minor MUST match. The runtime copies the builder's
# venv wholesale (see the COPY below), and a venv is version-keyed — site-packages lives under
# lib/python<X.Y>/ and pyvenv.cfg names the interpreter that built it. A mismatch builds fine and
# then dies at import with `ModuleNotFoundError: No module named 'screamingface_engine'`.
# AIDEV-NOTE: Dependabot CANNOT keep these two in step — they are different images
# (ghcr.io/astral-sh/uv vs python), so no grouping setting pairs them, and it will happily bump
# one alone. It did exactly that in #439. Base-image bumps on this file always need a human.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# All path dependencies must exist before `uv sync` resolves the lockfile.
COPY packages/url4 ./packages/url4
COPY apps/screamingface-engine/pyproject.toml apps/screamingface-engine/uv.lock ./apps/screamingface-engine/
WORKDIR /app/apps/screamingface-engine
# Deps first (cache-friendly): busts only when pyproject/lock change.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
# Now the app source (siblings above are already in place).
COPY apps/screamingface-engine/src ./src
COPY apps/screamingface-engine/url4.toml ./url4.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Must track the builder's Python minor exactly — see the INVARIANT above.
FROM python:3.13-slim-bookworm AS runtime
LABEL org.opencontainers.image.title="screamingface-engine" \
      org.opencontainers.image.source="https://github.com/ScreamingFace/screamingface" \
      org.opencontainers.image.description="screamingface-engine — REST + WebSocket control plane and url4 run mode"
RUN apt-get update && apt-get install -y --no-install-recommends tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -g 1000 app && useradd -u 1000 -g 1000 -M -d /app app
WORKDIR /app/apps/screamingface-engine
# INVARIANT: same absolute layout as the builder — editable installs resolve through these paths.
COPY --from=builder --chown=1000:1000 /app/packages/url4 /app/packages/url4
COPY --from=builder --chown=1000:1000 /app/apps/screamingface-engine /app/apps/screamingface-engine
# The DECLARED world both serving discovery and run mode consume (`screamingface_engine.world_config`,
# DEFAULT_CONFIG_PATH). Endpoints are declared here, never discovered from the gateway catalog —
# the image decides what CAN exist. URL4_RUNNER_CONFIG overrides the path; a read-only rootfs is
# fine, it is read once per process at boot.
COPY --from=builder --chown=1000:1000 /app/apps/screamingface-engine/url4.toml /etc/url4/url4.toml
ENV PATH="/app/apps/screamingface-engine/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER 1000
EXPOSE 9108
ENTRYPOINT ["tini", "--"]
# Serving is the default mode, which is what keeps the chart's `command: [url4-cloud]` working.
# The runner pool overrides it with `["screamingface-engine", "worker"]` (deployment-runner.yaml),
# and the worker's children exec `screamingface-engine run` (worker/exec_wrapper.py).
# INVARIANT: AIGATEWAY_BASE_URL is NOT baked here — it reaches each worker pod from the chart's
# runner-env ConfigMap, so the endpoint follows the deployment, not the artifact (§9).
CMD ["url4-cloud"]
