---
ticket: OME-1031
stack: screamingface
status: done
started: 2026-09-29
finished: 2026-09-29
---

# report-accounting-token-unknowns — preserve partial token uncertainty

## Intent

Fix the owner's P2 finding on PR #1097: newly populated member usage reaches a renderer
that replaces unknown input/output tokens with zero. Keep missing counts explicit.
Continue in the existing clean PR worktree and reuse OME-1031.

## Planned changes

- `report_view.py`: require both token counts before showing their total; preserve each
  missing component in the input/output receipt with the existing em-dash marker.
- New `test_accounting_token_unknowns.py`: evaluate retained partial accounting through
  actual member projection and full report rendering, including zero and complete controls.
- Append the existing accounting spec and plan with this narrow correction.

## Test plan

- RED first for input/output pairs (10, None), (0, None), (None, 10), (None, 0).
- All-unknown, known zero, and complete nonzero controls.
- Assert decoded member usage remains partial, rendered member total stays unknown, and
  the receipt preserves the known half without inventing a zero.
- Run existing rendering/accounting tests and full Client gates, append-only against
  pre-follow-up head 5b2d5d6935f57e41dde45e184f393ca29d0af83b.

## Acceptance

Unknown input OR output means unknown total. Known zero + known zero remains zero.
Retained accounting, scores, and root usage are unchanged. No previous tests modified.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** shared report renderer, new seven-case evaluation/rendering regression,
  existing spec/plan clarification, and this ledger; no prior tests changed.
- **Commits:** `fix(client): preserve unknown token counts in reports` (containing this ledger).
- **Gates:** 46 focused tests passed. ALL GATES GREEN via `run_gates.py screamingface
  --base 5b2d5d6935f57e41dde45e184f393ca29d0af83b`: append-only check, Ruff lint/format,
  pyright, full pytest with >=95% coverage, notebooks, build and distribution.
- **Deviations:** first gate caught optional-value narrowing omissions in the new tests;
  added explicit assertions and reran all gates successfully. No production design deviation.

## Reproduction and review

The new evaluation-to-HTML regression failed for all four partial-count pairs and passed
its three complete/all-unknown controls before the fix. Existing member projection already
preserves `None`; the shared formatter's `or 0` caused the false total. A small direct
reproduction made speculative hypotheses and temporary instrumentation unnecessary.

After the renderer fix, all 46 focused accounting/report tests passed. The first gate run
caught missing optional-value assertions in the new test fixture; added those assertions
before rerunning, with no production behavior or prior-test changes.

Wisdom review: retain one shared formatter for Candidate/member totals, keep the established
unknown marker and existing all-unknown split, and preserve genuine zeros. No dependency,
public API, wire, schema, score or logging change. Tests exercise the real evaluation and
rendering path and verify that rendering does not mutate report JSON. No debug code remains.
The same plain-text marker works in the existing light/dark styles; no visual styling changes.
