---
ticket: OME-1768
stack: screamingface
status: in_progress
started: 2026-11-06
finished:
---

# Colab analytics recovery — failing regression tests

## Intent

Turn the reproduced Colab analytics failures into executable recovery requirements.
Filip explicitly requested failing tests and reopened OME-1768 to In Progress.

## Planned changes

- New test module: packages/screamingface/tests/test_analytics_colab_recovery.py.
- Spec and plan: 2026-11-06-colab-analytics-recovery-tests.md.
- Reopen the existing OME-1768 task mirror to match Linear.

## Test plan

Setup failures and event-delivery failures must not permanently suppress later
evaluations. Cover sync/async clients, timeout expiration, preserved opt-outs,
healthy delivery and no replay. Mock browser responses and block network access.

## Acceptance

Recovery tests fail for the reproduced behavior. Healthy/opt-out controls and
existing targeted tests pass. Product code and prior tests remain unchanged.

## Original red-test baseline

- **Actual files:** the planned test module, spec, plan, ledger and task mirror only.
  Product code and prior tests are unchanged.
- **Publication:** Filip requested an immediate PR after reviewing the red results.
  Publish the intentionally failing tests as a draft on branch
  `OME-1768-colab-recovery-tests`, based on main `7b7d99d33`.
- **Regression results on current main:** 18 failed, 14 passed. Every failure is
  `Healthy browser was not recovered automatically` at the recovery assertion.
  No collection errors, skips or xfails.
- **Existing targeted coverage:** all 55 tests in `test_analytics_colab.py`,
  `test_analytics_default_colab.py` and `test_analytics_review.py` pass.
  Combined targeted run: 18 failed, 69 passed in 21.01 seconds.
- **Published-wheel validation:** identical 18 failed, 14 passed against the
  unmodified PyPI `screamingface-0.1.11-py3-none-any.whl`, SHA256
  `9cacc99633aa8c4e9e00be0bc88640eb1c49ef79a9be58483b0c96b04de87411`.
  The wheel check copies the new test and existing browser fixture module into
  an isolated temporary pytest directory with collection-time DO_NOT_TRACK=1.
  This avoids current-main runtime fixtures importing APIs absent from 0.1.11.
- **Checks:** Ruff lint and formatting pass for the new test. Git diff whitespace
  check passes. Tests prohibit socket connections and use invalid public client
  inputs, so no production events or paid evaluations occur.
- **Harness correction:** use an absolute source PYTHONPATH when reusing the old
  worktree's virtualenv. The initial relative path made two existing subprocess
  tests import the older editable package; both pass with the corrected path.
- **Deviations:** this unit deliberately stops at RED, as requested. Filip subsequently
  authorized publishing this state as a draft PR. It is not merge-ready: full merge
  gates cannot pass until recovery is implemented. Recovery remains pending; Linear
  and the task mirror remain In Progress.

## Implementation

Filip authorized the fix after PR #1703 and confirmed bounded retries and basic
local status diagnostics. He subsequently approved five seconds for consent
setup and background delivery. The implementation changes the Colab adapter,
prompt scheduling and internal consent revision, with appended failure/race
coverage. The two existing timing test modules are updated only for this approved
contract; the exact test-change manifest records their hashes. The red results above are the pre-fix baseline, not final validation.

## Reproduction of the original defect

From `packages/screamingface`, with the package's test dependencies installed:

```sh
PYTHONPATH="$PWD/src" python -m pytest tests/test_analytics_colab_recovery.py -q --tb=short
```

On the original red-test commit `33ac2d7b3`, the expected exit code is 1,
with 18 failures and 14 passing controls. The fixed branch must pass. The tests
cover both sync and async public clients, state/ID setup failure, real two-second
setup expiration, start/finish event-delivery failure, healthy repetition and
opt-outs introduced after either setup or delivery failure. They inject candidate
failure mechanisms; they do not claim to identify the exact production browser error.


## Final implementation validation

- Recovery now runs from ordinary sync/async client evaluation after temporary
  setup or delivery failure; concurrent callers share pending setup.
- Five-second shared control deadlines and background delivery budgets implement
  Filip's updated decision. Native Python HTTP delivery is unchanged.
- Late replies, stale waiters and pre-recovery operations cannot restore expired
  consent. Saved decline, process disable and DO_NOT_TRACK remain effective.
- Local status exposes sanitized failure codes, stages and setup attempt counts.
  Failed delivery drops pending events; there is no event replay or event retry.
- Focused Colab, recovery, diagnostics, race and setup-error tests: **121 passed**.
- Required SDK gates: **all green** (append-only/approved timing transitions,
  Ruff lint/format, Pyright, full parallel pytest with 95% coverage floor, notebook
  checks, build and distribution checks).
- Required repository gates: **all green**, including mirror/ledger consistency.
- An earlier full-suite run was deliberately interrupted when the approved timing
  contract changed; the final complete run above supersedes it.
- README and `docs/verification/analytics-colab-recovery.md` document the final
  behavior and a public-client Colab smoke test without paid model calls.
- Remaining rollout evidence: real Colab/PostHog verification of the patched
  build. Local simulations do not identify the original browser failure cause.
- PR #1703 is updated with the implementation; CI must validate the pushed commit.
  Linear remains In Progress. No new issue was created.
