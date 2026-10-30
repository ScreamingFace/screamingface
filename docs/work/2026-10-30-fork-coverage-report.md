---
ticket: OME-860
stack: repo
status: in_progress
started: 2026-10-30
finished:
---

# fork-coverage-report - keep fork tests green after coverage passes

## Intent

Keep `screamingface-tests.yml` authoritative for fork pull requests. Python tests and the 95%
coverage threshold remain mandatory, while the optional coverage comment runs only when GitHub can
provide a write-capable same-repository token. Never switch to `pull_request_target` for untrusted
fork code.

## Planned changes

- Add a repo regression test pinning the fork guard on the coverage-comment step.
- Add the matching `if` condition to `.github/workflows/screamingface-tests.yml`.
- Add this ledger and the OME-860 task mirror to external contribution PR #1553, where the defect
  was reproduced after all Python checks passed.

## Test plan

- Run the new repo test RED before changing the workflow.
- Run the repo gate.
- Rerun PR #1553 fork CI and confirm both Python lanes and E2E replay are green.

## Acceptance

- Same-repository pull requests retain the coverage comment.
- Fork pull requests skip only the comment step.
- Test execution and `--cov-fail-under=95` remain unconditional.

## Outcome

- **Actual files:** `.github/workflows/screamingface-tests.yml`,
  `.claude/scripts/tests/test_fork_workflow_guards.py`, `.claude/sdlc.local.md`, this ledger and
  the OME-860 task mirror.
- **Commits:** the branch follow-up `fix(ci): skip coverage comment for fork pull requests`.
- **Gates:** the new regression was RED before the workflow condition and GREEN after it;
  `run_gates.py repo --base origin/main` ALL GATES GREEN. The check also pins that
  `--cov-fail-under=95` remains unconditional.
- **Deviations:** OME-860 originally added `pull-requests: write`; it was restored because fork
  tokens remain read-only by GitHub policy, which that permission cannot override. The defect was
  reproduced twice after Python 3.12 tests and coverage passed; both failures were solely the
  coverage action's `Resource not accessible by integration` write-back error.
