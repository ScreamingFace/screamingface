---
ticket: OME-1947
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-17
finished:
---

# engine-expired-copy-message — the engine says when a replayed frozen copy expired (unit C2)

## Intent

When the gateway answers 410 `frozen_copy_expired` on a replay, the engine gives a fixed text that says the copy expired. The code that leaves the engine stays `frozen_copy_unavailable`.

Spec: `docs/spec/2026-11-16-frozen-copy-retention/`. Plan: `docs/plan/2026-11-17-frozen-copy-retention-stack-c.md` (owner approved 2026-11-17).

## Planned changes

Paths are under `apps/screamingface-engine/`.
- `src/screamingface_engine/capture_outcomes.py` (`REPLAY_EXPIRED`, `REPLAY_EXPIRED_TEXT`, `replay_refusal_code`)
- `src/screamingface_engine/world/connector.py` (`_replay_refusal`)
- `src/screamingface_engine/world/web_tools.py` (`lookup`)
- `src/screamingface_engine/error_text.py` (comment only)
- `tests/unit/test_frozen_copy_replay_expired.py` (new)

## Test plan

RED first. Test ids of `prd/expired-copy-replay.md`.
- R-4, R-5: chat replay 410 → `frozen_copy_unavailable`, permanent, the fixed text, one POST, no gateway message.
- R-6: tool lookup 410 → the same code and text, no Tavily call.
- R-7: a 410 with a different code or no JSON body → the old text; `frozen_copy_expired` is in no engine code set.
- CH-2, CH-3 stay green with no edit.
- Invariant protected: no new error code leaves the engine.

## Acceptance

- `run_gates.py screamingface-engine` all green.
- No existing test is changed.
- An independent design review against the spec has no open major finding.

## Notes at start

- Owner order of 2026-11-17: both plans approved; build stacks B and C in parallel.
- The branch was first cut from the stack A branch, because pull request #1911 was not merged.
  Review of 2026-11-18 (changes requested): the plan cuts C2 from `main`, and the engine change
  needs nothing below it. On 2026-11-23 the one commit was moved onto `origin/main` and the pull
  request now targets `main`.
- The `tortoise-dev` companion skill is not installed on this machine. Code that touches the ORM
  follows the house pattern that the plan names.

## Outcome (fill at the end — required before COMMIT)

State on 2026-11-17: the code is built, reviewed and committed on the branch
`OME-1947-engine-expired-copy-message`. `status` stays `in_progress` until the pull request is
merged.

- **Actual files:** as planned.
- **Commits:** one commit,
  `feat(screamingface-engine): say when a replayed frozen copy expired (OME-1947)`.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine --base a06fc9802` → ALL
  GATES GREEN.
- **Design review:** verdict ACCEPT, 5 low findings. Fixed: C2-1 (the text "the frozen copy is
  not available for replay" is written one time; `_replay_unavailable` reads the table), C2-4 (a
  comment that repeated a docstring is removed). C2-5 is a confirmation, not a defect. Open, low:
  C2-2 (the pair "expired text, `frozen_copy_unavailable`" is in two tables, one in
  `connector.py` and one in `web_tools.py`, as the plan says) and C2-3 (`or ""` as the lookup
  key for "no code").
- **Deviations:** none from the plan. CH-2 (`tests/unit/test_frozen_copy_replay_failures.py`)
  and CH-3 (`tests/unit/test_frozen_copy_replay_unserved.py`) are green with no edit.

## Review fix (2026-11-23)

- Deviation, now closed: the branch was cut from the stack A branch (see "Notes at start"). It is
  now one commit on `origin/main`, and pull request #1920 targets `main`, as the plan says.
- Gates on the main-based branch: see the line below, run on 2026-11-23.
