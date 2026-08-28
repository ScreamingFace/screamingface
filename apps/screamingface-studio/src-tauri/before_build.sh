#!/usr/bin/env bash
set -euo pipefail

studio_root="$(cd "$(dirname "$0")/.." && pwd)"
runtime_dist="$studio_root/runtime/dist/screamingface-runtime"
tauri_runtime="$studio_root/src-tauri/resources/screamingface-runtime"

"$studio_root/runtime/build-sidecar.sh"

mkdir -p "$tauri_runtime"
rm -rf "$tauri_runtime/_internal" "$tauri_runtime/screamingface-runtime"
cp -RL "$runtime_dist/"* "$tauri_runtime/"
chmod +x "$tauri_runtime/screamingface-runtime"

npm run --prefix "$studio_root/frontend" build
