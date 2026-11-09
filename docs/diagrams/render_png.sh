#!/bin/sh
# Renders sf-client-0-1-11-*.svg to PNG with headless Microsoft Edge (or Chrome).
BROWSER="${BROWSER:-/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge}"
cd "$(dirname "$0")" || exit 1
for f in sf-client-0-1-11-*.svg screamingface-request-architecture-*.svg; do
  w=$(sed -n 's/.*viewBox="0 0 \([0-9]*\) \([0-9]*\)".*/\1/p' "$f" | head -1)
  h=$(sed -n 's/.*viewBox="0 0 \([0-9]*\) \([0-9]*\)".*/\2/p' "$f" | head -1)
  "$BROWSER" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
    --window-size="$w,$h" --screenshot="${f%.svg}.png" "file://$PWD/$f" >/dev/null 2>&1
done
