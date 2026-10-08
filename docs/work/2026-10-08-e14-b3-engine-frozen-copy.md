---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-08
finished:
---

# e14-b3-engine-frozen-copy — engine capture mode (frozen copy) and replay mode

## Intent

E14 PR F-B3 (design `02-frozen-copy-design.md` §5, §9). A run that gets `X-Capture: true` opens a
frozen copy in the AI Gateway before its first step, sends `X-AIGW-Frozen-Copy: <id>` on every chat
call, posts every web-tool result string to the copy, and seals the copy when the steps end. A run
that gets `X-Replay-Frozen-Copy: <uuid>` sends every chat call to the copy's replay route, reads
every web-tool result from the copy, and never calls a provider or Tavily. A run-scoped tally (with
the old D1 and D2 rules) gives `capture.status`. The run summary always states `capture.*` for a
capture run and `capture.replay` for a replay run. Local only: no push, no PR, no Linear.

## Planned changes

- New: `src/screamingface_engine/capture_outcomes.py` (run-scoped tally, adapted from the old
  `replay_outcomes.py`).
- `request_scope.py`, `job_env.py`, `runner/main.py`: `capture` and `replay_frozen_copy` end to end.
- `rest/routes.py`, `ports.py`, `adapters/inprocess.py`, `adapters/queue_runner.py`,
  `runner_queue.py`, `local.py`: header into the job env, and the start-response echo.
- `world/connector.py`: copy header and capture status on chat; replay route and occurrence header;
  `open_frozen_copy` and `seal_frozen_copy` on the connector's gateway client.
- `world/web_tools.py`: tool-result capture before truncation; tool lookup in replay mode, no Tavily.
- `runner/executor.py`: bind the tally; open before the steps, seal after; summary attributes.
- `error_text.py`, `benchmarks/contract.py`, SDK `_report_primitives.py`: the two new failure codes.
- `README.md`: capture and replay section.
- New tests only, under `tests/unit/`.

## Test plan

The F-B3 TDD list, in order (risk order):

1. replay never calls Tavily or the normal chat route.
2. capture sends the copy header on every chat call and records the capture status.
3. a normal run is byte-identical (no new header, no tool-result post, no new summary attribute).
4. the `capture.status` rule table (D1, D2).
5. tool results are posted before truncation, failure strings included.
6. replay occurrence counter per digest.
7. replay 404 miss and unavailable fail the case with their codes; a tool lookup miss fails it.
8. replay success is accounted as zero spend.
9. header, env and scope plumbing for both modes; both present is 400; malformed uuid is 400; echo.
10. the summary is always written for capture and replay runs.
11. open and seal once per run; seal on a failed run; no seal on a cancelled run.

## Acceptance

- Gates green for `screamingface-engine` with `--base e14-b2-engine-tavily-cache`.
- No existing test edited, except the approved edits below.

## Approved test changes (append-only exception)

Pre-approved by the F-B3 plan. Nothing else in an existing test may move.

1. `frozen_copy_miss` and `frozen_copy_unavailable` added to the exact sets in
   `tests/unit/test_failure_classes.py` and `tests/unit/test_terminal_error_detail.py`.
2. `capture` / `replay_frozen_copy` parameters added to fake `schedule` signatures (a fake that
   pyright rejects after the port gains the parameters).
3. `tests/unit/data/cache_hit_contract/run_events.json` regenerated only if the normal-run bytes
   change. They must not.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
