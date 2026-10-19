---
id: OME-1667
linear_url: https://linear.app/openmined/issue/OME-1667/admit-the-dynamic-models-a-url4-names-when-the-engine-schedules-the
status: in_review
type: bug
priority: medium
labels: [bug, screamingface-engine, agentic, autonomous]
parent:
created: 2026-10-19
closed:
---

# Admit the dynamic models a url4 names when the Engine schedules the run

Dynamic model admission happened only as a side effect of `GET /v1/model-parameters`, and the
run world copies the admitted overlay at schedule time. A url4 replay (or any client that does
not probe first) that named a dynamically admitted OpenRouter model therefore ran without a
route for it: every Case failed "Answering failed" with 0 gateway calls. The Engine now admits
the dynamic models a url4 names in `_schedule`, before the snapshot, for every client; frozen-copy
replay is skipped. One shared url4 route walker (`benchmarks/expression_routes.py`) serves
admission and install validation.

Ledger: ../work/2026-10-19-url4-replay-admission.md
