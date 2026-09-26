# Implementation notes: uniform executor

This file records where the build deviates from the PRDs, and why. It also records the
residual risks that the build accepts. Read it with the PRD of each phase.

Status: phase 1 (PRD 01) built on branch `exp/uniform-executor`. Exploratory work: the SDLC
steps (ticket, ledger) were skipped on the owner's instruction. Phase 0 is partial: the CHAR
tests of PRD 01 exist; the kind environment and the measurement harness do not exist yet.

## Phase 1 — shared events stream

### Deviations

| # | PRD text | Built | Reason |
|---|---|---|---|
| D1 | EV-H4, EV-D11: after the reclaim, "the stream holds no frame for the topic" | The reclaim (`delete_stream`) purges the subject with `keep=1`. The terminal frame stays until `max_age` (24 h). | The terminal frame is the evidence that a run is over. The worker dedupe gate reads it on redelivery, and App admission reads it to free a caller slot. In the old layout "the per-run stream is gone" was also evidence. A shared stream has no per-run object, and an empty subject is also the state of a queued run. |
| D1a | (not in PRD) | The admission path "stream absent after 90 s ⇒ run finished" (OME-1108, `reclaim_evidence_after_s`) is removed. | With D1 it is not necessary. With a shared stream it is wrong: it would free the slot of a run that waits in the queue for longer than 90 s. |
| D2 | (not in PRD) | Queued-cancel tombstone guard: "no frame and no stream ⇒ no-op" became "no frame and the App did not schedule the topic (`_scheduled_at`) ⇒ no-op". | An empty subject says nothing about the queue. |
| D3 | (gap in PRD) | Redelivery rebase: the first frame that a publisher stores for a run reads the subject tail, and every frame of the run is offset by it. | The url4 producer numbers every run from 1. A redelivered run (`max_deliver=2`, test K7) would write 1..n again on a subject that has 1..k. The client drops those frames as duplicates, and `Nats-Msg-Id=<topic>:<seq>` makes the broker drop them too. |
| D3a | (gap in PRD) | If the tail is terminal when a run starts (the tombstone won the race with the claim), the publisher drops the run's frames. | I-EV4: nothing follows the terminal frame. |
| D4 | Refactor note: callers use `publish_next` | `publish()` sends an unsequenced frame to `publish_next`. The three non-child writers (supervisor, App tombstone, max-deliveries advisor) keep calling `publish()`. | The url4 port contract (`EventPublisher.publish`, `assert_stream_conformance`) publishes unsequenced frames and expects the adapter to number them. Refusing them breaks the port. The child's url4 producer always sequences its frames. |
| D5 | (gap in PRD) | A duplicate `PubAck` in `publish_next` is a conflict only when the subject tail moved. Otherwise the writer retries with a message id that is unique to its frame. | The broker checks `Nats-Msg-Id` before `Nats-Expected-Last-Subject-Sequence`. So a late child frame at the same sequence shows as a *successful* duplicate, not as a conflict. After a full purge, a reused id matches a purged frame. |
| D6 | url4 contract: "purge keeps the counter" | The check moved to the reclaim (`_reclaim_keeps_counting`). `purge` only drops frames. | A full subject purge has no counter to keep, because the producer sequence lives in the frames. `purge` has no production caller for JetStream. |
| D7 | erd.md §10: "After deploy, run `purge-legacy-streams`" | The order is: drain → `admin purge-legacy-streams` (new image) → deploy. Startup fails and names the command while a legacy stream exists. | JetStream refuses `url4-cloud.*` while a legacy `url4-cloud_<topic>` stream holds an overlapping subject (err 10065). |
| D8 | EV-D10 / resume | `StreamNotFoundError` is raised only when the first retained frame is the kept terminal frame and it is above the cursor. For an empty subject the consumer waits. For a live run that lost its oldest frames, it resumes at the head. | A resume cursor is a producer sequence, which has no stream position. A live run that rolled over (EV-D6, ans:Q11) is not finished. |

### Residual risks (accepted)

| Risk | Window | Detection |
|---|---|---|
| A late frame from a dead child lands after the supervisor's terminal frame. The child's frame at `last+1` is dropped as a duplicate id, and its next frame is stored after the terminal frame. | The child has exited before the supervisor classifies it, so only frames that the broker has not processed yet can be affected. This exists in the old layout too. | The tail of such a run is not terminal: the dedupe gate and admission read it as "not finished" until the lease (1 h) ends. |
| A queued cancel is lost after an App restart (D2 uses App memory). | Between an App restart and the claim of a run that was queued before it. | After a restart, `status()` also reports such a run as `not_found`. The App stays at 1 replica by plan (ans:Q1). |
| `events_subject_purges_total` counts only App purges (`DELETE /`). | The runner purges in the child, which has no scrape endpoint. | Documented in the metric help text. |

### Validation done

- Integration against a real JetStream (`tests/integration/test_events_stream.py`, 27 tests).
  This includes EVT-C1, EVT-2..EVT-15, EVT-17, redelivery, conflict races, rollover resume and
  the legacy-overlap startup error.
- Linux container run of the worker spine and the child OOM cap (`RLIMIT_AS` does not work on
  macOS).

### Not done in phase 1

- EVT-16 (NATS restart during a run) and the kind cases K1, K6, K10, K11, K12: they need the
  kind environment (phase 0).
- The throughput measurement (2 000 frames/s): it needs the measurement harness.
