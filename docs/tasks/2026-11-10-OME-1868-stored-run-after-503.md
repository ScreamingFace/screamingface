---
id: OME-1868
linear_url: https://linear.app/openmined/issue/OME-1868/a-run-the-broker-stored-despite-its-starts-503-can-still-execute
status: triage
type: bug
priority: medium
labels: [bug, screamingface-engine, agentic, autonomous]
parent:
created: 2026-11-10
closed:
---

# A run the broker stored despite its start's 503 can still execute

A start whose own send times out may still be stored, and the stored run can be claimed and
executed after the start answered 503. OME-1859 keeps it counted against its caller; nothing
stops it: a plain stop writes no tombstone for a topic never recorded as scheduled, a mount call
does not stop its own topic, and the orphan reaper reads a held topic as `not_found`. The run is
bounded by its own deadline. Behaves the same on `main`.

A durable fix probably needs a stop that retries until its tombstone lands, owned by the runner.
Found in the OME-1859 review loop; recorded in its spec's Out of scope section.
