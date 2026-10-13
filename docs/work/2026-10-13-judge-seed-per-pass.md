---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-13
finished: 2026-10-13
---

# judge-seed-per-pass — give each judge pass its own pinned seed

## Intent

OME-1527 R12 (Work order #16). draco grades one Candidate reply with 3 or 5 judge passes; the
hand-built board sends `seed=<pass>` on each pass so the AI Gateway's exact-request cache can
never fold the passes into one reply. On the plugin lane a scorer cannot do that: the judge
provider refuses every grade-affecting `GenerateConfig` field, `seed` included, because the row
pins how the judge grades (the OME-1240 trust line). This unit lets a row opt in to judge passes:
the scorer then names pass `k` as `GenerateConfig(seed=k)`, and the provider sends the row's
pinned params plus `seed=k`. Every other setting stays refused; rows that do not opt in refuse
`seed` exactly as today. First consumer: draco as a local Task (Work order #18).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py`: `JudgeSpec`
  gains `seed_per_pass: bool = False` (refused together with a pinned `seed`), hashed into the
  revision only when set, and carried onto the `JudgeTransport`.
- `apps/screamingface-engine/src/screamingface_engine_inspect/judge_provider.py`:
  `JudgeTransport.seed_per_pass`; on an opted-in transport `seed` joins the config allowlist,
  must be a pass number `0..MAX_JUDGE_PASS`, and is appended after the pinned params; the
  accounting registration uses the same per-call params.
- `apps/screamingface-engine/src/screamingface_engine_inspect/judge_redraw.py`:
  `judge_until_parsed(..., judge_pass=k)` sends pass `k` on every draw, so a redraw keeps its
  pass's seed and still leaves the gateway cache.

## Test plan

- New `tests/unit/inspect/test_judge_seed_per_pass.py`: two passes of a stand-in judged scorer
  send two requests whose seeds differ and whose other params, path and messages match; a row
  without the opt-in refuses `seed` as today; an opted-in row still refuses any other setting
  and an out-of-range pass; a redraw inside pass 2 keeps `seed=2` and opts out of the cache;
  the opt-in moves the revision and a pinned seed beside it is refused.
- Existing: `test_judge_provider.py`, `test_judge_redraw.py`, `test_judge_grader_role.py`,
  `test_concurrent_judge_booking.py`, `test_judge_observability.py`,
  `test_judged_benchmark_assembly.py`, `test_published_revisions.py`.

## Acceptance

- The new tests pass with the `inspect` extra and skip cleanly without it; the existing judge
  tests and `test_published_revisions.py` pass unchanged (no published revision moves).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger. No pre-existing test edited (no approval
  manifest entry); the append-only check vs `upstream/main` passes.
- **Commits:** see the PR — feat(screamingface-engine): give each judge pass its own pinned seed
- **Gates:** 472 passed across the new file and `test_judge_provider.py`,
  `test_judge_redraw.py`, `test_judge_grader_role.py`, `test_judge_observability.py`,
  `test_concurrent_judge_booking.py`, `test_judged_benchmark_assembly.py`,
  `test_inspect_frontierscience_benchmark.py`, `test_inspect_imported_benchmarks.py`,
  `test_published_revisions.py`, `tests/unit/test_fresh_judge_retry.py` (with the `inspect`
  extra); extra-less, the inspect files skip cleanly and the rest pass. ruff check and format
  clean; pyright 0 errors with and without the extra on the touched files. Full gate left to the
  pre-push hook and CI.
- **Deviations:** the seed seam is opt-in per row (`JudgeSpec(seed_per_pass=True)`) rather than
  admitted on every judged row, so a row that never declared passes refuses `seed` exactly as
  before. The pass number maps to the seed unchanged (`seed=k`), the hand-built draco judge's own
  mapping. Also fixed in passing because the change needs it: the accounting registration now
  keys on the call's own params (seed included), or a seeded pass's cost would miss its Case.
- **Owner-verify:** nothing to press here; no row opts in. The first paid check is draco's
  migration run (Work order #18), which should show 3 or 5 distinct judge requests per Case.
