#!/usr/bin/env bash
# Plain bash harness for src-tauri/before_build.sh. It copies the script into a scratch Studio
# tree whose sidecar build, signing, dataset preparation, and frontend build are stubs, so the
# dataset bundling logic runs without PyInstaller, codesign, network, or npm.
set -euo pipefail

real_script="$(cd "$(dirname "$0")/.." && pwd)/before_build.sh"
bundles=(draco ifeval healthbench gdpval medxpert contracteval)
failures=0
scratch="$(mktemp -d "${TMPDIR:-/tmp}/before-build-test.XXXXXX")"
trap 'rm -rf "$scratch"' EXIT

make_studio() {
  local studio="$1"
  mkdir -p "$studio/src-tauri" "$studio/runtime/.venv/bin" "$studio/frontend" "$studio/bin"
  cp "$real_script" "$studio/src-tauri/before_build.sh"
  touch "$studio/src-tauri/entitlements.plist"

  cat >"$studio/runtime/build-sidecar.sh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
dist="$(cd "$(dirname "$0")" && pwd)/dist/screamingface-runtime"
mkdir -p "$dist/_internal"
cat >"$dist/screamingface-runtime" <<'SIDECAR'
#!/usr/bin/env bash
# Stub frozen sidecar: answers `prepare --data-dir D --list` only.
[[ "$1" == "prepare" && "$2" == "--data-dir" && "$4" == "--list" ]] || exit 64
for name in draco ifeval healthbench gdpval medxpert contracteval; do
  if [[ "$name" == "${STUB_MISSING_BUNDLE:-}" ]]; then
    printf '%-12s missing\n' "$name"
  else
    printf '%-12s prepared\n' "$name"
  fi
done
SIDECAR
chmod +x "$dist/screamingface-runtime"
STUB

  cat >"$studio/runtime/.venv/bin/screamingface" <<'STUB'
#!/usr/bin/env bash
# Stub build-venv CLI: `prepare --data-dir D --all` writes one file per bundle.
set -euo pipefail
[[ "$1" == "prepare" && "$2" == "--data-dir" && "$4" == "--all" ]] || exit 64
echo "${HF_TOKEN:-<unset>}" >"$STUB_LOG_DIR/hf_token"
[[ -z "${STUB_PREPARE_FAILS:-}" ]] || exit 1
for name in draco ifeval healthbench gdpval medxpert contracteval; do
  mkdir -p "$3/benchmark-assets/$name"
  echo "$name" >"$3/benchmark-assets/$name/cases.json"
done
STUB

  cat >"$studio/runtime/sign-sidecar.sh" <<'STUB'
#!/usr/bin/env bash
touch "$STUB_LOG_DIR/signed"
STUB

  cat >"$studio/bin/npm" <<'STUB'
#!/usr/bin/env bash
touch "$STUB_LOG_DIR/frontend_built"
STUB
  chmod +x "$studio/runtime/build-sidecar.sh" "$studio/runtime/.venv/bin/screamingface" \
    "$studio/runtime/sign-sidecar.sh" "$studio/bin/npm"
}

# Runs the copied script; prints its exit status. Extra arguments are VAR=value overrides.
run_before_build() {
  local studio="$1"
  shift
  mkdir -p "$studio/log"
  set +e
  env PATH="$studio/bin:$PATH" STUB_LOG_DIR="$studio/log" \
    TAURI_ENV_TARGET_TRIPLE=aarch64-apple-darwin "$@" \
    bash "$studio/src-tauri/before_build.sh" >"$studio/log/output" 2>&1
  echo $?
  set -e
}

check() {
  local description="$1"
  shift
  if "$@"; then
    echo "ok   - $description"
  else
    echo "FAIL - $description"
    failures=$((failures + 1))
  fi
}

assets_of() {
  echo "$1/src-tauri/resources/screamingface-runtime/benchmark-assets"
}

all_bundles_copied() {
  local name
  for name in "${bundles[@]}"; do
    [[ -f "$(assets_of "$1")/$name/cases.json" ]] || return 1
  done
}

# Case 1: every bundle prepared -> success, all six copied, stale bundle removed, token passed.
studio="$scratch/all-prepared"
make_studio "$studio"
mkdir -p "$(assets_of "$studio")/retired-bundle"
status="$(run_before_build "$studio" HF_TOKEN=hf_test_token)"
check "exits 0 when every bundle is prepared" test "$status" -eq 0
check "copies all six bundles into the Tauri resources" all_bundles_copied "$studio"
check "removes a bundle that is no longer prepared" \
  test ! -e "$(assets_of "$studio")/retired-bundle"
check "passes HF_TOKEN through to prepare" \
  grep -qx hf_test_token "$studio/log/hf_token"
check "still copies the sidecar executable" \
  test -x "$studio/src-tauri/resources/screamingface-runtime/screamingface-runtime"
check "still builds the frontend" test -f "$studio/log/frontend_built"

# Case 2: a rebuild keeps the bundled folder in place while it replaces the sidecar.
status="$(run_before_build "$studio")"
check "a rebuild exits 0" test "$status" -eq 0
check "a rebuild keeps all six bundles" all_bundles_copied "$studio"

# Case 3: one bundle missing after prepare -> build error, nothing copied, no frontend build.
studio="$scratch/one-missing"
make_studio "$studio"
status="$(run_before_build "$studio" STUB_MISSING_BUNDLE=medxpert)"
check "exits non-zero when one bundle is missing" test "$status" -ne 0
check "names the missing bundle" grep -q medxpert "$studio/log/output"
check "copies no bundles when one is missing" test ! -e "$(assets_of "$studio")"
check "stops before the frontend build" test ! -e "$studio/log/frontend_built"

# Case 4: prepare itself fails -> build error.
studio="$scratch/prepare-fails"
make_studio "$studio"
status="$(run_before_build "$studio" STUB_PREPARE_FAILS=1)"
check "exits non-zero when prepare fails" test "$status" -ne 0
check "copies no bundles when prepare fails" test ! -e "$(assets_of "$studio")"

if [[ "$failures" -ne 0 ]]; then
  echo "$failures check(s) failed"
  exit 1
fi
echo "all before_build checks passed"
