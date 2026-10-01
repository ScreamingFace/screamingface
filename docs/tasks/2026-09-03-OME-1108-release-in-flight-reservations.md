---
id: OME-1108
linear_url: https://linear.app/openmined/issue/OME-1108/release-in-flight-reservations-when-a-run-actually-finishes
status: done
type: task
priority: 1
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-03
closed: 2026-09-28
---

# Release in-flight reservations when a run actually finishes

A caller was permanently locked out of the runner by runs that had already finished. Observed
live on the kind rig: an evaluation of 7 candidates had 1 accepted and **7 refused with 503
"the runner is at capacity"** while `url4-runq` held zero messages, every consumer sat at
`pending=0/ack_pending=0`, and the worker reported 0 of 4 slots busy. The App still held the 8
reservations admitted ~23 minutes earlier.

Root cause: a reservation was released only by `status()` observing a terminal frame — and
`status()` is reached only from the pre-schedule 409 check and the orphan reaper, never from
the WebSocket path the SDK uses — or by `_prune()` at `capability_lifetime_s` (16.3h). The
reaper is disabled in this deployment, silently.

Fix: the runner observes its own finished runs before refusing a caller, reusing the release
`status()` already performs, plus a bounded reservation lease as the backstop.

Ledger: `docs/work/2026-09-03-OME-1108-release-in-flight-reservations.md`

## Close (2026-09-28)

Landed on `main` in `4cdfa920` (#822, 2026-09-08). PR #836 merged into the stacked branch
`OME-1092-chart-cutover`, not into `main`. `d64d5e94` (#1085) later adapted the release to the
shared events stream with no change in behaviour. Closed in Linear on 2026-09-28 with the close
comment.
