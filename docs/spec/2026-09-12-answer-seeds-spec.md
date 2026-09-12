# Answer seeds — declaring the sittings of an exam

**Ticket:** `OME-1038` (design-session, parent epic `OME-1024`) · **Status:** proposal —
awaiting owner decision · **Author unit:** `docs/work/2026-09-12-OME-1038-answer-seeds.md`

**TLDR: a benchmark score today is one exam sitting presented as the student's ability.
We let a run declare its sittings (answer seeds), stamp every answer with its sitting,
and publish mean ± CI — without invalidating a single recorded replay fixture.**

## Problem / Solution

**Problem:** Run the same exam twice and the student may score differently — models are
nondeterministic. Today every leaderboard number is a single sitting shown as the truth:
nobody can say how much it wobbles, and nobody can re-create the exact sitting behind it.

**Solution:** A run declares its sittings up front — a list of answer seeds. Every answer
records which sitting produced it, identical sittings produce identical requests
byte-for-byte, and the score can be published honestly as *mean ± confidence interval*.

## Before / After

The before/after mechanism diagram lives on the
[ticket](https://linear.app/openmined/issue/OME-1038/a-run-cant-declare-answer-seeds-so-score-variance-cant-be-measured-or)
(red TODAY lane / green AFTER lane) — drag the same PNG into the implementation PR.

### Before

- Trigger: a researcher wants to publish *mean ± CI* by running the same cases N times.
- Today: no answer-seed exists anywhere; two "identical" runs can't be told apart or
  reproduced. The only seed concept is judge-side and benchmark-local.
- Cost: every published number is one sample; and every day of delay records more replay
  fixtures whose request keys a carelessly-added seed field would invalidate.

### After

- Same trigger.
- Now: the run declares N seeds; each answer names its seed; same seeds render
  byte-identical expression text.
- Win: variance/CI reporting, exact replay of any sitting.

### Don't regress

- A run that declares nothing behaves byte-identically to today (see the fixture
  decision below — this is the load-bearing bullet).
- The seed **set** is identity-bearing; execution order stays operational (`OME-931`).

## Current state — verified 2026-09-12

The machinery is closer than the ticket assumed. Three facts anchor the design:

| Fact | Where | Consequence |
| --- | --- | --- |
| URL4 expression params flow to the model untouched — anything not runner-owned passes through | `apps/screamingface-engine/src/screamingface_engine/runner/request_parameters.py` (`model_params`; owned set = `model`, `messages`, `tools`, …) | **A `seed` param already reaches the provider today.** No runner change is needed for the wire. |
| The judge side already uses exactly this idiom: `params=(*JUDGE_PARAMS, ("seed", str(run)))` — one stable seed per pass, occupying independent cache slots | `apps/screamingface-engine/src/screamingface_engine/benchmarks/draco/exam.py` | The candidate-side design is a **mirror of a proven pattern**, wire name `seed` included. |
| Replay tapes are keyed by the gateway's canonical request bytes (`key_hash`), so tape identity ≡ cache identity | `packages/screamingface/tests/e2e/harness/tape.py` | A seed param **in** the expression changes the key; a seed param **absent** leaves every existing fixture valid. |

One honesty constraint the ticket didn't state: **a provider `seed` is best-effort, not a
determinism guarantee** — OpenAI documents seed as best-effort, Anthropic has no seed
parameter at all. What the seed buys us for certain is *labeled, cache-separated samples*
(each sitting is its own cache slot, so N sittings are N genuine samples, and a replay of
sitting 2 replays sitting 2's recorded bytes). Provider-side determinism is a bonus where
it exists, never a promise we publish.

## The fork: where does the seed axis live?

Both options put `("seed", str(s))` on every candidate call of a sitting — that part is
settled by the judge idiom. The fork is **what one "run" means**.

### Option A — one run per sitting (recommended)

A run keeps today's shape: one url4 expression, one report. Declaring seeds `[1, 2, 3]`
executes three runs, each rendering its expression with its own `seed` param, each
producing a report stamped `answer_seed: s`. The scoreboard (or the client) aggregates N
sibling reports into mean ± CI.

- **Row envelope: untouched.** The spine's rows, `grade_case`, and the exam scorer never
  learn seeds exist — the seed rides where model params already ride.
- **Fixture decision: dissolves.** An undeclared run renders no seed param — byte-identical
  to today, **0 fixtures invalidated**. A seeded run is a new recording by definition.
- **Cost:** N sittings = N× paid calls (inherent to the feature, identical in both
  options) and a cross-cutting sub-issue for the scoreboard's sibling-report aggregation.

### Option B — one run carries all sittings

One expression fans out per-Case × per-seed; each row names its seed; the exam scorer
aggregates within the run; one report carries mean ± CI.

- **Wins:** one submission, one report, variance computed engine-side.
- **Costs:** breaks four shipped contracts at once — the row envelope (`spine/rows.py`
  position-is-identity roll call becomes two-dimensional), `grade_case`, the exam
  scorer's metric vocabulary, and the report schema. It also *forces* the fixture
  question Option A dissolves, because the single-seed default must then be expressed
  in-expression.

**Recommendation: Option A.** It is the YAGNI shape — the entire feature reduces to (1) a
client/run-config field `answer_seeds: list[int]`, (2) the candidate call rendering
`("seed", str(s))`, (3) `answer_seed` in the report metadata, (4) a scoreboard
aggregation sub-issue. Option B's single-report elegance can be layered later without
undoing A; A ships without touching the spine the epic just stabilized.

## Scope

- **Now:** seed declaration (client + engine run config), candidate `seed` param
  rendering, `answer_seed` in report metadata, the no-declaration byte-identity guarantee
  pinned by a test against a recorded fixture.
- **Later:** scoreboard mean ± CI display and sibling-report grouping (own sub-issue,
  `scoreboard` landing); engine-side single-report aggregation (Option B) if N-run
  submission proves clumsy in practice.
- **Out:** determinism guarantees per provider (not ours to promise — best-effort
  upstream); seeding judge passes differently (already shipped, revision-bearing, frozen).

## Acceptance (falsifiable)

1. A run declaring `answer_seeds=[1, 2, 3]` produces 3 reports, each naming its seed, and
   re-running with the same seeds renders byte-identical expression text (asserted by
   comparing rendered expressions, not scores).
2. A run declaring nothing renders expressions byte-identical to today: the existing
   recorded e2e fixtures pass **unmodified** (0 re-records).
3. The diff touches no file under `benchmarks/spine/` (Option A's deletion test).

## Decision needed from the owner

1. **Option A or B?** (Recommendation above: A.)
2. Confirm the fixture stance A implies: no default seed value — absence is the default.
3. Scoreboard aggregation: file the `scoreboard` sub-issue now (epic rule: one sub-issue
   per landing) or park it until A ships?
