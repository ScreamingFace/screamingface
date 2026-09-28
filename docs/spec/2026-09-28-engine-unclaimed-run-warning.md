# Spec — warn the client about an unclaimed queued run

- Status: approved for build (user, 2026-09-28: "spec + plan, then code")
- Component: `apps/screamingface-engine` (control plane)
- Parent epic: OME-1086. Residual gap of OME-1059 and OME-948 (both closed as superseded).
- Ledger: `docs/work/2026-09-28-engine-unclaimed-run-warning.md`

## 1. Problem

The App admits a run and publishes it to the durable run queue. If no worker claims it (the
pool is scaled to zero, the worker Pods are Pending, or all slots stay busy), the run stays
`scheduled`. The WS bridge sends only heartbeats. The client gets no signal for up to
`capability_lifetime_s` (58 800 s, about 16 h 20 min). Then a late claim writes
`queue_expired`.

A second, smaller gap: a broker failure inside `QueueJobRunner.schedule()` (not a capacity
refusal) is not translated. The admission read (`RunQueue.depth()`) and the publish
(`RunQueue.publish()`) raise `nats.errors.Error`. Nothing catches it. The client gets a naked
HTTP 500 with a plain-text body.

## 2. Requirements

### 2.1 Unclaimed-run warning (warn only)

- R1. When a run that this App scheduled has no frame on its event stream for longer than
  `unclaimed_run_warn_s`, the App sends ONE `warn` `LogEvent` to the topic's attached
  connections through `ConnectionRegistry.notify` (the existing notice channel).
- R2. At most one notice per run. The decision for a topic ("warned" or "started") is kept
  until the runner forgets the topic (capability expiry).
- R3. Never for a run that started. Any frame on the stream (a `StartedEvent`, a log, a
  terminal frame) means the run is not unclaimed. `QueueJobRunner.status()` is the one source:
  `scheduled` is the only status that warns.
- R4. Generic text, no internals: "the runner service is at capacity; your run is queued and
  has not started yet". Attribute: `run.wait_s` (whole seconds). No queue depth, no pod,
  subject, bucket or broker names.
- R5. No audience, no notice and no decision. A topic without a subscriber is checked again on
  the next sweep, so a client that reconnects while the run is still queued gets the notice.
- R6. An unreadable stream tail (`QueueReadError`) is UNKNOWN. No notice, no decision; the next
  sweep retries.
- R7. Advisory only. The warner never stops, fails, or reschedules a run. A failure inside a
  sweep never kills the loop.
- R8. Setting `unclaimed_run_warn_s` (env `URL4_CLOUD_UNCLAIMED_RUN_WARN_S`), float, `>= 0`,
  default 300. `0` disables the warner. The Helm chart renders it into the App ConfigMap
  (`config.unclaimedRunWarnS`), beside `orphanGraceS`.
- R9. Layering: the new module is control plane. It imports only `notices` (a shared leaf),
  `adapters.jetstream` (a shared leaf, for `QueueReadError`), and `url4.streaming`. It is
  listed in `CONTROL_PLANE` of `.claude/scripts/check_layering.py`, like `reaper`.

### 2.2 Broker failure at schedule time

- R10. `QueueJobRunner.schedule()` translates `nats.errors.Error` from the admission read and
  from the publish into `RunQueueUnavailable` (new, in `runner_queue.py`). The reservation that
  the attempt made is released (existing `BaseException` path).
- R11. The REST edge maps `RunQueueUnavailable` to RFC 9457 503, title "Service Unavailable",
  detail "the run queue is unavailable — retry shortly", header `Retry-After: 5`.

### 2.3 Alert rules

- R12. No chart in this repo ships alert rules (no `PrometheusRule`, `ServiceMonitor` or
  `PodMonitor` in `apps/*/deploy` or `apps/*/charts`). The OME-1092 ledger
  (`docs/work/2026-09-02-OME-1092-chart-cutover.md`) says alert rules live in a separate repo. So this unit adds NO alert rules. The ledger records a precise
  proposal as a follow-up.

## 3. Design

