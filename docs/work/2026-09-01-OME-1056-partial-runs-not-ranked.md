---
ticket: OME-1056
stack: scoreboard
status: done
started: 2026-09-01
finished: 2026-09-01
---

# OME-1056 — Keep partial runs out of the ranked leaderboard

## Intent

A run covering fewer cases than the benchmark defines currently ranks alongside a complete
run, and beats it: fewer cases makes a perfect score easier. Reproduced before any code was
written — a one-case IFEval run scoring 1.0 takes rank 1 over a 541-case run scoring 0.85.

The Scoreboard cannot presently tell the two apart. `total_questions` is validated only for
`> 0`, `Benchmark` stores no expected count, and the ranking query filters on `benchmark_id`
and `benchmark_revision` alone. The Engine already publishes `case_count` in the catalogue the
seed job fetches on every deploy; `_CatalogEntry` sets `extra="ignore"` and discards it.

Partial runs stay accepted and readable. A participant running `limit=1` to prove the
submission path works is a supported workflow, and the client already warns the run is partial
(OME-922). Only the RANKING changes.

## Planned changes

- `src/scoreboard/scores/models/benchmark.py` — `case_count`, nullable int
- `src/scoreboard/scores/migrations/00NN_benchmark_case_count.py` — new
- `src/scoreboard/scores/schemas.py` — `case_count` on `BenchmarkSchema` and `_CatalogEntry`;
  NOT on `SeedBenchmark` (deployment config must not claim canonical scope)
- `src/scoreboard/scores/store.py` — `benchmark_to_schema`, `register_benchmark`, and the
  `_build_leaderboard_query` predicate
- `src/scoreboard/seed.py` — carry `case_count` from the catalogue
- tests as below

## Test plan

RED first, from the reproduction:

1. **The bug itself** — a 1-case row and a full row on a benchmark with a registered
   `case_count`; only the full row ranks. Fails today.
2. **Boundary** — `total_questions == case_count` ranks; `case_count - 1` does not.
3. **No registered count filters nothing** — mirrors the existing revision rule, so legacy and
   non-Engine boards are unaffected.
4. **Still readable** — the excluded row is returned by `list_for_spec`, by score id, and in
   the submission response. This is the half that keeps `limit=1` testing viable.
5. **Deployment config cannot supply `case_count`** — same refusal the `revision` rule gives.
6. **Regression** — a public board with no partial rows is byte-identical to today.

## Acceptance

- A run below the registered `case_count` is absent from `entries` and present everywhere else.
- A benchmark with no `case_count` ranks exactly as today.
- `tortoise makemigrations` reports no further drift.
- Full gates green.

## Outcome

- **Actual files:** as planned. `models/benchmark.py`, `migrations/0011_benchmark_case_count.py`,
  `schemas.py`, `store.py`, `seed.py`, plus `tests/unit/scores/test_leaderboard_coverage.py` and
  `tests/unit/test_seed_case_count.py`.
- **Gates:** ALL GATES GREEN. 544 passed, 3 skipped, 3 deselected. `makemigrations` reports
  "No changes detected". The append-only check passes unaided — no prior test was modified.
- **Deviations:** none from the plan. Two things learned while building it, both recorded below.

## What the mutation checks proved

**The coverage filter must live inside the window.** Moved outside — onto the outer query beside
`rn == 1` — only `test_a_specs_complete_run_survives_its_own_higher_scoring_partial` fails, and it
fails with `[] == [('same-spec', 0.6)]`: the spec's COMPLETE run disappears entirely. The partial
row takes `rn = 1` within its partition, the outer filter then drops the row that would have
ranked, and the participant vanishes from the board for having smoke-tested. SQL evaluates WHERE
before window functions, which is why the filter sits beside the revision filter and not after it.
The other five tests still pass under that mutation, so the test is specific rather than redundant.

**Configuration cannot forge a scope.** Removing `row.case_count is not None` from
`_classify_configured` makes `test_configuration_may_never_declare_a_case_count` fail. Without it,
a chart entry declaring `case_count: 1` would make every one-case run rank as complete — the same
hole this unit closes, re-opened from the other side.

## Two notes for whoever picks up OME-867

**A prior test's comment is now stale, and was deliberately left alone.**
`test_catalog_fields_the_board_does_not_display_are_ignored` names `case_count` in its comment as
an example of a catalogue field the board ignores. Its ASSERTION is unaffected — unknown fields
still do not break a deploy — so under the append-only rule it was not touched. The staleness is
recorded in the new seed test's module docstring so the next reader finds it.

**Dedup already separates coverage levels, so nothing collides.** `total_questions` participates in
`_content_hash`, and the SDK sends `Idempotency-Key: run_id`, unique per run. So a `limit=1` run and
a full run of the same recipe are two rows on both paths. The partial one exists and does not rank;
the full one ranks. Neither displaces the other, and no participant loses a submission by having
tested first — which is the whole reason partial runs stay accepted.

## Approval follow-ups — 2026-09-02

PR #785 was approved with six non-blocking findings. Five are implemented on the follow-up
branch rather than added to the already-approved PR:

1. **Frontier parity:** `/frontier` now applies the registered `case_count` before computing
   the current holder, trend, and openness counts. A route-level regression proves the public
   endpoint cannot drift from the ranked table.
2. **Local seed parity:** `scoreboard_seed_json()` carries the Engine registry's `case_count`,
   so `screamingface up` enables the same coverage filter as a deployed Scoreboard.
3. **Producer contract:** the Engine catalogue suite pins `case_count` by exact field name,
   integer type, and positive range for every built-in benchmark.
4. **Seed persistence:** a real in-memory Tortoise test covers HTTP catalogue parsing through
   `seed_from_sources()` into `Benchmark.case_count` in the database.
5. **Predicate boundary:** a run reporting more than the registered count remains comparable;
   a regression test prevents accidentally tightening `>=` to `==`.

The seed/store boundary also now distinguishes **omitted** from **explicitly absent** scope.
A direct `register_benchmark()` caller that omits `case_count` preserves the stored value. An
authoritative Engine row with no usable count passes explicit `None` and clears it, preventing a
new benchmark revision from inheriting a stale scope.

The sixth finding is intentionally not folded into this implementation. `total_questions` is a
client claim and the submission wire does not attest that every selected case completed grading.
That product/trust decision is already tracked by OME-867, whose acceptance explicitly requires a
typed Client↔Scoreboard evaluation-scope contract, distinct incomplete-grading behavior, and
cross-stack `limit=1` coverage. No duplicate ticket was created.

### Follow-up verification

- **Scoreboard:** official `run_gates.py scoreboard` — all gates green, including append-only,
  Ruff, formatting, Pyright, coverage, and portal logic.
- **ScreamingFace SDK:** official `run_gates.py screamingface` — all gates green, including 95%
  coverage, notebook validation, wheel build, and distribution inspection.
- **Engine:** append-only, Ruff, formatting, Pyright, layering, and the changed 18-test catalogue
  contract suite are green. The full pytest gate completed 2,283 passed / 5 skipped / 1 unrelated
  local failure: Helm 4's default Kubernetes capability is 1.20 while the untouched chart requires
  1.25+. Rendering the same untouched chart with `--kube-version 1.25.0` succeeds.
- **ORM:** installed and current Tortoise ORM versions both 1.1.8; persistence tests use the
  repository's `tortoise_test_context` fixture.
