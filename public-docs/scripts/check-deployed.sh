#!/bin/sh
# Post-deploy check: every probe URL must answer 200 with the expected Content-Type, not the SPA fallback.
BASE="${1:-https://docs.screamingface.ai}"
fail=0
check() { # url expected-prefix
  ct=$(curl -s -o /dev/null -m 20 -A 'Mozilla/5.0' -w '%{http_code} %{content_type}' "$BASE$1")
  code=${ct%% *}; type=${ct#* }
  case "$type" in "$2"*) [ "$code" = 200 ] && echo "PASS $1 -> $ct" || { echo "FAIL $1 -> $ct"; fail=1; } ;; *) echo "FAIL $1 -> $ct (expected $2)"; fail=1 ;; esac
}
check /favicon.svg image/svg+xml
check /llms.txt text/plain
check /llms-full.txt text/plain
check /sf-client/installation.md text/markdown
check /sf-client/api/reducers.md text/markdown
exit $fail
