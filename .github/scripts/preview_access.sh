#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'Preview access failed: %s\n' "$1" >&2
  exit 1
}

pr_number="${1:-}"
[[ "$pr_number" =~ ^[1-9][0-9]*$ ]] || {
  printf 'Usage: preview_access.sh PULL_REQUEST_NUMBER\n' >&2
  exit 2
}

for required_command in cloudflared curl gh install kubectl mktemp; do
  command -v "$required_command" >/dev/null 2>&1 || \
    fail "install $required_command and try again"
done

readonly kubeconfig_url="https://kube-pr-${pr_number}.preview.dev.screamingface.ai/kubeconfig"
readonly kubeconfig_path="${PREVIEW_KUBECONFIG:-/tmp/sf-preview-pr-${pr_number}.kubeconfig}"
temporary_kubeconfig="$(mktemp "/tmp/sf-preview-pr-${pr_number}.kubeconfig.XXXXXX")"
trap 'rm -f "$temporary_kubeconfig"' EXIT

access_token=""
if ! access_token="$(cloudflared access token --app="$kubeconfig_url" 2>/dev/null)" || \
  [[ -z "$access_token" ]]; then
  printf 'Complete the Cloudflare login in your browser.\n' >&2
  cloudflared access login --quiet "$kubeconfig_url" 1>&2
  access_token="$(cloudflared access token --app="$kubeconfig_url")"
fi
[[ -n "$access_token" ]] || fail "Cloudflare returned no access token"

if ! github_token="$(gh auth token 2>/dev/null)" || [[ -z "$github_token" ]]; then
  fail "run gh auth login and try again"
fi

if ! {
  printf 'header = "cf-access-token: %s"\n' "$access_token"
  printf 'header = "X-Preview-Access-Token: %s"\n' "$access_token"
  printf 'header = "X-GitHub-Token: %s"\n' "$github_token"
  printf 'output = "%s"\n' "$temporary_kubeconfig"
  printf 'url = "%s"\n' "$kubeconfig_url"
} | curl \
  --fail-with-body \
  --silent \
  --show-error \
  --location \
  --max-redirs 0 \
  --config -; then
  fail "the protected kubeconfig request was refused"
fi

kubectl config view \
  --kubeconfig "$temporary_kubeconfig" \
  --minify \
  >/dev/null || fail "the server returned an invalid kubeconfig"

install -m 600 "$temporary_kubeconfig" "$kubeconfig_path"
printf '%s\n' "$kubeconfig_path"
