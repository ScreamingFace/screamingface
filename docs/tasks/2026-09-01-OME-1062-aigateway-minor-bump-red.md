---
id: OME-1062
linear_url: https://linear.app/openmined/issue/OME-1062/diagnose-the-aigateway-python-minor-bump-that-breaks-the-test-suite
status: backlog
type: task
priority: 3
labels: [aigateway, agentic, autonomous, task]
created: 2026-09-01
closed:
---

# Diagnose the aigateway-python-minor bump that breaks the test suite (#774)

Dependabot PR #774 (`build(deps): bump the aigateway-python-minor group across 1
directory with 2 updates`) is `MERGEABLE/UNSTABLE`. It is the only Dependabot PR left
open after the 2026-09-01 backlog clear-out, and it is red for a real reason.

Failing checks — `test (3.12)` and `test (3.13)` (runs 33172319416 and 33172323365) plus
`images` (run 33172323029). Both Python versions fail, so this is not a matrix-specific
flake. The group carries two updates; the job is to find which one breaks the suite.

Then either fix forward in `apps/aigateway`, or hold the offending dependency with a
scoped `ignore:` entry in `.github/dependabot.yml` carrying a rationale comment in that
file's existing style — every `ignore:` there names its blocking ticket and states the
trigger that lifts it.

Do not close #774 without a diagnosis. Dependabot re-raises the same red PR next cycle
with nothing learned; the config header records #480 as exactly that failure.

Related: OME-1063 (Dependabot volume), which is where the `ignore:` entry lands if the
decision is to hold.
