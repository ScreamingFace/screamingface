---
ticket: unfiled
stack: screamingface
status: done
started: 2026-10-08
finished: 2026-10-08
---

# Saved report membership — truthful listing and complete deletion

## Intent

Fix the verified listing and deletion defects in PR #1269. Damaged embedded
candidate membership must not hide known sibling results or prevent explicit
whole-evaluation removal.

## Planned changes

- `packages/screamingface/src/screamingface/reports.py`: share validated canonical
  metadata loading with discovery; union lightweight legacy membership and known
  names; delete all locally saved runs sharing the selected evaluation identity.
- New `packages/screamingface/tests/test_report_membership_listing_deletion.py`.
- Record the correction in the existing durable-report spec and plan.

## Test plan

- RED first: canonical and legacy listing with truncated candidate metadata,
  missing sibling results and expected-but-unsaved candidates.
- Listing must not decode raw results; malformed canonical metadata must surface
  named errors; canonical ordering must be retained.
- Deletion by evaluation ID and either saved key must remove all siblings even
  with absent or damaged canonical metadata, preserving unrelated evaluations.
- Existing SDK tests remain unchanged; run all screamingface card gates.

## Acceptance

Truthful lightweight listing and complete identity-based deletion, no API or
dependency changes, all old and new tests passing, gates green before commit.

## Outcome

- **Actual files:** all planned files, including this ledger; no inherited test
  changes and no public signature or dependency changes.
- **Commits:** this unit — `fix(screamingface): honor saved report membership in list and delete`.
- **Tests:** before the fix, 18 failed / 3 passed for the observed metadata defects.
  After the fix and two additional named-error cases, 23 new regressions and the
  existing 36 recovery authority cases passed (59 total); independently rerun.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface --base e525886f6383b7248ff3c032a63210c352d166b6`
  returned `ALL GATES GREEN`: append-only preservation, lint, format, typecheck,
  full parallel suite with the 95% coverage floor, notebooks, build, distribution.
- **Review:** independent Standards and Spec reviews found no actionable issue.
- **Wisdom:** sharing the existing canonical loader avoids duplicate validation;
  legacy discovery uses only metadata. Identity-based deletion matches the public
  contract while preserving unrelated groups. No schema, API, secret, or access
  changes. Tests assert candidate completeness and actual retained/removed files,
  rather than implementation details. Confidence exceeds 95%.
- **Deviations:** none. The user-facing verification notebook gained an isolated
  corruption regression; it is a temporary output, not a repository feature.
