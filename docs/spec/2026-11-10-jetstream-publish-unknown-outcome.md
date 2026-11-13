---
ticket: OME-1859
status: approved
---

# A run-queue publish with an unknown outcome keeps its slot

## TLDR

The queue-backed runner admits a start against two limits, the queue's depth ceiling and the
caller's in-flight cap, and then publishes the run to JetStream. A JetStream publish is
at-least-once: the broker can store the message while the publisher sees a failure. The runner
read every failure as "not queued": it freed the caller's slot and answered 503, while a stored
run executed, uncounted and reading `not_found` (#1648 review, NATS 2.10.18).

**The rule:** an outcome the runner cannot know never frees a slot. It is the rule the runner
already applies to an unreadable stream tail (`_release_finished_for`: "UNKNOWN NEVER FREES A
SLOT").

## Decisions

- **D1. Which outcomes are unknown.** The run's own send may have reached the broker when it
  times out, or when the start is cancelled while its publish is in flight. nats-py reports
  every such case as a timeout: a lost acknowledgement, a connection that closed while the
  request waited, and a send it buffered during a reconnect and flushed later. `RunQueue.publish`
  raises `PublishOutcomeUnknown` (a `nats.errors.TimeoutError`) from that send alone, so a
  timeout before it (declaring the stream, connecting) stays a plain, definite one. A cancel
  cannot say whether the send had begun, so it is unknown too. Every other failure is definite:
  `NoServersError`, `ConnectionClosedError` (raised before the send), JetStream's own 503 and
  `NoStreamResponseError` (nothing served the stream, so nothing stored; this one used to
  escape as a plain 500 and is now a retryable 503 too), and any error a retry cannot cure.
- **D2. An unknown outcome holds the attempt's reservation.** The caller's slot stays counted
  and the start answers as it does today: 503 `RunQueueUnavailable`, or the cancellation. The
  topic gets no `scheduled` record, so its status still comes from stream evidence alone and the
  Client's retry of the same start passes the 409 pre-check. Each attempt holds only its own
  reservation. A stop's marker releases nothing: it is set before the stop's tombstone lands,
  and the tombstone can fail.
- **D3. The cap counts a held start once, so a retry is counted once.** The per-caller in-flight
  cap counts each live attempt, as before, so concurrent starts stay bounded; but a topic whose
  attempts are all held counts once, however many timed out, since together they are at most
  one run. The topic being started counts its live attempts only: its held ones are this same
  run, so they never refuse its retry. The retry's publish is deduplicated on the topic
  (`Nats-Msg-Id`) when an earlier attempt was stored, and stores the run when none was. A
  topic with a landed attempt is counted by that attempt alone: held attempts beside it add
  nothing, and end as D4 says. A retry that fails outright releases its own reservation and
  leaves the earlier holds.
- **D4. What frees a held reservation.** The run's terminal frame, a stop's tombstone included,
  seen by the admission path's observation, which a caller at its cap makes before it is
  refused (for a held topic the tombstone is a Run cancel's: a plain stop writes nothing for a
  topic the runner never recorded as scheduled and that has no frame); the one-hour
  reservation lease; and the point where the run, if stored, can no longer exist. A stored message is claimable until its
  deadline past its enqueue stamp, and a run claimed just before then runs for one deadline
  more, plus the stream grace and the worker's kill margins. So a hold ends at twice the run's
  deadline plus a 300 s slack after the attempt, or at the lease, whichever is first. The slack
  is the 60 s stream grace plus the worker's 40 s of kill margins plus 200 s of headroom. The
  run queue writes the grace into every message from that constant (5 s for a direct run), so
  no deployment setting changes it; tests pin the slack against both the grace and the margins.
- **D5. Accepted cost.** A start that was never stored and never retried holds one of its
  caller's slots: about six minutes for a direct (mount) run, whose deadline is 35 s by default,
  and up to the one-hour lease for a hosted run. The depth ceiling is unaffected: the
  reservation counter resets on every depth refresh, and the broker's depth is the truth.

## Rejected

- **Re-sending the publish with the same id.** It cannot settle anything while nats-py
  reconnects, since both sends are buffered and both time out, and a late re-send can land
  outside `duplicate_window` and store the run twice.
- **Waiting for the publish after a cancel.** It holds a cancelled task for seconds, skips the
  mount handler's stop of its run, and in this App only shutdown cancels a start mid-publish.
- **A retry taking the held reservation over.** Keeping one reservation per topic and handing
  it between attempts needed the hold, its renewal and every attempt's take-over kept in step
  by hand, and each concurrent interleaving broke one of them. One reservation per attempt has
  no shared state between attempts.
- **Stopping a held topic from the stop path or the mount handler.** A plain stop that
  tombstoned and marked a held topic refused a plain start's retry with the Run-only
  `run_canceled`, and kept the marker when its tombstone failed; a mount call stopping its own
  topic after a 503 tried once, in the same outage, from a task nothing drained at shutdown.
  Both changed paths this fix does not need; they keep their behaviour from before.

## Out of scope

- A start that saw a bound stop's marker after its own publish landed releases its slot. That
  is #1648's contract (spec D12): the stop's tombstone keeps the run from executing. A tombstone
  that failed to land is the stop's own failure, answered by the stop as a retryable 503.
- A run stored though its start was answered 503 can still execute, as before: a plain stop
  of the topic writes no tombstone (the runner never recorded it as scheduled), a mount call
  does not stop its own topic, and the orphan reaper reads a held topic as `not_found`, which
  it must, or the Client's retry would be refused with a 409. This fix keeps such a run
  counted; the run itself is bounded by its own deadline (35 s for a direct run). Tracked in
  OME-1868.
- A retry that arrives after the stored run already ended is admitted, deduplicated and answered
  202, and its reservation is kept until the lease, since the run's terminal frame predates it.
  That is how any re-start of an ended topic behaves today; it is not changed here.
- Two callers starting one topic share one run, but each caller's attempts count against its own
  cap: a landing by one does not end the other's hold, which stays until the run's end is seen
  or it runs out. The conservative direction for a case capability tokens rarely produce.
- A retry stored past the broker's duplicate window (120 s) is a second copy of the run. A
  worker acks away a copy claimed after the run started or ended, but two pods claiming the two
  copies at once can both run them: the ownership probe runs only on redelivery. That is how a
  late retry behaves today too; this change counts the run once, as before. Tracked in
  OME-1867.
- A tombstone written after a worker claimed the run is still a terminal frame, so observing it
  frees the topic's holds, as it frees any reservation of a run it ends. The stop's
  confirmation ask cancels a run claimed in that window; only a worker that claimed the run and
  stopped answering control asks escapes, and the stop path cannot stop that run either.
