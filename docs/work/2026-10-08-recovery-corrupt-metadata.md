---
ticket: OME-1503
stack: screamingface
status: done
started: 2026-10-08
finished: 2026-10-08
---

# Recovery review corrections — malformed metadata isolation

## Intent

Fix the two independently reproduced PR #1269 review defects: invalid saved costs must not poison healthy report recovery; explicit deletion must remove same-identity results even if their full membership cannot decode. Rebase onto current main while preserving production Client defaults, Named Scores, and the authorized recovery surface.

## Planned changes

ResultStore named metadata error normalization and minimal-identity manifest enumeration; grouped recovery settlement and complete deletion; new sync/async corruption/deletion regressions. Refresh the exact API snapshot approval after rebasing, preserve all inherited assertions, and record this correction in the existing spec and plan.

## Test plan

RED first for corrupt reported/archive/root costs and invalid membership deletion by evaluation ID and either saved key. Preserve unrelated groups and return healthy partial reports with result_metadata_invalid. Run all SDK card gates and targeted combined export tests in disposable scratch.

## Acceptance

Both reproduced defects fixed; no schema, public API or dependency additions; current main retained; tests append-only; full SDK gates green before publication. No GitHub comments, paid calls, or merge.

## Outcome

Implemented both review corrections. Actual files match the plan: store.py, reports.py, the new corruption regressions, existing spec/plan, exact snapshot approval and this ledger. No inherited Python tests or assertions changed; the authorized snapshot is rebased onto current main without dropping Named Scores or production defaults.

- RED: all 34 new corruption/deletion regressions failed against the rebased pre-fix implementation for the reviewed failure mechanisms.
- GREEN: 34 new regressions and 89 affected existing tests passed (123 total). The initial sandbox run passed 120 but denied loopback binds for three protocol-server tests; the unchanged tests passed with escalation.
- Combined with pinned #1241 f4fb4b6f: 77 export/atomic/corruption/Named Scores regressions passed in disposable scratch.
- Independent SF reviewers reproduced the original failures against the correction and found no remaining actionable findings. Their focused runs passed 129 tests and 104 tests respectively (overlapping sets; not additive).
- Full SDK runner, `uv run .claude/scripts/run_gates.py screamingface --base origin/main`, returned ALL GATES GREEN: byte-exact approved snapshot transition, append-only inherited tests, Ruff lint/format, Pyright, full parallel pytest at 96% coverage (11,541 statements, 456 missed), deterministic notebooks, wheel/sdist builds and distribution checks. Mirror status and diff whitespace checks passed.
- Rebase base: main 21132c8d006e0315305149ddb3ebead07904bda9. The sole snapshot conflict was resolved by preserving main's production defaults and the already authorized recovery API. Approval pins the exact main and resulting snapshot blobs.
- Wisdom: minimal identity enumeration is shared between grouping and deletion. It does not decode raw Cases or trust metadata-derived paths. Corrupt costs become named errors, and partial recovery preserves healthy candidates. No API, schema, dependency, credential or runtime behavior additions. Confidence exceeds 95%.
- Commit message: `fix(screamingface): isolate corrupt saved metadata during recovery`. Update existing draft #1269; OME-1503 remains open for review/merge. No GitHub comments or paid calls.
- Deviations: used an isolated /private/tmp worktree because the shared checkout is inaccessible; refreshed the existing precise API approval as required by the authorized conflict resolution.
