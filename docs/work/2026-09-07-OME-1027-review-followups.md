---
ticket: OME-1027
stack: scoreboard
status: done
started: 2026-09-07
finished: 2026-09-07
---

# OME-1027 — Close the rollback purge review follow-ups

## Intent

Make the approved private-board purge easier to trust and harder to regress: render its production
row-lock query in the existing PostgreSQL guard, and give the private export a single canonical byte
representation shared by CLI output and purge hashing.

## Planned changes

- `apps/scoreboard/tests/unit/guards/test_visibility_exit_guard.py` — extend the existing asyncpg
  SQL guard to cover the purge query.
- `apps/scoreboard/tests/unit/test_purge_private_benchmark.py` — require the digest to consume the
  exporter's canonical bytes.
- `apps/scoreboard/src/scoreboard/purge_private_benchmark.py` — expose the exact purge visibility
  query for guard rendering and hash canonical export bytes.
- `apps/scoreboard/src/scoreboard/export_private_submissions.py` — define and emit canonical JSONL
  bytes, including the trailing newline.

## Test plan

- RED: the existing PostgreSQL visibility guard cannot import/render the purge query yet.
- RED: the exporter does not expose canonical bytes for the digest test yet.
- GREEN: run the two changed safety modules and the private-export module.
- Run the complete Scoreboard gate runner against `origin/main`.

## Acceptance

- The exact purge query emits `FOR UPDATE` on the installed asyncpg/Tortoise dialect.
- The CLI and purge digest consume one shared byte representation, including empty-output behavior.
- Existing purge refusal, transaction rollback, and export privacy behavior remains green.
- The full Scoreboard gate passes before commit.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. The purge now builds its locked benchmark read through a named
  production query that delegates to `ScoreStore.visibility_query`; the existing asyncpg guard
  renders that exact query and proves it contains `FOR UPDATE`. The exporter now owns the canonical
  JSONL bytes, writes those bytes directly, and supplies the same bytes to purge hashing. One empty
  export boundary test was added.
- **Commits:** `fix(scoreboard): harden rollback purge invariants` (the remote SHA is recorded by
  GitHub when this ledger-bearing commit updates PR #840).
- **Gates:** focused RED checks failed on the two missing seams, then 20 affected safety/export tests
  passed. `run_gates.py scoreboard --base origin/main --skip-append-only` reported ALL GATES GREEN:
  Ruff lint/format, Pyright, Python coverage, and all three portal modules. Direct counts: 611 Python
  tests passed, 3 skipped, 3 deselected; 50 Node portal tests passed.
- **Deviations:** the append-only precheck was skipped under the owner's explicit 2026-09-07
  Confidence-Gate approval to extend the existing PostgreSQL lock invariant test. The first full
  gate run found one Ruff `UP012` spelling issue; removing the redundant UTF-8 argument made the
  second run green. No public API, dependency, database schema, or migration changed.
