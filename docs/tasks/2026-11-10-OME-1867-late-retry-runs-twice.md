---
id: OME-1867
linear_url: https://linear.app/openmined/issue/OME-1867/a-run-re-sent-after-the-run-queues-duplicate-window-can-execute-twice
status: triage
type: bug
priority: medium
labels: [bug, screamingface-engine, agentic, autonomous]
parent:
created: 2026-11-10
closed:
---

# A run re-sent after the run queue's duplicate window can execute twice on two worker pods

The run queue deduplicates a re-sent start only within its 120 s duplicate window. A Client
retry stored after it is a second message for the same run. The worker checks whether another
pod runs a topic only on redelivery, so two pods claiming the two copies at once both run them,
and every model call is paid twice. Behaves the same on `main`.

Possible fixes: probe ownership on every claim (a broker round trip per run start), or skip a
first delivery whose topic already has frames (needs proof the App writes no frame before the
claim).

Found in the OME-1859 review loop; recorded in its spec's Out of scope section.
