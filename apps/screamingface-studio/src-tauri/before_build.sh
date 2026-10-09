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

target_triple="${TAURI_ENV_TARGET_TRIPLE:-$(rustc -vV | awk '/^host:/ { print $2 }')}"
if [[ "$target_triple" == *-apple-* ]]; then
  # PyInstaller also includes standalone Python binaries. The copied Python.framework is
  # redundant, and cp -RL dereferences its internal symlinks into an ambiguous bundle that
  # codesign and Apple's notarization service reject.
  rm -rf "$tauri_runtime/_internal/Python.framework"
  "$studio_root/runtime/sign-sidecar.sh" \
    "$tauri_runtime" "$studio_root/src-tauri/entitlements.plist"
fi

# FEATURE (spec D10): every benchmark dataset ships inside the app, read-only, and Tauri passes
# the folder to `up --benchmark-assets-dir`. `prepare` runs from the sidecar's build venv: the
# frozen sidecar cannot start the `python -m` preparer children that `prepare` spawns. The frozen
# sidecar then lists the bundles, so its own fingerprints decide whether they count as prepared.
# The build cache keeps already-prepared bundles, so only the first build downloads (~2 min).
benchmark_data="$studio_root/runtime/build/benchmark-data"
"$studio_root/runtime/.venv/bin/screamingface" prepare --data-dir "$benchmark_data" --all
bundle_status="$("$tauri_runtime/screamingface-runtime" prepare --data-dir "$benchmark_data" --list)"
if grep -qv ' prepared$' <<<"$bundle_status"; then
  echo "Benchmark datasets are not all prepared; refusing to bundle a partial set:" >&2
  echo "$bundle_status" >&2
  exit 1
fi
rsync -a --delete "$benchmark_data/benchmark-assets/" "$tauri_runtime/benchmark-assets/"

npm run --prefix "$studio_root/frontend" build
