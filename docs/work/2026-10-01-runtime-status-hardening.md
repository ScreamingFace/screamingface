---
ticket: OME-1454
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# runtime-status-hardening — report serving storage honestly

## Intent

Fix two runtime PR #1217 review findings: status must not infer a legacy process's
artifact location, and permissions anywhere in size inspection must yield unknown.

## Planned changes

- _runtime/cli.py: optional recorded path, restart guidance, guarded stat/list sampling.
- New test_runtime_status_hardening.py: active legacy state, inspecting env mismatch,
  real filesystem permission failures at parent and entry, deletion and absence.
- Runtime spec and PR description: document unknown legacy storage and permission size.

## Test plan

Write failing status tests before implementation. Existing tests stay unmodified.
Verify JSON null/human guidance for active legacy state and serving-state path precedence.
Use real POSIX permissions for inaccessible parent and listable/nonsearchable directory.
Keep zero for absent folders, skip concurrently deleted files, and treat disappeared
folders as absent. Full SDK card gates against 06fa9e91, review before commit/push.

## Acceptance

Both findings fixed and tested in runtime PR; SDK PR #1156 remains independent.
No Engine settings/wire/retention change and no review comments posted.

## Outcome

- **Actual files:** planned CLI/new regression file, runtime spec and ticket mirror.
- **Commit:** `fix(runtime): report unknown legacy storage and inaccessible size` (this unit).
- **RED:** both legacy cases reported the unrelated default path; actual inaccessible-parent and nonsearchable-folder permissions raised PermissionError; directory disappearance raised FileNotFoundError.
- **GREEN:** 11 new cases and 31 focused runtime tests passed, including real unprivileged POSIX permission enforcement. The existing 20 tests remain unmodified. Adoption retains legacy unknown storage instead of inventing a state value.
- **Gates:** `packages/screamingface/.venv/bin/python -u .claude/scripts/run_gates.py screamingface --base 06fa9e91` — ALL GATES GREEN. Append-only tests, Ruff, Pyright, full parallel pytest/95% coverage, notebooks, build and distribution passed.
- **Reviews:** separate SF standards/spec reviews found no actionable defect and each ran all 31 focused tests.
- **Deviations:** included directory disappearance and invalid relative/blank state paths as the same inspection boundary. Corrected the new adoption fixture to include legacy schema_version 1, and reran the full gates. No prior test changed, paid calls, Engine/SDK wire changes or posted review comments.

## Wisdom and confidence

The state record is the only authority for a running process's artifact path. Missing
observations remain unknown; restarting can record a new process's effective directory.
Permission errors remain distinct from absence on supported Python versions through
explicit stat, rather than is_dir error suppression. Sampling tolerates concurrent
retention deletion and leaves service health untouched. Tests use actual permission
failures, restore modes in finally, and skip only platforms/users without POSIX permission
enforcement. This changes no retention policy and does not claim full OME-1448 coverage.
