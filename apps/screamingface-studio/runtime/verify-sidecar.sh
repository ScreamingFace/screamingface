#!/usr/bin/env bash
set -euo pipefail

runtime_dir="$(cd "$(dirname "$0")" && pwd)"
executable="$runtime_dir/dist/screamingface-runtime/screamingface-runtime"
verification_dir="$(mktemp -d "${TMPDIR:-/tmp}/screamingface-sidecar.XXXXXX")"
runtime_log="$verification_dir/runtime.log"
runtime_pid=""

cleanup() {
  if [[ -n "$runtime_pid" ]] && kill -0 "$runtime_pid" 2>/dev/null; then
    kill -TERM -- "-$runtime_pid" 2>/dev/null || true
    wait "$runtime_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ ! -x "$executable" ]]; then
  echo "Sidecar executable not found at $executable. Run ./build-sidecar.sh first." >&2
  exit 1
fi

"$runtime_dir/.venv/bin/python" -c \
  'import os, sys; os.chdir(sys.argv[1]); os.setpgrp(); os.execv(sys.argv[2], sys.argv[2:])' \
  "$verification_dir" "$executable" --data-dir "$verification_dir/data" up --foreground \
  >"$runtime_log" 2>&1 &
runtime_pid=$!

ready=false
for _ in {1..180}; do
  if grep -q 'SCREAMINGFACE_RUNTIME_READY ' "$runtime_log"; then
    ready=true
    break
  fi
  if ! kill -0 "$runtime_pid" 2>/dev/null; then
    cat "$runtime_log" >&2
    wait "$runtime_pid"
  fi
  sleep 0.5
done

if [[ "$ready" != true ]]; then
  cat "$runtime_log" >&2
  echo "Sidecar readiness timed out" >&2
  exit 1
fi

for service_url in \
  http://127.0.0.1:9105/healthz \
  http://127.0.0.1:9106/healthz \
  http://127.0.0.1:9108/healthz; do
  curl -fsS "$service_url" >/dev/null
done
model_count="$(
  curl -fsS http://127.0.0.1:9108/v1/models |
    "$runtime_dir/.venv/bin/python" -c \
      'import json, sys; models = json.load(sys.stdin).get("data", []); assert models; print(len(models))'
)"
echo "SCREAMINGFACE_RUNTIME_SMOKE_OK models=$model_count"

kill -TERM -- "-$runtime_pid"
wait "$runtime_pid" || true
runtime_pid=""

ports_released=false
for _ in {1..300}; do
  ports_released=true
  for port in 9105 9106 9108; do
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null; then
      ports_released=false
      break
    fi
  done
  if [[ "$ports_released" == true ]]; then
    break
  fi
  sleep 0.1
done

if [[ "$ports_released" != true ]]; then
  cat "$runtime_log" >&2
  echo "Runtime ports are still listening after sidecar shutdown" >&2
  exit 1
fi

echo "SCREAMINGFACE_SIDECAR_VERIFY_OK data_dir=$verification_dir"
