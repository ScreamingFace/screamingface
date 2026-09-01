#!/usr/bin/env bash
set -euo pipefail

runtime_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$runtime_dir"

sidecar_pyinstaller_cache="${PYINSTALLER_CONFIG_DIR:-${TMPDIR:-/tmp}/screamingface-pyinstaller}"
export PYINSTALLER_CONFIG_DIR="$sidecar_pyinstaller_cache"

uv sync --frozen
.venv/bin/pyinstaller --clean --noconfirm screamingface-runtime.spec

echo "Built $runtime_dir/dist/screamingface-runtime/screamingface-runtime"
