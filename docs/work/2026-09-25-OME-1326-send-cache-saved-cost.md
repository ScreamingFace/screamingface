---
ticket: OME-1326
stack: screamingface
status: in_progress
started: 2026-09-25
finished:
---

# OME-1326 — Send the cache saved cost on a leaderboard submission

Client half of `OME-1251` D5. The board half is `OME-1325` (PR #1055), **not yet merged**.
Branch from `origin/main` at `eaae03b5`.

## ⚠️ Build now, merge later

**Do not merge until PR #1055 is deployed on dev and verified live.** `ScoreSubmission` is
`extra="forbid"`, so a board that does not know the field 422s the whole submission. Releases
also go out as hand-published post builds (`0.1.1.post9` was one), so anything merged into the SDK
can reach PyPI without passing through release PR #592.

#1055 is still in review and its contract changed twice already. This unit follows the contract
as it stands at `0357d7bd`.

## Intent

The SDK already holds the provider-reported saving: `_engine/contract.py` accumulates it per run
and `_RunOutcome` carries it. It is read once, at `_evaluation/results.py:191`, to tell `partial`
from `unavailable`, and then dropped. This unit carries it onto `CandidateResult` and the
submission payload.

## Planned changes

- `report.py` — `CandidateResult.cache_saved_cost_usd: Decimal | None`, emitted by `to_dict()`
- `_evaluation/results.py` — pass `outcome.cache_saved_cost_usd` through
- `_scoreboard/leaderboards.py` — send it as a decimal string, **omitted when null**
- `CHANGELOG.md`, `tests/public_surface_snapshot.json`

## Test plan

- a run with a saving sends it as a decimal string
- a run with no saving omits the key, so its payload is unchanged from today
- the archive-matched figure is never sent and never summed in
- `unavailable` is never sent with a saving (the board refuses that pair)
- a report export keeps the saving (the Keelan F2 lesson)
- the existing exact key-set guard stays green without being edited

## Acceptance

- every test-plan bullet
- the public surface snapshot records the `CandidateResult` addition
- full `screamingface` gates green at 95%

## Outcome (fill at the end — required before COMMIT)

- **Merge gate cleared.** #1055 merged as `494a5fa3`. `cache_saved_cost_usd` was live and optional
  on `ScoreSubmission` and present on `ScoreSchema` in the dev board's `/openapi.json` on
  2026-09-25. The production board was not checked.
- **Actual files:**
  - `src/screamingface/report.py`: the field, its validation, `partial` inference, the
    `unavailable` refusal, the `to_dict()` key
  - `src/screamingface/_report_primitives.py`: `_cost` takes a label, so the saving reuses it
  - `src/screamingface/_evaluation/results.py`: the pass-through
  - `src/screamingface/_scoreboard/leaderboards.py`: the key, only when not null
  - `tests/test_cache_saved_cost_submission.py`: 20 tests, new
  - `tests/public_surface_snapshot.json`, `CHANGELOG.md`
  - `docs/tasks/2026-09-23-OME-1326-send-cache-saved-cost.md`: the mirror
- **Commits:** see the PR.
- **Gates:** `run_gates.py screamingface --base origin/main --skip-append-only` ALL GREEN.
  1851 passed, 26 skipped, coverage 96%. The append-only check flagged only
  `tests/public_surface_snapshot.json`, the owner-approved exception (2026-09-25).
  `tests/test_leaderboards.py` was not touched.
- **RED:** 17 of 20 failed on the missing field. The 3 type-error tests passed for the wrong
  reason (the unknown keyword also raises TypeError) and are meaningful only after GREEN.
- **Mutation check:** pointing the pass-through at `cache_saved_cost_archive_usd` failed 3 tests.
  Reverted.
- **Snapshot diff:** exactly the one field plus its `__init__` parameter, in both namespaces
  that export `CandidateResult`.
- **Deviations:**
  - `CandidateResult` now infers `partial` when a saving is given with no cost and no status,
    and refuses `unavailable` beside a saving. The plan only said the evaluation path never
    builds that pair. Enforcing it at construction mirrors the board (#1055) and how the
    cost/status pair is already handled, so a hand-built result cannot 422 either.
  - `_cost` in `_report_primitives.py` gained a `label` parameter (default unchanged) instead of
    a second copy of the decimal validator.
  - Local pyright needs `uv sync --extra notebook`, as CI does. Without it, 11 unrelated
    `ipywidgets` import errors.
