---
ticket: OME-1448
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# SDK report recovery and pagination

## Intent

Separate the runtime artifact-directory work from PR #1156 so both runtime and SDK changes can land against main in either order. The user authorized this two-PR split.

## Planned changes

Relocate the three runtime modules, their existing artifact-directory tests and relative-status regression into a main-based runtime branch. Keep SDK persistence, case indexing, recovery, streamed atomic export and notebook pagination in #1156. Split current documentation by ownership while retaining historical ledgers.

## Test plan

Run the runtime regressions on main before transplanting implementation (RED). Preserve each moved test definition exactly and audit that no original source/test changes are lost. Run every SDK card gate independently on both branch trees and verify conflict-free composition in either merge order. No paid model calls.

## Acceptance

Each branch builds/tests against main without the other, has no dependency on the other PR, and both combined preserve the source implementation at 10354d58. Runtime source lives only in the runtime PR; SDK imports have no dependency on the extracted artifact configuration.

## Outcome

Exact relocation audit passed: every original test/helper definition remains unchanged on exactly one branch; runtime modules and artifact tests match 10354d58 byte for byte. This split deliberately moves the runtime tests out of the SDK PR, as authorized by the user.

For append-only checking, the preserved SDK test layout is recorded in validation-only commit d65c48f60fa181c019d2be273624f30961a2948d, parent 10354d58. Its only tree changes are removal of the relocated artifact test file and the exact extraction of the runtime status helper/regression from the mixed follow-up file. It contains no production-code changes. SDK gates compare against that audited layout, preserving the prior approved SDK test contracts. Independent build/test checks run on the actual SDK-only tree against main's runtime modules.

All SDK card gates passed on the SDK-only tree: append-only preservation, Ruff lint/format, Pyright, parallel full tests with >=95% coverage, notebooks, build and distribution. Focused SDK regressions: 32 passed. Independent review found no dependency on the extracted runtime code.

Both merge orders apply cleanly to main and produce identical combined trees. Combined production source files match 10354d58 exactly. Evidence is in docs/work/assets/report-runtime-split-validation.json. Existing source assertions were relocated, never weakened.

Wisdom: keep the cohesive SDK case/recovery/export pipeline together; extract the isolated runtime adapter and its tests. No new production behavior, dependencies, schemas or paid calls. New nonblocking SDK findings supplied during the split remain follow-up work; this extraction does not claim to fix them.
