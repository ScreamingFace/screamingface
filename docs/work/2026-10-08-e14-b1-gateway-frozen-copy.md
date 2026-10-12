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

## Rebase 2026-10-11

- The stack was rebased onto origin/main 8e0c0a298 (url4 2.0, OME-1503). B1 had no conflicts.
- CI `golden-replay` found a bug once capture became the default (B5). With auth disabled, the caller is the
  unsaved anonymous account. `POST /v1/frozen-copies` then failed with a 500: the `frozen_copies.account_id`
  foreign key names an account row that does not exist.
- Fix: `FrozenCopyStore.open` calls the existing `ensure_anonymous_account` before it creates the copy, as
  `writer_floor` does for the same case. New test:
  `test_the_anonymous_account_opens_a_copy_without_a_foreign_key_failure` (red first, with the same
  foreign key error).
- Gates: ruff, ruff format, pyright, pytest (5436 passed, 97 skipped).

## Review round 2026-10-12 (design review fixes)

- Source: plan `R-2026-10-12-design-review-fixes.md`, section B1. Design: `02-frozen-copy-design.md`,
  decisions Q25, Q27 and Q28, sections 3 and 4.1 to 4.4.
- Commit: `c001fc9f7 fix(aigateway): key frozen-copy entries by the call key (Q27, Q28)`.

### What changed

- A call has a key. The key is the case key (`X-AIGW-Case-Key`) and the occurrence
  (`X-AIGW-Call-Occurrence`). One parser, `parse_call_key`, reads both.
- Capture stores each entry under its key: case key, occurrence and request digest.
- Replay reads the exact key. The rule: the latest success at the key. If none, the latest
  error at the key. If none, a miss. There is no fallback to another occurrence or case key.
- A bad or missing key does this:
  - Chat capture: `X-AIGW-Capture: refused`. The call is still served.
  - Replay, tool-results capture and tool lookup: 400 `malformed_call_key`.
- Removed: `X-AIGW-Capture-Occurrence`, `X-AIGW-Replay-Occurrence`, `malformed_replay_occurrence`
  and the `seq` fallback for entries without a stated slot.
- Seal takes an optional body `{"provenance": {"engine_version": "<1 to 64 chars>"}}`. Any other
  key or bad value gives 422. The first seal keeps its provenance. A repeat seal does not change it.
- `Retry-After` is read in any header casing, with `_case_insensitive_header`.
- Migration 0014 is amended in place. The migration is not released.
  - `frozen_copy_entries`: `case_key` varchar(32) not null default `""`; `occurrence` int not null
    default 0.
  - Index: `(frozen_copy_id, kind, case_key, request_digest, occurrence, seq)`. The old index is gone.
  - `(frozen_copy_id, seq)` stays unique.
  - `frozen_copies`: `provenance` JSON, nullable.
- The model mirrors the migration. The `occurrence` comment is fixed.

### Approved test edits (by name)

These edits are in plan B1, approved on 2026-10-12.

- `test_frozen_copy_replay.py::test_replay_lookup_rule` is replaced by
  `test_replay_returns_the_latest_success_at_the_key_else_the_latest_error_else_miss`.
- `test_frozen_copy_replay.py::test_replay_occurrence_defaults_to_the_first_success` is deleted.
  A call with no key headers is a 400 now.
- `test_frozen_copy_replay.py::test_a_malformed_occurrence_is_a_400` is replaced by
  `test_bad_or_missing_key_headers_are_a_400_malformed_call_key`.
- `test_frozen_copy_store.py::test_replay_order_follows_seq_not_the_clock` keeps its name. It now
  checks the latest success at one key.
- `test_frozen_copy_store.py::test_replay_serves_by_stated_occurrence_not_completion_order` is
  deleted. Its check moves to `test_frozen_copy_replay.py::test_completion_order_does_not_change_replay`.
- `test_frozen_copy_store.py::test_a_reused_slot_keeps_one_success_and_the_error_falls_behind` is
  renamed `test_a_reused_key_keeps_the_latest_success_and_the_error_falls_behind`.
- `test_frozen_copy_store.py::test_a_digest_without_stated_slots_still_replays_in_completion_order`
  is deleted (no fallback).
- `test_frozen_copy_store.py::test_a_capture_occurrence_header_reads_as_absent_unless_usable` is
  turned into `test_a_bad_or_missing_call_key_is_malformed_not_absent`.
- `test_frozen_copy_routes.py::test_tool_lookup_follows_the_occurrence_rule` now uses keys. A
  call past the captured occurrences is a miss.
- `test_frozen_copy_routes.py::test_tool_lookup_rejects_a_malformed_occurrence` is replaced by
  `test_tool_lookup_rejects_a_bad_call_key_with_400`.
