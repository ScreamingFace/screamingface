---
ticket: OME-986
stack: scoreboard
status: done
started: 2026-08-25
finished: 2026-08-26
---

# OME-986 — Retire the legacy news demo benchmarks

## Intent

`hle`, `livetruth` and `livetruth-latest` are leftovers from the previous SF project, still
advertised on the catalogue of the board being handed to internal testers this week. Irina asked
for their removal in `#scream-dev` on 2026-08-25.

Removing them from the chart's seed list is necessary but not sufficient: seeding only registers
and updates, so the rows persist and keep being served. A deletion path has to exist first, and
this unit builds it as an operator module rather than a migration or hand-written SQL.

## Verified before starting

Exactly **two** foreign keys point at `Benchmark` — `Score` and `Baseline`. `IdempotencyKey` links
to `Score`, not `Benchmark`. So a blockers check covering scores and baselines is complete, and no
third table can produce an `IntegrityError` the guard failed to predict.

## Facts established before design

Full table in the spec (§2). The two that shape the unit:

- **F1/F2** — seeding never deletes, so the config change alone changes nothing a reader sees.
- **F3/F4** — all three are empty today (0 entries, 0 baselines) and both foreign keys are
  `RESTRICT`, so nothing blocks deletion right now. That stops being true the moment a tester
  submits against one, which is why this is cheaper now than later.

## Owner decisions (2026-08-25)

- Operator module plus the config removal, rather than a migration or raw SQL.
- Scope is exactly the three revision-less ids; the five Engine-published benchmarks are a
  different conversation.
- Named `retire_benchmark`, with the docstring stating plainly that it is an irreversible DELETE.
- Deletion requires an explicit `--yes`; without it the module reports and changes nothing.
- An unknown id is refused with a non-zero exit, so a typo cannot read as success.

## Planned changes

Per `docs/plan/2026-08-25-OME-986-retire-news-benchmarks.md`: refusal path → unknown-id guard →
deletion → CLI wrapper → chart seed list → close-out. The refusal path is built and tested before
the deletion path, because destroying submissions is this module's only real risk.

## Test plan

Per the plan, RED-first. Contracts pinned: a referenced benchmark is refused **and survives**; an
unknown id is refused rather than reported as success; an unreferenced benchmark is deleted and
stops being advertised.

## Acceptance

See spec §6.

## Outcome

- **Actual files:** as planned — `src/scoreboard/retire_benchmark.py`,
  `tests/unit/test_retire_benchmark.py`, `charts/scoreboard/values.yaml`.
- **Gates:** `run_gates.py scoreboard --base origin/main` green — append-only ✓, ruff check ✓,
  ruff format ✓, pyright ✓, pytest --cov ✓, node --test portal ✓. No prior test modified.
- **Guards are mutation-proven**, not merely passing:
  - removing the `--yes` gate → `test_without_confirmation_nothing_is_deleted` fails;
  - removing the refusal → 4 tests fail, one of them with `IntegrityError: FOREIGN KEY constraint
    failed`, which also demonstrates `RESTRICT` working as the second line of defence rather than
    the first.
- **End-to-end against a real database:** dry run changed nothing; the three legacy ids retired;
  `draco`, holding one score, was refused **even with `--yes`** and survived. Exit codes verified
  separately after an initial check misread `tail`'s status instead of the module's — refusal `2`,
  unknown id `2`, dry run `0`, confirmed delete `0`.
- **Deviations:** one, below.

## Deviations

1. **The module was written in one pass, then refactored, rather than grown strictly step by
   step.** The first draft duplicated the existence check and the blockers check between
   `retire_benchmark` and `_run`. It was collapsed to a single decision function with `_run`
   reduced to database lifecycle, which also made the `--yes` gate testable without standing up a
   connection. The refusal tests were written first and did drive the guard; the deletion and
   confirmation tests followed the code, which is why both were mutation-checked before being
   trusted.

## Review round — 2026-08-25

Three P2 findings, all reproduced before being acted on, all valid.

- **Engine-owned benchmarks had no guard.** Reproduced something stronger than the report: the
  deletion is not merely out of scope, it is **futile** — `retire draco` → `[]` → next seed →
  `['draco']`. An Engine-published benchmark is re-seeded from the catalogue, so deleting it here
  silently does not achieve what the operator asked. It is now refused, naming the revision.
  **Not** an absolute block: if the Engine STOPS publishing a benchmark, seeding will not recreate
  it but also never deletes it, so the row is stranded and this module is the only way out.
  `--include-engine-owned` exists for exactly that case, and does not bypass the reference refusal.
- **The check/delete race escaped as a traceback.** Reproduced with
  `IntegrityError: FOREIGN KEY constraint failed` — `main()` catches only `LookupError` and
  `RetirementRefused`, so a score landing between `collect_blockers()` and the `DELETE` handed the
  operator the exact traceback this module exists to replace. The `IntegrityError` is now caught,
  the counts re-read, and a readable refusal raised naming what actually landed.
- **The docs went stale on my own change.** `DEPLOYMENT.md` claimed the default seed registers
  HLE/Livetruth and its smoke check POSTed to `hle`, which now 404s on a fresh install;
  `charts/README.md` said the list carries the legacy demos. Both rewritten: the default seeds
  nothing, a real deployment points `engineUrl` at the Engine, and the smoke example uses a
  `smoke` entry the reader is told to seed. Both now also state that seeding never deletes and
  name the retire command.

Checked and deliberately **not** changed: `DEPLOYMENT.md` still documents the three `livetruth-*`
public artifact files. Those are the portal's `PUBLIC_ARTIFACTS` allowlist, still present on disk
and still served — a separate concern from benchmark registration. Retiring the benchmark does not
retire the artifact, and widening this unit to cover it would be scope creep.

## Review round — 2026-08-25 (@HupBaHa, PR #726)

Changes requested on three items; the safety core was signed off explicitly. Reasoning in spec §7
(D8–D10).

- **D8 — scope widened by owner decision.** `retire_benchmark` is a general operator command for
  any unreferenced benchmark, not only the three legacy ids. The reference guard stays
  unconditional and `--include-engine-owned` stays for the stranded case.
- **D9 — the delete now confirms it deleted.** The row count was discarded, so a concurrently
  vanished benchmark printed `retired`. Also fixed a third unhandled path (`get()` →
  `get_or_none()`, which raised `DoesNotExist`), and moved the Engine-ownership guard into the
  DELETE predicate so it holds at the write rather than only at the read.
- **D10 — the CLI boundary is tested**, against a real on-disk database so the init/close paths are
  genuinely exercised.

Both new guards are mutation-proven: dropping the `--include-engine-owned` wiring fails two CLI
tests, and ignoring the delete row count fails two decision tests.

This is the second review round where the finding was **adjacent to something I had just fixed** —
the row count sits directly beside the race I had hardened. Same pattern as OME-894's rounds.

## Owner-verify

- **The config half may land nowhere.** The chart's seed list is now `[]`, but the deployed values
  are not this repo's defaults (spec F6) — confirm with @Stephen which file feeds the deployed seed
  job. Same conversation as the `authMode` question on `OME-894`.
- **Emptying the list does not remove anything that already exists.** The three rows on the live
  board are still there until someone runs
  `python -m scoreboard.retire_benchmark --benchmark <id> --yes` against that database. Order
  matters: run the module *after* the config change is deployed, or the next deploy recreates them.
- The five Engine-published benchmarks (`draco`, `draco-3pass`, `healthbench-professional`,
  `healthbench-worst30`, `ifeval`) are untouched and were never in the chart list.
