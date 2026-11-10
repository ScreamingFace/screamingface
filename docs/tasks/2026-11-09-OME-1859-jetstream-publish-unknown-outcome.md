---
id: OME-1859
linear_url: https://linear.app/openmined/issue/OME-1859/a-jetstream-publish-with-an-unknown-outcome-is-treated-as-failed
status: backlog
type: bug
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1785
created: 2026-11-09
closed:
---

# A JetStream publish with an unknown outcome is treated as failed

`RunQueue.publish()` can store a run's message and then time out or be cancelled before the
acknowledgement arrives. `QueueJobRunner.schedule()` then frees the admission reservation and
answers 503, but the stored message still runs, with no slot or status held for it.

Fix: settle the unknown outcome before freeing the slot, by looking the message up by its id
(`Nats-Msg-Id` is the topic) or by keeping the run counted until broker evidence settles it.

Found in the PR #1648 review (`OME-1810`); it predates E5 P1.
