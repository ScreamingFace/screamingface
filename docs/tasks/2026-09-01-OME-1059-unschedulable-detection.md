---
id: OME-1059
linear_url: https://linear.app/openmined/issue/OME-1059/surface-unschedulable-runner-jobs-as-a-typed-run-error-instead-of
status: planned
type: bug
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-01
closed:
---

# Surface unschedulable Runner Jobs as a typed run error

Parent: `OME-1064`. First unit to ship — no infrastructure dependency, and it alone removes
the silence.

`_map_status` maps both "Pending, starting soon" and "Pod refused by quota" to `"scheduled"`,
and no watchdog watches the producer, so a run that will never start is indistinguishable
from one about to start. Add an `unschedulable` `JobStatus` and a producer-side watchdog that
publishes a typed `ai.url4.error` when a topic has produced zero frames past a configurable
grace.

Spec §4.1. Plan unit 1.
