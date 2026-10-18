---
ticket: OME-1646
status: implemented
date: 2026-10-16
spec: ../spec/2026-10-16-judge-redraw-live-only.md
---

# Plan — a recorded judge reply is final

One unit, one stack (`screamingface-engine`), TDD.

## Step 1 — reply origin (V1)

- New `src/screamingface_engine/world/reply_origin.py`: `ReplyOrigin` (`live`, `cache`,
  `replay`), `RECORDED_ORIGINS`, `watch_reply_origin()` (a shared mutable watch in a
  ContextVar, so a child task reaches it), `record_reply_origin()` (no-op with no watch),
  `round_trip_origin(cache_outcome, replay_frozen_copy)`.
- `world/connector.py` `_observed_round_trip`: record the origin once the gateway answered
  with a body.
- Tests: `tests/unit/test_reply_origin.py` (mapping, watch semantics, child task, and the real
  connector through `frozen_copy_support.run_call`: miss, hit, no header, replay, failure).

## Step 2 — judge provider (V2)

- `judge_provider.py`: watch each fetch; put the origin in `ModelOutput.metadata` under
  `REPLY_ORIGIN_KEY`; a blank reply carries it on `JudgeReplyBlank.origin`.

## Step 3 — redraw helper (V3)

- `judge_redraw.py`: one ask is `_ask()` → `_Answer(text, origin)`. A reply with no verdict
  whose origin is `cache` or `replay` ends the item at once (`JudgeReplyUnparseable`, no
  redraw). Live or unknown origin: today's redraws. `JudgeReplyUnparseable.redraws` reports
  what was spent (default 0).
- Tests appended to `tests/unit/inspect/test_judge_redraw.py`.

## Step 4 — DRACO reference replay (V4)

- Fixture `tests/fixtures/draco_reference_cases.json`: 4 real Cases from the reference run,
  built by the script recorded in the ledger.
- Test `tests/unit/inspect/test_draco_reference_replay.py`.

## Step 5 — documentation

- `world/fresh_judge_retry.py`: AIDEV-NOTE stating the rule for a future `;retry=` raise site.
- The four local Task files are NOT edited: their source is hashed into the published
  revision (`test_published_revisions.py`), and the behaviour lives in the shared helper.

## Step 6 — gates

`uv run .claude/scripts/run_gates.py screamingface-engine` and
`uv run --extra inspect pytest tests/unit/inspect` (the CI inspect job).

## Step 7 — V5 manual replay (done 2026-10-16; dev seed fixed 2026-10-18)

draco-3pass on `~/sf-local` from `draco-cache-live-v5.sql.gz` with no provider key; compare with
`stats/by_model.csv`. Result and the seed fix: see the ledger.