- `test_frozen_copy_migration.py::test_0014_creates_both_tables_with_the_design_columns` has the new
  column sets (`case_key`, `provenance`, and the nullable columns).

### Edits outside the approved list

- `test_frozen_copy_migration.py::test_0014_indexes_the_replay_lookup_in_capture_order` checks the
  new index columns. It also checks that `(frozen_copy_id, seq)` stays unique. The old index is
  removed by Q27.
- Key headers were added to requests that now need them. No assertion was weakened. Files:
  - `test_frozen_copy_capture.py`: the `_chat` helper and 11 replay posts.
  - `test_frozen_copy_replay.py`: every replay post.
  - `test_frozen_copy_routes.py`: the tool helper, the tool posts and one copy-header test.
  - `test_frozen_copy_store.py`: the `_replay` helper and the latest-error test.
  - Without these headers, the new 400 rule fails the tests before they reach their checks.
- `test_frozen_copy_support.py` gains `call_key`, `seed_keyed_copy` and the key constants. It is a
  helper module and holds no test.

### New tests

- `test_same_request_in_two_cases_replays_each_case_its_own_answer` (replay).
- `test_completion_order_does_not_change_replay` (replay).
- `test_replay_returns_the_latest_success_at_the_key_else_the_latest_error_else_miss` (replay, with
  the error at occurrence 0 and success at occurrence 1 case).
- `test_no_fallback_to_another_occurrence_or_case_key` (replay).
- Bad key headers, 400 on replay: `test_bad_or_missing_key_headers_are_a_400_malformed_call_key`.
- Bad key headers, 400 on tool lookup: `test_tool_lookup_rejects_a_bad_call_key_with_400`.
- Bad key headers, 400 on tool capture: `test_tool_results_capture_rejects_a_bad_call_key_with_400`.
- Bad key headers, refused on chat capture: `test_a_bad_or_missing_key_header_is_refused_and_the_call_is_still_served`.
  The bad values include `+3`, ` 3`, `1_0`, a non-ASCII digit, 10 digits and a missing occurrence.
- `test_tool_results_capture_and_lookup_use_the_key` (routes).
- `test_seal_stores_provenance_and_keeps_the_first` (routes).
- `test_a_seal_body_with_an_unknown_key_or_bad_value_is_422` (routes).
- `test_replay_occurrence_header_is_gone` (replay).
- `test_a_seal_without_a_body_stores_no_provenance` (routes, extra).
- `test_a_retry_after_in_any_header_casing_is_stored_under_its_name` (capture, extra).
- Migration: the column and index tests above, and the existing
  `test_autodetector_proposes_no_frozen_copy_change` (model and migration parity).

### Gate results

- `run_gates.py aigateway --base refs/e14-backup/pre-phase2-2026-10-12/OME-1307-e14-design-review`,
  append-only check on, before and after the commit: `✗ append-only test check`. The only flagged
  file is `tests/unit/test_migration_0012_provider_credential_slots.py` (approved line). The runner
  stops there.
- The same command with `--skip-append-only`: `✓ uv run ruff check`, `✓ uv run ruff format --check`,
  `✓ uv run pyright`, `✓ uv run python scripts/check_no_enterprise.py`,
  `✓ uv run pytest --cov=aigateway --cov-fail-under=80 -q`, `ALL GATES GREEN`.
- Direct full run of `uv run pytest -q`: 5499 passed, 0 failed, 101 skipped.
- Frozen-copy tests: all pass.
- `test_unknown_user_timing_close_to_wrong_password` passed in the full run. It was not run alone.
- Postgres migration apply: not run. No Postgres server is available in this session.

### Deviations

- One code commit (`c001fc9f7`) covers Q27 and Q28. The two changes share the migration, the models
  and the routes. A split by hunk needs interactive staging.
- `capture` takes `attempt=None, case_key="", occurrence=0`. The defaults match the model defaults.
  `find` has no defaults, as the plan says.
- `request_digest_prefix` and `log_capture_failure` take `attempt`. Without it, the log prefix of
  an Attempt 2 call would not match its digest.
- Seal: `provenance` is required inside the body. `{}` and `{"provenance": null}` give 422. The
  design names only the full form. See the open question below.
- On replay and tool routes, the key check runs before the copy check, as the old occurrence check
  did. A bad key on an unknown copy gives 400.
- On chat capture, the key check runs before the copy lookup. A bad key does no database read. The
  outcome is `refused` in both orders.

### Open question

- Should a seal body of `{}` mean "no provenance" (200), or stay 422? This build gives 422.
