---
id: OME-1233
linear_url: https://linear.app/openmined/issue/OME-1233/tell-the-researcher-what-kind-of-failure-ended-their-run
status: Done
sub_issues: [OME-1234, OME-1235]
type: task
priority: Medium
milestone: Public Launch
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-19
closed: 2026-09-21
supersedes: [OME-844, OME-1232]
---

# Tell the researcher what kind of failure ended their run

A failed benchmark run reports one name for why — `benchmark_unavailable` — from **86
raise sites** spanning genuinely different situations: missing assets, violated
contracts, exhausted graders, benchmark-author mistakes. The researcher cannot tell
whether to retry, fix their recipe, raise a budget, or report a broken benchmark, and
guessing on a paid run costs money twice.

Fix: split the catch-all into named classes (messages verbatim), set retryable per
class, declare the full list of names in one place, and refuse any undeclared name on
both the engine `Failure` model and the SDK's — bound by a conformance test.

Two landings (engine + SDK), so this becomes an epic with one sub-issue per landing at
pickup; the engine split alone exceeds the ~500-line PR cap.

Full problem statement, diagrams, evidence, and scope guards: the Linear issue body.
