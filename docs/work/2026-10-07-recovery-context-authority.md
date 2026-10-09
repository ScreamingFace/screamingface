---
ticket: OME-1503
stack: screamingface
status: done
started: 2026-10-07
finished: 2026-10-07
---

# Preserve healthy saved results during grouped recovery

## Intent

Fix the corrupt-first-candidate defect identified in PR #1269. The owner requested
the fix and a temporary offline JupyterLab notebook exercising current report APIs.

## Planned changes

- Resolve grouped recovery context from the canonical evaluation manifest.
- Preserve legacy recovery when an evaluation manifest is absent by preferring
  a sibling whose local result validates against its decoding context.
- Add sync/async regressions without modifying inherited tests.
- Create an untracked user-facing notebook outside the repository.

## Test plan

Reproduce corrupted first membership through the public report ID before fixing;
cover canonical context, legacy context, healthy local siblings, missing artifacts,
and explicit candidate keys. Run SDK gates and execute all offline notebook cells.

## Acceptance

Healthy siblings remain in partial_report for both recovery APIs. Existing saved
directories remain readable, and recovery never reruns models. Notebook runs from
start to finish against the fixed SDK and writes only into its own temporary folder.

## Outcome

- **Actual files:** reports.py, 36 new sync/async regression cases, and spec/plan
  follow-up records. The temporary notebook and launcher live outside the repository.
- **Commits:** fix(screamingface): preserve healthy siblings during saved report recovery.
- **Gates:** final complete SDK card runner ALL GATES GREEN against b83b9670:
  append-only inherited tests and approved snapshot transition, lint, formatting,
  Pyright, full parallel suite with unchanged 95% coverage floor, deterministic
  notebooks, wheel/sdist builds, and distribution checks. No test exclusions.
- **Regression evidence:** 16 initial failures, six membership/storage failures,
  and four missing-result fallback failures reproduced before their fixes. All
  36 added cases pass; 88 focused new and inherited recovery cases passed.
- **Notebook:** all 38 cells executed against this checkout, including optional
  Inspect export. A dedicated SDK kernel and localhost JupyterLab server were
  prepared. The notebook touches only synthetic temporary data by default.
- **Wisdom:** use existing canonical metadata and decoding contracts; no public
  API, dependency, storage schema, or inherited assertion changed. Legacy fallback
  preserves every known sibling instead of claiming false completeness.
  Independent final review found no remaining actionable issue.
- **Deviations:** none in runtime scope. The original PR's known main API-snapshot
  conflict and #1241 prerequisite remain separate merge prerequisites.
