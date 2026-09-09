# OME-1141 — Implementation plan

1. Add deterministic tests driving both real reconnect loops with scripted socket
   outcomes and a local fake monotonic clock. Assert late-close recovery, cursor and
   capability reuse, exhausted outages, stable recovery, and no retry after abort.
2. Run new tests against unchanged production code and capture failures.
3. Add a private recovery-window object shared by both transports. Record successful
   attachment time; initialize/reset deadline and attempts only on a new outage.
4. Run new and existing reconnect tests, then the complete screamingface quality gates.
5. Review scope and invariants, update the ledger, commit, push, and open the PR.

Design: docs/spec/2026-09-09-OME-1141-reconnect-budget.md.
