# Local catalog performance harness

Run from this worktree's root. Requires the scoreboard .venv, Node, Playwright and
installed Chrome. No production writes. Capture makes three normal public homepage
loads. Raw public response bodies are saved locally.

```sh
export PLAYWRIGHT_MODULE=/path/to/node_modules/playwright
node docs/spec/benchmark-catalog-summary/evidence/capture.cjs
# Start a disposable PostgreSQL instance at 127.0.0.1:55462; create catalog_perf.
export CATALOG_PERF_DB=postgres://filip@127.0.0.1:55462/catalog_perf
apps/scoreboard/.venv/bin/python docs/spec/benchmark-catalog-summary/evidence/seed.py
SCOREBOARD_DATABASE_URL="$CATALOG_PERF_DB" apps/scoreboard/.venv/bin/python -m uvicorn scoreboard.main:create_app --factory --host 127.0.0.1 --port 8773
# In another shell:
node docs/spec/benchmark-catalog-summary/evidence/compare.cjs
apps/scoreboard/.venv/bin/python docs/spec/benchmark-catalog-summary/evidence/server_timings.py
node docs/spec/benchmark-catalog-summary/evidence/smoke.cjs
```

Seed requires a fresh database and rejects nonlocal URLs. server_timings.py expects
exactly the 21 captured top rows, adds synthetic lower-ranked rows, measures, then
removes those synthetic rows. Do not run measurements concurrently with other local
load tests. Read docs/work/2026-11-03-benchmark-catalog-performance.md for assumptions.

The committed live.json.gz is the original public response snapshot. Capture replaces it
with a fresh one; skip capture to reproduce against the recorded snapshot.

The comparison reads baseline HTML and JavaScript from Git commit
`ffdc7e93f8f17e7622db0148c51982eca1e6a720`; that commit must exist locally
(use a full clone). No duplicate baseline source files are maintained. The small
public fixture and screenshots stay versioned for reproducibility; PR links use
commit hashes so deleting the branch does not break the evidence.
