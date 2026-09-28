---
ticket: OME-1247
stack: screamingface
status: done
started: 2026-09-21
finished: 2026-09-21
---

# OME-1247 — Mirror the Scoreboard's models bounds in the Client

## Intent

`OME-1180` (this branch) starts sending `models` on a leaderboard submission. The Scoreboard
caps that field at 32 routes, 255 characters each, and 4096 bytes serialized
(`apps/scoreboard/.../scores/schemas.py`, `validate_bounded_models`). The Client enforces none
of them, so a candidate over any cap turns a previously valid submission into a **422 on the
whole submission** — `models` fails validation and takes `ScoreSubmission` with it.

This is an existing inconsistency, not a new question. The board's route *pattern* was
deliberately mirrored from the Client's, and `schemas.py` says why: "the two ends must agree on
what a route is, or the Client compiles an expression the board then rejects at submit — a
failure that would only appear in the field, after a release." The grammar was mirrored. The
bounds were not.

## Why this lands on THIS branch

Owner decision 2026-09-21. A guard and the field it guards are one change; neither is correct
alone. Landing the guard on `main` first would create a regression window — a candidate with 33
distinct routes is accepted today precisely because the field is not transmitted, and would
start being rejected for a field still not sent. Landing the field first ships the defect.

Cost accepted: `#923` already carries HupBaHa's approval, so this needs a re-review.

## Scale, measured before deciding

`CandidateResult.models` is deduplicated at every accumulation path — `_ordered_unique`, i.e.
`tuple(dict.fromkeys(...))`, at `_evaluation/candidate.py:294`, `:326` and `:359`. The cap is
therefore on **distinct** routes, not recipe positions. The live maximum on any board is 4 (a
three-member fusion plus its synthesizer), so 33 distinct routes is a candidate eight times
larger than anything that has run. Real, remote, and a correctness gap rather than an outage.

## Planned changes

- `packages/screamingface/src/screamingface/_scoreboard/leaderboards.py`
  - three constants beside `_MAX_AUTHORS` / `_MAX_AUTHOR_LENGTH` (lines 39-40), which are the
    same kind of cap for the same kind of reason
  - `_submission_models()`, mirroring `_submission_authors()`: validates and returns the routes
  - `_submission()` calls it instead of reading `candidate_result.models` directly
- `packages/screamingface/tests/test_leaderboards.py` — appended cases only

## Test plan

Boundaries on both sides of each cap, because an off-by-one here is a field failure after a
release:

- 32 distinct routes submits; 33 raises, message naming the cap
- a 255-character route submits; 256 raises
- a payload serializing above 4096 bytes raises even when route count and length are legal
- the byte cap is measured on the same serialization the board measures — compact separators,
  `ensure_ascii=False` — or the two ends disagree about what 4096 bytes means
- the message names the offending value, so a user need not read the board's source
- the existing payload shape is unchanged for a candidate within every cap

## Acceptance

- every acceptance bullet on `OME-1247`
- no prior test modified
- full `screamingface` gates green at 95% coverage

## Outcome

- **Actual files:** as planned — `_scoreboard/leaderboards.py` and `tests/test_leaderboards.py`,
  plus this ledger, the spec and the plan. Nothing else touched.

- **Gates:** `run_gates.py screamingface --base origin/main --skip-append-only` ALL GREEN —
  ruff check, ruff format, pyright, pytest at **95%** coverage, the deterministic notebook check,
  `uv build`, and the distribution check. Full suite **1656 passed / 26 skipped**.

- **Deviations:**

  1. **The append-only skip is `OME-1180`'s recorded exception, not a new one.** The checker
     flags one in-place edit at line 1341 — the single string `"models"` added to
     `test_the_submission_payload_gains_only_the_cost_key`, approved 2026-09-11. Verified by
     reading the diff: every line this unit added is a pure append at 1740+. No second exception
     was taken and no prior assertion was loosened.

  2. **`import json` was replaced with `from json import dumps as _json_dumps`.** `_sync_json`
     and `_async_json` both take a parameter named `json`, so the module name is shadowed inside
     exactly the two functions most likely to want it. A future edit reaching for `json.dumps`
     in either would silently get the parameter. The aliased import removes the trap; the reason
     is recorded at the import site.

  3. **The byte-cap test pins the exact boundary rather than comparing the two serializations.**
     The first draft asserted a payload under 4096 by the board's spelling and over it by the
     default one. That fixture cannot exist for a uniform payload: the gap between the spellings
     is `len(models) - 2` bytes while one character of route moves the total by `len(models)`, so
     no length straddles them. Pinning 4096 exactly is stronger anyway — a payload measuring 4096
     by the board's spelling measures 4115 by the default one, so a wrong-separator implementation
     refuses it and fails the test.

  4. **`_result_declaring` rebuilds rather than `replace`s**, for the reason `_result_costing`
     already records beside it: `CandidateResult` takes `metrics=` but stores `_metric_items`, so
     `dataclasses.replace` feeds back a keyword its `__init__` does not accept.

- **`uv sync --all-extras` does not work on this package.** It fails with *"Extras `inspect` and
  `runtime` are incompatible with the declared conflicts"*. The gate runner selects extras per
  gate (`uv run --extra notebook …`) and is unaffected, but the instruction to sync all extras
  before running the suite is wrong for this stack as it stands today.
