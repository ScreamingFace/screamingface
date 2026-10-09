---
ticket: OME-1434
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-08
finished: 2026-10-08
---

# e14-b1-gateway-frozen-copy — AI Gateway frozen copy store, capture on chat, replay endpoints

## Intent

E14 (OME-1307) needs a run to be reproducible without the cache. A run that opts in opens a frozen
copy in the AI Gateway. The gateway stores every chat request and its response (cache hit, live
success or final error) in that copy. The engine also stores web-tool results. After the copy is
sealed, replay endpoints answer the same requests with the same shape as `/v1/chat/completions`,
with no credential, no provider and no cache. Design: `02-frozen-copy-design.md` §3, §4, §9.

## Planned changes

- `src/aigateway/core/frozen_copy/__init__.py`, `models.py`: `FrozenCopy`, `FrozenCopyEntry`.
- `src/aigateway/core/frozen_copy/store.py`: `FrozenCopyStore`.
- `src/aigateway/db.py`: register the new model package.
- `src/aigateway/migrations/0014_frozen_copies.py`: the two tables.
- `src/aigateway/config.py`: `frozen_copy_max_entry_bytes`.
- `src/aigateway/routes/frozen_copies.py`: the five routes; included in `main.py` next to `chat.router`.
- `src/aigateway/routes/chat.py`: capture hook and the shared body-preparation helper.
- `tests/unit/test_frozen_copy_*.py`: new files only.

## Test plan

TDD order from the plan (risk order):
1. replay never resolves credentials or calls a provider.
2. capture and replay digest match for the same body.
3. a cache hit and a live success are captured with the same shape.
4. a capture failure never fails the call.
5. capture is refused for an unknown, foreign or sealed copy, and for a stream.
6. a provider error is captured and replayed with the same status and detail.
7. replay lookup rule (occurrence n, past the end, latest error, miss).
8. replay of an open or unknown copy is 404 unavailable.
9. replay body reports zero cost and marks `frozen_copy_replay`.
10. seal is owner-only, idempotent, counts entries; capture after seal is refused.
11. tool results round trip; sealed gives 409; non-owner gives 404.
12. an entry over the size cap is `failed`, not stored.
13. no capture without the header (no new header, no row).
14. the migration applies on SQLite; model and migration match.

## Acceptance

- Design §3, §4, §9 behaviour holds for every row of the test plan.
- `uv run .claude/scripts/run_gates.py aigateway --base e14-reproducible-submission-spec` is green.
- Postgres-only tests are listed as skipped (no Docker on this machine).

## Approved test changes (append-only exception)

**Owner approval:** confirmed by the owner on 2026-10-08. The append-only gate may skip these edits.

- `apps/aigateway/tests/unit/test_migration_0012_provider_credential_slots.py::test_0012_downgrade_drops_only_the_marker_table`:
  one line changed, `_tortoise(url, "migrate")` to `_tortoise(url, "migrate", "models", _MIGRATION)`. The test assumed
  0012 is the newest migration, so any later migration that adds a table broke it. It now migrates to 0012 before
  it snapshots the schema. Nothing else in the test changed.
- Approval: orchestrator-approved under the owner's E14 authorization, to be confirmed by the owner.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `src/aigateway/core/frozen_copy/headers.py` (capture header constants and the request-state hand-off), `core/request_hardening.py` (now holds `prepare_ingress_body`), `main.py` and `unhandled_errors.py` (the two app handlers add the capture header), `tests/unit/test_frozen_copy_support.py` and `test_frozen_copy_store.py`, and the one-line approved test change above.
- **Commits:** see `git log --oneline e14-reproducible-submission-spec..HEAD`.
- **Gates (without `--skip-append-only`):** `✗ append-only test check` — only the approved line in `test_migration_0012_provider_credential_slots.py`; the runner stops there.
- **Gates (with `--skip-append-only`):** `✓ uv run ruff check`, `✓ uv run ruff format --check`, `✓ uv run pyright`, `✓ uv run python scripts/check_no_enterprise.py`, `✓ uv run pytest --cov=aigateway --cov-fail-under=80 -q`, `ALL GATES GREEN`.
- **Skipped tests:** 55 need Postgres (`AIGW_TEST_PG=1`), 21 are live provider tests (`AIGW_LIVE=1`). None is new. The Postgres row lock in `capture` and `seal` is not exercised.
- **Review round (F-B1 design review):** a non-dict success is `failed` and stamped; a mutation conflict (503) and an unexpected exception (generic 500) are captured and re-raised unchanged, the header reaching the response through the two app handlers; a replayed error has `detail` plus the zero-cost `_aigw` block with `frozen_copy_replay`; an empty `X-AIGW-Frozen-Copy` is `refused`; an inert capture never touches `exc.headers`; entries are ordered by a per-copy `seq` (`frozen_copies.entry_seq` counter, advanced under the copy-row lock; migration 0014 edited in place); one store accessor (`frozen_copy_store_for`) and one log helper (`log_capture_failure`); `prepare_ingress_body` moved to `core/request_hardening`; relative imports in `routes/frozen_copies.py`; unused `KIND_*` constants removed; a store or database failure on tool-results is 200 `failed`; a malformed copy id on replay and tool lookup is 404 `frozen_copy_unavailable`; `frozen_copies.account_id` is indexed.
- **Known limits:** the exclusive row lock on capture serialises inserts per copy (accepted). Entries are stored in JSON columns, so a `\u0000` character inside a request or response is not storable on Postgres: the capture is then `failed` and the run is `partial` (accepted).
- **Deviations:** none from the design. Decisions inside the plan, all accepted by the orchestrator: migration FK spelling as in 0012; zero-cost hit `_aigw` with top-level `frozen_copy_replay`; `frozen_copy_not_found` 404 code; no capture header on refusals before the copy check; row lock in store capture and seal; always-present capture object in `chat_completions` to stay inside the 76-statement limit.
