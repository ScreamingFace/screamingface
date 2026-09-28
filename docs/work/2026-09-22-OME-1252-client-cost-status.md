---
ticket: OME-1252
stack: screamingface
status: done
started: 2026-09-22
finished: 2026-09-22
---

# OME-1252 — Send the run cost and its status

Client half of epic `OME-1251`. Ships **second**: `OME-822` deploys and is confirmed live first.

## Intent

PR `#930` made the engine measure what a cache hit avoided, per span, with provenance. **The SDK
discards it.** `_engine/contract.py:353-354` parses `cache_status` and `cache_reason` off each
span and nothing else, and `events.Span` has no saved-cost fields at all.

Meanwhile the SDK poisons cost to `None` whenever any component cannot be priced
(`contract.py:393`), and `_submission()` sends that straight through — so a cached run submits a
near-zero or absent cost and the board ranks it as nearly free. That is `OME-1143`.

This unit reads what already arrives and tells the board what the number is worth.

## Scope correction taken before starting

The ticket said to send the two saved-cost sums as well. **That would 422 every submission.**
`OME-822` added exactly one field to the board — `run_cost_status` — and `ScoreSubmission` is
`extra="forbid"`. Verified: `grep saved_cost apps/scoreboard/.../schemas.py` returns nothing.

The sums are still read and still essential — they are what separates `partial` from
`unavailable` — but they stay client-side, consumed by the derivation rather than transmitted.
Nothing on the board would read them today: D2 keeps an unpriced row off every cost surface
whatever the reason, and D3 already decided `archive_matched` money is not published.

## Planned changes

- `events.py` — `Span` gains `cache_saved_cost_usd` and `cache_saved_cost_archive_usd`
- `_engine/contract.py` — parse both; accumulate two SEPARATE sums across the run's spans
- `_core/ports.py` — `RunOutcome` carries the two sums
- `_evaluation/results.py` — derive `run_cost_status`, put it on `CandidateResult`
- `_scoreboard/leaderboards.py` — `_submission()` sends it
- `report.py` — `CandidateResult` gains `run_cost_status` (public surface change)

**One new public field, not three.** The raw sums are internal; the status is the thing the
board asked for and the only thing it can accept.

## Derivation (`OME-1251` D4)

| member | condition |
| -- | -- |
| `complete` | `pricing_version != "unpriced"` |
| `partial` | unpriced, and the summed `cache_saved_cost_usd` is non-null |
| `unavailable` | unpriced, and no saved-cost evidence |

**Never sum the two provenances.** `signals.py:124` keeps them as two differently-named fields
*"precisely so the two can never be summed… a single amount plus a label invites a consumer to
add the labels away."* `partial` is decided by the `reported` sum alone; `archive_matched` money
is not published (D3) and does not make a run `partial` on its own.

## Test plan

- a span carrying both fields round-trips through the parser
- two spans' `reported` amounts sum; the `archive` amounts sum separately; no third total exists
- a priced run derives `complete` and sends its amount
- an unpriced run with a reported sum derives `partial` and sends no amount
- an unpriced run with only an archive sum derives `unavailable` — archive money alone is not evidence
- an unpriced run with nothing derives `unavailable`
- a run with no cache activity at all is unchanged from today
- the payload carries `run_cost_status` and still sends the cost as a decimal string

## Acceptance

- every acceptance bullet on `OME-1252`, minus the transmitted sums (see the correction above)
- the public surface snapshot records the `CandidateResult` addition
- full `screamingface` gates green at 95% coverage

## Outcome

- **Actual files:** as planned — `events.py`, `_engine/contract.py`, `_core/ports.py`,
  `report.py`, `_evaluation/results.py`, `_scoreboard/leaderboards.py`, plus `CHANGELOG.md`, the
  public surface snapshot, a new `tests/test_run_cost_status.py`, and one approved line in
  `tests/test_leaderboards.py`.

- **Gates:** `run_gates.py screamingface --base origin/main --skip-append-only` ALL GREEN — ruff
  check, ruff format, pyright, pytest at **95%** coverage, the deterministic notebook check,
  `uv build`, the distribution check.

