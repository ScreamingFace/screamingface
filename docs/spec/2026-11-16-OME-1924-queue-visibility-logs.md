# OME-1924 (part 1 of 3) — queue visibility in the logs: owner, claim, finish, waiting count

Status: draft for owner approval · 2026-11-16 · epic `OME-1314` · ledger
`docs/work/2026-11-16-queue-visibility-logs.md` · ticket by Khoa (OME-1924), picked up by the owner.

## Intent

On 2026-11-15 all 8 prod runner slots held multi-hour runs (4 of them one HLE run) and three
outside users waited 3–4 h and gave up. On-call could not answer "whose run holds a slot, what
happened to it, when does a queued run start" from the read-only session: the App and runner logs
carry a run id but no owner, the runner logs nothing when it claims or finishes a run, and the
300 s capacity notice says nothing about the queue. This part makes the logs answer those
questions. The admin queue view (part 2) and wait-aware rotation (part 3) follow in their own
units — owner decision 2026-11-16.

## Goals · non-goals · anti-goals

- **Goals.** From App + runner logs alone, on-call names for every run: owner key, Run id,
  Benchmark, Case count, Candidates, accept time, claim time (and how long it waited), finish time
  and outcome. The operator line of the 300 s notice says how many runs wait and how many run.
- **Non-goals.** No queue position for users, no ETA, no admin route, no change to admission,
  the per-caller cap, bucket rotation or the 16 h deadline. No new metrics.
- **Anti-goals.** An email in any log record. Internals (depth, pod, bucket, broker) in the
  user-facing notice text (`unclaimed.py:26` invariant, pinned by
  `test_unclaimed_run_warner.py::test_the_message_names_no_internals`). Per-caller metric labels.

## Constraints (found in recon, 2026-11-16)

- Identity: `runner_queue.caller_key` is the **raw email** (used for the in-flight map and the
  bucket hash; never logged). The loggable key is `runs.records.owner_key(email)` — sha256 of the
  trimmed, lowercased email — the same value run history and aigateway store. Local mode: `local`;
  no identity: `anonymous` (`rest/runs_boundary.request_caller`).
- Benchmark, Case count and Candidates are known at `POST /runs` (`rest/runs.py:208-231`, logs
  nothing today) and live on the Run record; at run start only `run_id` and the candidate index
  are known (`X-SF-Run`, `X-SF-Run-Candidate`, `rest/runs_start.py:63-93`). Unbound starts (no
  Run record) have none of them.
- The queue message carries the accept time as the `ENQUEUED_AT_HEADER` header, which the worker
  already reads (`worker/supervisor._published_at`, `:983-994`). `claim_latency_s` is the pull's
  own duration, not the queue wait — not reusable.
- The App cannot see the fleet's slot total (`slots_total` is a worker-side gauge). It can see
  waiting runs (`job_runner.queue_snapshot()` → depth) and running runs
  (`app.state.runner_demand.fresh().running`, may be `None`).
- Logging style: `%`-formatted `key=value` lines on `logging.getLogger(__name__)`; the one helper
  is `run_evidence.log_scheduled`.

## Approaches considered

**Accepted line.**
- A — *two lines joined by `run_id`* (**chosen**): `run created` at `POST /runs` with the Run
  facts; the existing `run scheduled` line at start gains `owner=… run=… candidate=…`. No DB read
  on the start path; unbound starts still log owner + topic.
- B — one `run accepted` line at start with a `registry.get(owner, run_id)` read: one more DB
  round trip per start, and unbound starts carry no Benchmark facts anyway.
- C — only extend `run scheduled`: cheapest, but Benchmark/Cases stay in the DB, which is what
  on-call cannot read.

**Notice.**
- A — *operator log line gets `waiting=N running=M`; the user's frame gains the attribute
  `run.queue_waiting`; message text unchanged; no slot total* (**chosen**).
- B — log line only: on-call helped, users still blind.
- C — a configured fleet slot total (`replicas × slots`): drifts whenever infra changes replicas.

## Design

1. **`run created` (App, `rest/runs.py` after the record is written).** One INFO line on
   `screamingface_engine.rest.runs`:
   `run created run=%s owner=%s benchmark=%s cases=%d candidates=%d` — `owner` is the owner
   key (first 12 hex are enough for matching; log the full key, it is already the stored value).
   Candidates: the count; names are the caller's and may be long — count only.
2. **`run scheduled` gains identity (App).** `run_evidence.log_scheduled` and the
   `rest/routes.py:403-408` line gain `owner=%s run=%s candidate=%s` (run/candidate `-` when
   unbound). One helper computes the owner key from the request identity so both lines agree.
3. **`run claimed` / `run finished` (runner, `worker/supervisor.py`, logger
   `screamingface_engine.worker.supervisor`).**
   `run claimed topic=%s waited_s=%.0f` right after the claim gates pass (before `_run_child`),
   `waited_s = now − _published_at(msg)`; `run finished topic=%s outcome=%s ran_s=%.0f` in
   `supervise`'s `finally`, `outcome` = the terminal classification already computed at
   `:760-764` (or the early-ack path's own name: `duplicate` — another worker owns the run; `settled` — a terminal frame is already on the stream; `redelivery` — the tail was unreadable and the claim is left for the broker; `error` — the claim raised; an expired or refused run keeps the `failed` it published). The in-process duplicate claim logs `run claim dropped topic=… reason=duplicate` instead — the original run is still executing, so no `run finished` for that topic may appear.
   The runner has no owner key (the message body carries the raw identity env, which is never
   logged); the topic joins the line to the App's `run scheduled`.
4. **Notice (`unclaimed.py`).** The warner takes an optional `demand: Callable[[], RunnerDemand |
   None]` and reads `job_runner.queue_snapshot()`; the operator line becomes
   `unclaimed run warned topic=%s wait_s=%.0f waiting=%d running=%s` (`running=-` when demand is
   unavailable). The frame attributes gain `run.queue_waiting: int`. `UNCLAIMED_MESSAGE` is
   unchanged. Wiring in `app.py:_install_unclaimed_run_warner` passes
   `lambda: app.state.runner_demand`.

## Tests (append-only, RED first)

- `run created`: fields present; the owner value equals `owner_key(email)`; the email string is
  absent from every record (`caplog`).
- `run scheduled`: bound start logs run/candidate; unbound logs `-`; owner key present.
- `run claimed`: `waited_s` from a message with `ENQUEUED_AT_HEADER` N seconds old; fallback to
  `metadata.timestamp`. `run finished`: outcome names for the normal end and one early-ack path.
- Notice: `waiting` and `running` in the log line; `run.queue_waiting` in the attributes;
  `running=-` when demand is `None`; the message text test still passes; silent under 300 s.
- A ratchet: no log record in these tests contains an `@`.

## Left to the builder

Exact field order; whether `log_scheduled`'s signature grows or a second helper is added; the
`-` placeholder spelling for unknowns.

## Follow-ups (not here)

Part 2 admin queue view (needs the owner-key-vs-email decision for the view: owner chose key);
part 3 wait-aware rotation (owner chose oldest-waiting-run-first, per-caller cap unchanged);
a fleet slot total visible to the App; `OME-1880`'s `maxAckPending: 24` handoff risk (comment
posted 2026-11-16).
