#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <sidecar-directory> <entitlements.plist>" >&2
  exit 2
fi

sidecar_dir="$1"
entitlements="$2"
executable="$sidecar_dir/screamingface-runtime"
signing_identity="${APPLE_SIGNING_IDENTITY:--}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Skipping sidecar signing: codesign is only available on macOS"
  exit 0
fi
if [[ ! -x "$executable" ]]; then
  echo "Sidecar executable not found at $executable" >&2
  exit 1
fi
if [[ ! -f "$entitlements" ]]; then
  echo "Entitlements file not found at $entitlements" >&2
  exit 1
fi

echo "Signing PyInstaller sidecar with identity: $signing_identity"
while IFS= read -r -d '' candidate; do
  if [[ "$candidate" != "$executable" ]] && file "$candidate" | grep -q "Mach-O"; then
    codesign --force --options runtime --entitlements "$entitlements" \
      --sign "$signing_identity" "$candidate"
  fi
done < <(find "$sidecar_dir" -type f -print0)

# Sign the outer executable last so its signature covers the finalized onedir contents.
codesign --force --options runtime --entitlements "$entitlements" \
  --sign "$signing_identity" "$executable"
codesign --verify --strict --verbose=2 "$executable"
echo "Sidecar signing complete"
