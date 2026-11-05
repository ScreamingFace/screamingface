---
ticket: unfiled
parent: OME-1309
stack: scoreboard
status: done
started: 2026-11-03
finished: 2026-11-03
---

# External result metadata

## Intent

Implement E20's metadata foundation under the owner's explicit instruction to do
the metadata work. Spec and plan are in the sibling directories with this slug.
No Linear writes are authorized; file a child issue only after owner confirmation
at PR-open. This work is separate from #1644.

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/baseline_metadata.py`: shared validation.
- `scores/schemas.py`, `scores/models/baseline.py`, `scores/baseline_store.py`:
  typed provenance, nullable storage and import/read round trip.
- `scores/migrations/0022_baseline_metadata.py`: additive nullable migration.
- New tests for metadata, API reads and populated migration.
- `apps/scoreboard/docs/external-result-imports.md`: importer contract and example.

## Test plan

RED first: valid/invalid JSON, old inputs and rows, read/reimport, unchanged first
import time, updated last import time, omitted fields, batch rollback and migration
on existing data. Run full scoreboard gates after GREEN; do not modify old tests.

## Acceptance

Meet the linked spec's contract without changing measured submissions or UI.

## Privacy decision

Owner chose option A on 2026-11-03: publish the metric and dates, keep who attached
the result internal. This explicitly resolves the privacy guard's requested choice
and authorizes updating its published-field set to the three nonidentity fields.
The attaching person must be absent from the public DTO and API on public AND
private boards. Preserve attribution only in the database and trusted import input.

## Outcome

- **Actual files:** planned metadata module, model, serializer, schema, migration,
  importer guide and two new test files. The owner-approved privacy guard change
  and its exact-blob approval manifest were also required. No UI or permissions
  changes; no deployment, GitHub or Linear writes.
- **Commits:** local implementation commit follows this ledger update:
  `feat(scoreboard): store external result metadata`.
- **Gates:** full scoreboard gate runner passes against base `ffdc7e93f`: approved
  test transition, append-only check, Ruff lint/format, Pyright, entire Python suite
  with required coverage, and both portal test commands. Focused final run: 26 pass
  (22 new metadata/migration cases plus four privacy guard cases). The privacy RED
  run failed for both public/private response leaks and the field guard before the
  implementation fix; all three are now green.
- **Migration:** populated SQLite migration test passes; PostgreSQL SQL renders
  four nullable additions without connecting. Regeneration reports no model drift.
  No live PostgreSQL migration or deployment was performed.
- **Wisdom review:** input/store attribution is separate from the public DTO;
  existing upsert and batch transaction behavior are reused. No new dependencies,
  invented historical facts, auth paths or source-eligibility policy. Existing
  free-form metadata stays public and the importer guide warns against placing
  internal attribution there. Old import formats continue working. History remains
  a separate unit; repeat imports replace the current observation.
- **Deviations:** current main uses slug branches and unfiled ledgers until PR-open;
  branch is `external-result-metadata`. Generated migration joins both existing
  heads (`0004_add_run_cost_usd` and `0021_score_metadata_objects`). Owner approval
  manifest is keyed to parent E20 until a child issue is filed; update its branch
  and issue identity together when renaming at PR-open. The ORM has no
  `makemigrations --check` option; normal generation confirmed no remaining changes.

## Ready-to-file child issue (pending owner permission)

Title: **Store metadata for external leaderboard results**

Parent: E20 / OME-1309. Landing: scoreboard. Assignee: current owner.

External result imports need a named metric, source-read date, internal attaching
person and latest import time. Add nullable storage, validation and public reads
for metric/dates while keeping attribution internal on all boards. Preserve old
imports and first-import timestamps. Include a populated database migration test,
API privacy tests, repeat-import/rollback tests and operator documentation.

This does not close E20. Edit history, manual-entry UI/permissions, dead-link checks,
production importing and source eligibility are separate work.

PR description will use the same scope, validation and migration limits above.
No Linear write or PR opening before confirmation.

## Publication preparation — 2026-11-05

Rebased the implementation onto current main `0b2d63fac`, including the merged
scoreboard validation and cost-read fixes. No conflicts or migration numbering
collision. The full scoreboard gate runner passes against that base, including
the owner-approved privacy transition, lint, formatting, typecheck, complete Python
suite/coverage and portal tests. A read-only Linear check found no existing metadata
child issue. Publication confirmation requested before creating it and opening the
PR; no Linear or GitHub writes yet.
