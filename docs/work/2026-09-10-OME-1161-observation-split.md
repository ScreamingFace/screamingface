---
ticket: OME-1161
stack: screamingface-engine
status: done
started: 2026-09-10
finished: 2026-09-10
---

# Split observation foundation from activity delivery

## Intent

Owner approved two sequential main-based PRs, explicitly no stacked PRs. Reduce existing
PR 897 to the generic Engine observation foundation. Preserve the full implementation at
local branch `OME-1161-activity-preserved` (01b3a0f1) until the foundation merges.

## Planned changes

Keep observation interfaces/dispatch and connector/executor/run lifecycle hooks. Expose
observer factory injection at Engine composition with an empty default. Remove activity
implementation, deployment changes and activity-specific tests/docs from this PR; preserve
those on the local branch for the later PR. Split existing tests by ownership, adding
standalone generic integration and lifecycle checks. Rewrite PR/task descriptions to identify
foundation delivery and the pending activity PR. The issue remains open across both PRs.

## Test plan

RED: a composition test injects a generic observer and observes actual connector facts.
Then validate no-observer real execution, retries, accounting, failure/cancellation,
observer faults, concurrent/cross-task lifecycle, transport loss and full Engine gates.
No pre-PR tests change. User's split instruction authorizes relocating the activity-only
tests with their implementation; all are retained at the preserved commit.

## Acceptance

PR 897 is main-based and independently green, contains no activity schema/policy/timers
or deployment changes, and does not claim to enable researcher activity yet. No second PR
is opened before this merges. Full implementation is recoverable without force-pushing.

## Outcome

PR 897 now contains five production files: observation ports/dispatch and four execution
integration points. Activity implementation and deployment changes are absent from its final
diff; complete feature and tests remain recoverable at the preserved local branch/commit.
No second PR was opened.

RED confirmed the missing explicit composition injection. 22 focused foundation tests pass,
including real connector retry/completion, unregistered execution/accounting/failure/cancellation,
concurrent and cross-task lifecycle, loss decoration and observer fault handling. Full Engine
gates pass: append-only against origin/main, Ruff lint/format, Pyright, layering and full
suite/coverage (2,731 collected). Both independent reviews report no confirmed findings.

Wisdom: the first PR can merge with zero registered observers and no deployment change.
The next PR has a concrete implementation consumer already preserved; these are not speculative
interfaces. No pre-PR tests changed. Activity-specific tests moved with their implementation by
owner approval; the generic test file retains its foundation assertions. Justifications remain
in the scoped PR and the overall Linear description. The feature issue stays open for PR two.