### 3.1 Parts

| Part | Where | Role |
|---|---|---|
| `UnclaimedRunWarner` | `screamingface_engine/unclaimed.py` (new) | Policy only. No FastAPI, no task, no `ws` import. |
| `QueueJobRunner.accepted_ages()` | `adapters/queue_runner.py` | Sync snapshot: topic → seconds since this replica accepted the run. Reads the existing `_scheduled_at` record. |
| `_install_unclaimed_run_warner` | `app.py` | One process-wide sweep task, modelled on `_install_orphan_reaper`. |
| `RunQueueUnavailable` | `runner_queue.py` | Typed broker failure at schedule time. |

### 3.2 Sweep algorithm

```
for topic, age in runner.accepted_ages():
    if age < grace or topic in decided: continue
    if not await registry.has_subscriber(topic): continue      # R5
    try: status = await runner.status(topic)
    except QueueReadError: continue                            # R6
    decided.add(topic)
    if status == "scheduled": registry.notify(topic, warn(...)) # R1, R3
decided &= set(accepted_ages)                                  # R2, bounded
```

Cost: one stream-tail read per run in its lifetime (plus retries on an unreadable tail). A run
that started before the grace is read once, after the grace, and never again.

### 3.3 Why its own process-wide task, and not the reaper's loop

The requirement is "no background task per run". This design has none: one task per App
process, like the artifact sweeper, the reaper, the max-deliveries advisor and the events
store monitor. It does not share the reaper's loop, for three reasons:

1. The reaper's loop does not exist when `orphan_grace_s = 0`. Sharing it would make an
   operator who turns off reaping also turn off a client-visible notice, with no sign.
2. The reaper's cadence is `orphan_grace_s / 8`. The warner's cadence is derived from its own
   grace (`grace / 8`, floor 1 s), the same rule. Two policies on one cadence is the "two
   knobs that disagree" shape `reaper.py` rejects.
3. The reaper listens to audience edges (the registry has ONE listener slot). The warner polls
   the runner's accepted set. They have different inputs.

### 3.4 Why the default is 300 s

- The noise lesson (`14982d83`, in PR #822): the queue-position notice fired on EVERY run on a
  healthy stack. This notice must fire only on a real wait.
- On a healthy stack a claim is fast: `publish()` sends a wake-up nudge, and an idle `pull`
  claims the message at once (OME-1091 F6). The normal claim wait is seconds.
- 300 s is two orders of magnitude above that. A run that waits 5 min has met a pool that is
  saturated or not there. The text "at capacity; queued; not started" is true in both cases.
- 300 s is small against the 16 h silence it replaces, and it is above the reaper grace
  (120 s), so a client that loses its socket is reaped before it can be warned.

### 3.5 Clock

The age comes from the runner's own record and clock (`_scheduled_at`, the capability-validity
input). This keeps one record of "when accepted". An NTP step can move one notice early or
late. The notice is advisory (R7), so this is acceptable; the reaper's monotonic rule protects
a run STOP, which this is not.

### 3.6 Known limits (accepted)

- A run that starts between the status read and the notify can get the notice just before its
  `StartedEvent`. The window is one broker round trip.
- A sync `GET /?q=` caller has no WS and gets no notice (no notifier exists for it).
- A socket that attaches after the notice does not get it.
- Per replica: only the replica that scheduled the run warns (the App runs `replicaCount: 1`).

## 4. Out of scope

- Failing a run fast, or a typed terminal error, for an unclaimed run.
- OME-1093 (NATS restart drill), deploys, the infra repo, SigNoz, Linear, Asana.

## 5. Open questions (owner decision)

- Q1. Should an unclaimed run FAIL after a bound shorter than 16 h (a typed terminal error,
  for example `Terminated(failed, run_not_started)` plus a tombstone so a late claim skips it)?
  This spec only warns.
- Q2. Where must the queue alert rules live (SigNoz, or a `PrometheusRule` in the chart)? See
  the ledger follow-up for the proposed rules.
- Q3. Is 300 s the wanted default for the notice, or does product want a different bound?
