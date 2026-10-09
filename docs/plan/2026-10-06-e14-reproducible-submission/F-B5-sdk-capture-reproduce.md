# F-B5 — SDK: `capture=True` and `sf.reproduce` over a frozen copy (rework of B5)

- **Worktree:** `.claude/worktrees/e14-b5-sdk-reproduce` · **Branch:** `e14-b5-sdk-reproduce`
  (rework in place, new commits on top) · **Base for gates:** `e14-a2-sdk-metadata` · **Stack:** `screamingface`
- **Prerequisite:** the stack is rebased so that F-B3 (engine, incl. the SDK mirror of `frozen_copy_miss` /
  `frozen_copy_unavailable`) and F-B4 (board) are below this branch.
- **Design:** `02-frozen-copy-design.md` §7 (binding), §5 for the engine contract. Rules: `00-common.md`.

## Changes

- `evaluate(..., capture: bool = False)` on `Client`, `AsyncClient` and module level. Thread it like
  `answer_seed` (`client.py` → `_evaluation/url4.py` → `Candidate` via `_stamped` → transport header
  `X-Capture: true` only when true). `capture` and the internal replay are mutually exclusive.
- Replace the old replay plumbing: `Candidate.cache_replay` → `replay_frozen_copy`; header `X-Cache-Replay` →
  `X-Replay-Frozen-Copy`; the start-response echo check uses the new header name.
- Run summary: read `capture.frozen_copy_id`, `capture.status` and `capture.replay` (replacing `cache.revision`,
  `cache.reproducible`, `cache.replay`). Absent → `None`.
- `CandidateResult.frozen_copy_id`, `capture_status` replace `cache_revision`, `reproducible` (validation:
  UUID string; `frozen_copy_id` requires `capture_status`). `to_dict` keys follow.
- `submit` sends `frozen_copy_id`, `capture_status`, `answer_seed` when set.
- `LeaderboardScore.frozen_copy_id`, `capture_status` replace `cache_revision`, `reproducible`.
- `_report_primitives.reproducible_status` → `capture_status_value` (same narrowing).
- `sf.reproduce`: the outcome table of design §7, in that order. Replay codes are `frozen_copy_miss` and
  `frozen_copy_unavailable` (they also prove replay mode when `capture.replay` is absent). The record POST
  sends `frozen_copy_id` instead of `cache_revision`.
- Tests: rename this PR's own tests and fixtures; add tests for `capture=True` (header sent only when true;
  result fields decoded) and for the two new codes. Regenerate `tests/public_surface_snapshot.json`
  (pre-approved; record it).

## Verify

`cd packages/screamingface && uv sync --extra runtime --extra notebook`, then
`uv run .claude/scripts/run_gates.py screamingface --base e14-a2-sdk-metadata` (with and without
`--skip-append-only`).
