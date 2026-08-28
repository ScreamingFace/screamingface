---
ticket: OME-1029
stack: screamingface
status: in_review
started: 2026-08-28
finished:
---

# OME-1029 — Send run_cost_usd on leaderboard submissions from the SDK

## Intent

Scoreboard accepts `run_cost_usd`, the Engine produces a run total, and the SDK already holds it on
`CandidateResult.usage.cost_usd`. The submission payload just does not include it, so the column is
null on every row of every board.

This is the last link in the run-cost chain. It unblocks `OME-822` (make cost required) and part B
of `OME-923` (Pareto frontier marks), which cannot mark anything while no row carries a cost.

## Why now

The priorities doc lists cost frontier marking and Pareto determination as Milestone 1 **Musts** for
the leaderboard. Both need cost data. The live board returns `entries=0, with a cost=0`, and this is
the only reason.

## Facts re-verified before starting

Full table in the spec (§1), checked against `origin/main` at `dd51ea81`. The one that shapes the
implementation: the payload is handed to `json=`, which serialises with `json.dumps` and raises on a
`Decimal`. The value cannot be passed through unchanged, and `float` would corrupt money.

## Planned changes

Per the plan: three cost states → payload otherwise untouched → both submit paths → round-trip
against Scoreboard's schema → close-out.

## Test plan

The absent/zero distinction is pinned first and separately. A null read as zero would put an
unpriced run at the cheapest end of the very frontier `OME-923` is about to build.

## Acceptance

See spec §5.

## Outcome

- **Actual files:** as planned — `_scoreboard/leaderboards.py` (one helper, one payload key) and
  `tests/test_leaderboards.py` (+11 tests). 58 tests pass in that file, up from 47.
- **Gates:** `run_gates.py screamingface --base origin/main` — all eight green: append-only ✓,
  ruff check ✓, ruff format ✓, pyright ✓, pytest --cov **--cov-fail-under=95** ✓, notebook
  determinism ✓, `uv build` ✓, distribution check ✓.
- **Verified beyond the suite:** every cost state round-trips through `json.dumps` and back to the
  identical `Decimal` — priced, cache-served `0`, unpriced `None`, sub-quantum `4E-7`, and the
  column ceiling `999999.999999`. Sub-quantum emits scientific notation, which `Decimal` parses
  and Scoreboard's own normalisation then quantises.

## Deviations

1. **Step 4's round-trip could not run *inside* the suite, so it was run out of band.**
   `scoreboard.scores.schemas` is not importable from this venv — `ModuleNotFoundError:
   pypika_tortoise` — because the SDK and Scoreboard are separate deployables and correctly do not
   share dependencies. The in-suite test therefore asserts a weaker property: that what we emit
   parses back to exactly the `Decimal` we started with, across the `DECIMAL(12, 6)` range. That
   exercises `Decimal`, not Scoreboard's contract.

   The contract itself **was** verified, in two processes — the SDK's venv emits via `_cost_text()`,
   Scoreboard's venv validates via the real `ScoreSubmission`:

   | emitted | `ScoreSubmission` |
   |---|---|
   | `1.234567` | `Decimal('1.234567')` |
   | `0` | `Decimal('0.000000')` — distinct from null |
   | `None` | `None` |
   | `4E-7` | `Decimal('0.000001')` — sub-quantum rounded away from zero, per `OME-770` §2.2 |
   | `999999.999999` | accepted; the ceiling |
   | `1000000.0` | **rejected** — 422 on `run_cost_usd` |

   Scientific notation surviving the wire was the live risk, and it holds. The rejection is covered
   under Owner-verify.

2. **The first attempt modified a shared fixture, and the append-only gate caught it.**
   `_result_costing` initially added a `usage` parameter to `_candidate_result`. `dataclasses.replace`
   was not an option: `CandidateResult` accepts `metrics=` but stores `_metric_items`, so `replace`
   feeds back a keyword `__init__` rejects. Rebuilt the helper to construct from the fixture's own
   attributes instead of asking for a rule-5 exception — the diff against `origin/main` is now
   purely additive, with no `-` lines in that file.

3. **Self-inflicted gate failure worth recording.** Running `uv run ruff` inside the package
   re-synced the venv without extras and dropped `ipywidgets`, so pyright failed on five files this
   unit never touched. Environment state, not code; fixed with `uv sync --extra notebook`.

## Owner-verify

- **Nothing on the live board changes until a client running this version submits.** Existing rows
  keep `null` permanently — no backfill, and `content_hash` dedup excludes cost (`OME-391`,
  `OME-770` D8), so a recipe already submitted without a cost cannot gain one.
- **This is what `OME-822`'s gate was waiting for.** That ticket makes cost required; it was moved
  out of Blocked on 2026-08-19 but its real gate — "a client can produce a run total end to end" —
  is only met once this ships and a client is released carrying it.
- **`OME-923` part B stays blocked until real cost data flows**, not merely until this merges. The
  Pareto marks need populated rows.
- **A run costing $1,000,000 or more now fails the whole submission, not just the cost field.**
  `sf.Usage` checks only finite and non-negative, so it accepts a value `DECIMAL(12, 6)` cannot
  store; before this change no cost was sent, so it could not fail. Scoreboard rejects it
  deliberately — seven integer digits overflow the column on Postgres while passing on SQLite
  (AIDEV-NOTE, `scores/schemas.py:298`). The failure is loud: `ScoreboardError`, `permanent=True`,
  with `run_cost_usd` named. Left unguarded on purpose — a client-side ceiling would put
  Scoreboard's contract in a second place, which D3 rejected. Aligning `sf.Usage`'s own validator
  is the real fix and belongs on its own ticket.

- **Reviewers differ from recent scoreboard work:** CODEOWNERS puts `/packages/screamingface/` on
  @IonesioJunior and @keelancj.