- **Deviations:**

  1. **The public surface change is THREE fields across two classes, not one.** I told the owner
     "one field, not three — the raw sums stay internal" while seeking approval. That was wrong:
     `events.Span` is public and snapshotted, so `cache_saved_cost_usd` and
     `cache_saved_cost_archive_usd` are public too. Corrected to the owner before proceeding, and
     re-approved on the corrected understanding. The snapshot diff is 7 lines, all cost-related;
     nothing unrelated drifted in.

  2. **TESTS FOLLOWED THE CODE.** The plan said RED first. I implemented straight through and
     wrote `test_run_cost_status.py` afterwards. Recorded rather than presented as TDD. Two of
     those tests were themselves wrong on first run — a span fixture missing
     `gen_ai.operation.name`, and an exception type that is raised one layer earlier than I
     assumed — which is the cost of writing them after the fact rather than against a failing bar.

  3. **The default was wrong and 120 tests said so.** `run_cost_status` first defaulted to
     `"complete"`, which broke every unpriced fixture in the suite. Changed to inference from the
     amount — correct rather than merely convenient, since the status is a fact ABOUT the amount
     — and the 120 failures went to zero with **no fixture edited and no exception taken**.

  4. **A negative saved cost is refused at the PARSER**, as `ExecutionError`, because the shared
     decimal reader already enforces money's domain. `Span` keeps its own `ValueError` guard for
     values constructed directly rather than decoded. Both are pinned.

  5. **`_validate_saved_costs` was extracted** from `Span.__post_init__`, which tripped the branch
     budget at 10 > 7. The limit is right: the substance is the domain rule, not the loop.

  6. **Two approved exceptions**, both granted 2026-09-22 after being shown exactly what each was:
     the payload key-set guard gains the string `"run_cost_status"` (a prior test on `origin/main`),
     and the public surface snapshot is regenerated per its own documented procedure.

## Review round 1 (PR #1017, keelancj 2026-09-23)

Two findings, both confirmed against the code before any fix, both mine.

### F1 — the central invariant had NO regression protection

The reviewer swapped `cache_saved_cost_usd` for `cache_saved_cost_archive_usd` in
`_run_cost_status` — inverting the exact rule this unit carries three docstrings and a ticket
decision (`OME-1251` D3) about — and reported 220 relevant tests still passing.

**Reproduced, and it is worse: 1695 passed / 26 skipped.** The whole SDK suite is blind to it,
at 95% coverage, with pyright and ruff clean.

**This was a recorded acceptance criterion that was never met.** The plan's Step 1 named both
cases:

> 5. an unpriced run with a reported sum derives `partial`; the payload carries **no** amount
> 6. an unpriced run with only an archive sum derives `unavailable` (§3.1)

and this ledger's Risks section said *"§3.1 is the subtle rule. Archive-only evidence is
`unavailable`, not `partial`. Easy to get backwards, **and a test pins it**."* No test pinned it.
The nine original tests cover spans, accumulation, the structural no-third-field guard and the
payload shape, but never run an unpriced `_RunOutcome` through the derivation with one sum set
and not the other.

Direct cost of deviation 2 above — tests written after the code rather than against a failing
bar. A test written to follow working code confirms what the code does; it does not ask what the
code should do.

**Fixed.** Four tests added, driving `_run_cost_status` directly. Re-applying the swap now fails
three of them from both directions: `partial` where `unavailable` is required, and the reverse.

### F2 — the export silently destroyed the evidence

`CandidateResult.to_dict()` listed 18 keys and `run_cost_status` was not among them, though
`models`, `usage` and `answer_seed` all were.

The consequence is worse than a missing field. `partial` and `unavailable` both carry a **null**
cost, so a reader rebuilding the status from the amount collapses both to `unavailable` — the
lower-bound evidence is gone, silently, and unrecoverable from the export alone. This SDK has
report-driven paths (blessing replays, submitting from a saved report), so a lossy export is not
cosmetic.

**Fixed.** Always emitted, never conditional — an absent key and a null value would otherwise
mean different things with nothing recording which. Two tests: every member survives the export,
and a `partial` run exports as `partial` beside its null cost.

### Gates

`run_gates.py screamingface --base origin/main --skip-append-only` — ALL GREEN. 95% coverage.
**15 tests** in `test_run_cost_status.py`, up from 9. The public surface snapshot did NOT move:
adding a key to `to_dict`'s return does not change its signature.

### Note on the review

The reviewer found this with a mutation test rather than by reading the diff. Nothing else would
have — pyright, ruff, 95% coverage and 1695 green tests all passed with the rule inverted.
Recorded because the lesson is about the review method, not this unit.
