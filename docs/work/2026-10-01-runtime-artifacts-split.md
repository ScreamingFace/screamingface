---
ticket: OME-1454
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# Persistent local Engine artifacts

## Intent

Separate the runtime artifact-directory work from PR #1156 so both runtime and SDK changes can land against main in either order. The user authorized this two-PR split.

## Planned changes

Relocate the three runtime modules, their existing artifact-directory tests and relative-status regression into a main-based runtime branch. Keep SDK persistence, case indexing, recovery, streamed atomic export and notebook pagination in #1156. Split current documentation by ownership while retaining historical ledgers.

## Test plan

Run the runtime regressions on main before transplanting implementation (RED). Preserve each moved test definition exactly and audit that no original source/test changes are lost. Run every SDK card gate independently on both branch trees and verify conflict-free composition in either merge order. No paid model calls.

## Acceptance

Each branch builds/tests against main without the other, has no dependency on the other PR, and both combined preserve the source implementation at 10354d58. Runtime source lives only in the runtime PR; SDK imports have no dependency on the extracted artifact configuration.

## Outcome

Runtime tests first failed on main because ARTIFACTS_DIR_ENV and the extracted behavior were absent. After transplant, 20 runtime artifact/status tests pass. Both test modules preserve their source assertions; the three runtime modules match 10354d58 exactly.

All SDK card gates passed independently against ba1545d8: append-only tests, Ruff lint/format, Pyright, parallel full pytest with >=95% coverage, notebook validation, build and distribution. Independent standards/spec reviews confirm no dependency on the SDK report PR. Both merge orders are conflict-free and their combined production sources match 10354d58 exactly.

Wisdom: the local runtime adapter is an existing configuration boundary; reader/writer parity and absolute serving-path recording belong together. Retention and hosted storage remain unchanged. No new dependency or paid calls. Runtime tests use stubs and do not reproduce a reboot.

The user authorized two independently mergeable PRs. The runtime branch is prepared and pushed. The user approved the exact ticket metadata; OME-1454 was created under E5 (OME-1294), assigned to the authenticated user, with client-sf/agentic/autonomous labels and High priority. The runtime PR targets main independently of SDK #1156, which has already been updated to SDK-only scope.
