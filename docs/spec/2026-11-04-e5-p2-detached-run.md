---
status: approved   # owner approved 2026-11-11 (§10)
issue: OME-1837    # one sub-issue per PR is filed under it
parent: OME-1294   # E5 · Improve managing runs in SF Client
tickets: OME-1611, OME-1617
builds_on: docs/spec/2026-10-27-e5-p1-first-class-run.md
date: 2026-11-11
base: origin/main bc951ce61
---

# E5 P2: a detached Run (start it, walk away, come back)

## 1. Purpose

`sf.evaluate(..., detach=True)` returns a `Run` at once. The Engine owns the Run until it ends,
and its owner reattaches by `run_id` from any notebook or machine (`OME-1611`). A Run nobody comes
back to still stops on its own, at a deadline. A default `evaluate` still blocks, returns a
`Report`, and still stops when nobody is listening.

To get there, **the Engine drives the fan-out for every `evaluate`**, attached or detached. The
Client sends the Run once, follows it and builds the Report. It never starts a Candidate. Attached
and detached Runs are the same Run; the only difference is what stops one that nobody follows.

P2 builds on P1 (the Run record, its owner, states, settling and retention). It changes who
starts Candidates, where a Candidate's result lives, and what stops a Run.

## 2. As-is (verified at b2e65c8c8)

Engine paths are relative to `apps/screamingface-engine/src/screamingface_engine/`, except
`deploy/helm/`, which is under `apps/screamingface-engine/`. Client paths start with
`packages/screamingface/src/screamingface/`, shortened to `sf/`.

**Starting**

- **The Client drives the fan-out.** It keeps as many Candidates in flight as the Engine's
  per-caller cap, 24, which it reads from `GET /v1/limits` (#1744, #1745). Each Candidate mints a
  token, opens its own WebSocket, sends its own start and follows its own topic
  (`sf/_engine/transport.py:259`, `:1309`).
  Candidates not yet started never start once the Client's process is gone.
- **The run queue refuses, it does not hold.** A caller's 25th run in flight gets "at capacity"
  before anything is published (`adapters/queue_runner.py:375`, cap 24 at `runner_queue.py:127`).
  The Client retries that for up to 900 s (`sf/_engine/admission.py:25`).
- **The broker dedupes a repeated start for 120 s,** by topic (`runner_queue.py:76`, `:594`).
- **A worker skips a start it need not run** in three cases (`worker/supervisor.py`): the topic
  already has a terminal frame (`:563`); this worker is already running it (`:435`); or, for a
  redelivery only, another pod answers that it is running it within 0.25 s (`:637`, `:899`, `:125`).
  A pod answers from the moment it takes the message, before its child exists
  (`worker/loop.py:475`). When a worker cannot tell, it runs: "losing runs is worse than
  double-running them" (`worker/supervisor.py:926`).
- **A worker keeps its run's queue message unacked until the run ends,** and the queue delivers a
  message twice at most. A copy declined twice ends the live run as `failed / max_deliveries`, so a
  duplicate is acked away, never returned (`worker/supervisor.py:644`).
- **A worker refuses a run message whose major version it does not know,** with
  `unsupported_spec_version` and before running anything (`worker/supervisor.py:587`). Messages are
  version 2 today (`job_env.py:205`).
- **Two gaps are open on the raw start path:** a late retry can run twice (`OME-1867`), and a start
  can be stored after a 503 (`OME-1868`).
- **An async start needs a listener** (428, `rest/routes.py:265`), and the reaper stops a topic 120
  s after its last listener leaves (`reaper.py:124`). A topic nobody ever attached to is never
  armed.
- **A start carries no credential.** The job reaches aigateway with the caller's email in its env
  (`job_env.py`). The Client's version travels in the start's `User-Agent`.

**Ending**

- **The runner classifies its own run.** The run's child wraps its event publisher in
  `SettlementWatch` (`run_evidence.py:198`), reads the run summary (cost, cache figures, trace id;
  `runner/summary.py:27`) and holds the result. It reports status, error code and cost to its worker
  on a control pipe (`child_protocol.py:78`; the reader's line limit is 64 KiB,
  `worker/warm_pool.py:45`). The worker publishes that as the Candidate's outcome on
  `url4-candidate-outcomes` (`worker/supervisor.py:1321`), a stream that survives restarts, and P1's
  consumer writes it to Postgres (`runs/consumer.py`). A failed publish is logged and dropped
  (`candidate_outcomes.py:231`). An outcome is at most 64 KiB (`:91`).
- **The runner already writes large results to the object store.** A result under 512 KiB rides the
  result frame (`job_env.py:584`, sized to fit one NATS message). Over that, the runner writes it to
  the artifact store under its sha256 (`runner/executor.py:700`); the App only reads and deletes
  there (`artifacts/ports.py:82`). In `s3` mode the bucket's lifecycle rule expires every object
  after 2 days (`deploy/helm/README.md:405`). The App redeems a result frame's artifact ticket at
  `GET /artifacts/{id}`.
- **A Candidate's events are short-lived.** They live on `url4-events` for 24 h (`config.py:345`),
  at most 20,000 frames per Candidate, terminal frame included. 60 s after a run succeeds or is
  stopped, the worker purges them and keeps the terminal frame (`worker/supervisor.py:789`).

**The Client and the Run record**

- **The Client folds a Candidate's events into one small record** (`_RunOutcome`,
  `sf/_core/ports.py:35`, built by `_RunState`, `sf/_engine/contract.py:48`). The frames are used
  for live display and then discarded. A `Report` does not keep them.
- **A Report is built from more than results.** The Client rebuilds one from the compiled Candidate
  and the benchmark's info (`sf/_results/codec.py:21`, `sf/reports.py:303`), which exist only in the
  process that called `evaluate` and in its local store.
- **P1 keeps the Run record, not its results.** The Run stores its owner as a hash and each
  Candidate's name, topic, state, cost and error code. A start binds a topic to its Candidate with
  `X-SF-Run` headers (`rest/runs_start.py:105`); `bind` stores the topic and the bind time
  (`runs/store.py:205`). Registration is best-effort (P1 D7). `Run.report()` reads the local store
  only, and `Run.wait()` returns a `Run` (`sf/runs.py:89`).
- **The App is pinned to one replica.** The start route's listener check and the queue's per-caller
  count are each kept in one pod's memory (`deploy/helm/values.yaml:1-21`,
  `adapters/queue_runner.py:335`).

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **The Engine drives the fan-out for every `evaluate`.** `POST /runs` carries every Candidate's start. The Client compiles, preflights, follows and builds the Report; it never starts a Candidate. | One fan-out: the cap, the at-capacity retry, cancel and the stop rules exist once. Detach and reattach need nothing the attached path lacks. |
| D2 | **Runs are required.** A hosted Engine without its Runs database answers `POST /runs` with 404 `runs_off`, and the Client raises. This replaces P1 D7 and P1's "history never blocks a run". | Under D1 nothing else can start the Candidates. |
| D3 | **The driver is a task in the App.** It starts a Run's next Candidate when one of its owner's 24 slots frees, stops Runs that are orphaned or past their deadline, and settles a Candidate whose outcome went missing (R7). It follows no event stream and writes no results. | The queue refuses rather than holds (§2), so something must keep the waiting Candidates. Keeping that in the App works in local mode, which has no NATS. |
| D4 | **One driver per Run, by a lease in Postgres.** `driver_lease_until` is taken and renewed with conditional UPDATEs; a driver whose renewal changes no row stops. At App start and on every tick, a pod takes the lease of each Run that is live and whose lease is empty or expired. | Exactly one pod wins a lease. An App restart resumes every Run. |
| D5 | **P2 adds nothing to a pod's memory that another pod would need.** The lease (D4) and the follow stamp (D10) are in Postgres, and the event route reads only the registry and the event streams. | The App is pinned to one replica (§2). P2 adds no further reason to stay pinned. |
| D6 | **One topic per Candidate, for its whole life.** The driver mints it at the Candidate's first start and never changes it. When it does not know whether a start landed, it sends the same start again. | Starting is safe to repeat: the broker drops a repeat within 120 s, and a worker skips one whose run is finished or already claimed (§2, D7). |
| D7 | **A worker claims a driver-started run's topic before it runs it.** The claim is a create-if-absent write, with the worker's id, in a NATS key-value bucket; exactly one worker's write succeeds. A worker that finds another worker's claim asks that worker whether it still has the run. On an answer it acks its copy away. With no answer it takes the claim over by a compare-and-set (R3). | A repeated start is a fresh message, which today's cross-pod check, made on redeliveries only, ignores. An atomic write decides between two workers whatever the interval between them. It costs one broker write per Candidate start. It is the guard `OME-1867` needs, applied to driver-started runs. |
| D8 | **The Run keeps what it needs to start its Candidates:** the owner's email, the Client's version, and each Candidate's start (the url4 expression and its flags). A P1 Run holds its owner only as a hash, and no prompt text. | The driver starts Candidates after the Client has gone. aigateway already keeps emails and full prompts in the same Postgres server. |
| D9 | **The runner produces the Candidate's record, and the outcome carries it.** At the end of a run the runner reports the record with its outcome, and P1's consumer writes state, cost and record in one transaction. The Client uses the Engine's record for every Run and stops building its own. | The runner already holds all of it (§2). One writer, one message, one transaction. The outcome stream survives restarts, so an App or database outage loses no record that reached the stream (R7). |
| D9a | **The runner writes every result of a driver-started run to the run-results store,** whatever its size, at `runs/{run_id}/{index}/{sha256}` in a bucket of its own. The record carries the checksum, and the App builds the key from the Run, the index and that checksum; it never reads a key from the runner. Local mode uses a folder in the Engine data dir. | It already writes large results (§2); only the destination changes. One path for all sizes keeps the outcome small. The checksum in the key means a second execution never overwrites the first. The artifact bucket expires everything after 2 days and takes only sha256 keys. |
| D9b | **The Engine keeps the Client's context in the run-results store and returns it to the owner.** With `POST /runs` the Client sends one `context` string holding what it needs to rebuild a Report: the benchmark's info, the selected Cases, and each compiled Candidate without its url4 and seed, which the start holds. The App writes it unread to `runs/{run_id}/context`, up to `run_context_max_bytes` (4 MiB), before it registers the Run, keeps its checksum and size on the Run, and serves it at `GET /runs/{id}/context`. | Without it a Report cannot be built on another machine or after a kernel restart (§2). The Engine never reads it, and an object store suits a blob of megabytes. The checksum lets the Client detect a context that was replaced in the store. |
| D10 | **An attached Run stops when nobody follows it.** The event route stamps the Run's `last_followed_at` while a follower is connected, and the driver's tick stops an attached Run whose stamp is older than `orphan_grace_s` (120 s). | "Runs started the current way should behave exactly as today" (`OME-1611`). |
| D11 | **A detached Run stops at its deadline.** `deadline_at = created_at + deadline`; the default is `run_detached_deadline_s` (48 h), settable per Run up to `run_detached_deadline_max_s` (7 days). Following a detached Run never makes it attached, and an attached Run cannot be made detached. An attached Run gets a deadline only when the orphan rule is off (R10). | The owner knows at start when it ends. The spend cap is P4 (`OME-695`). |
| D12 | **Every stop records its reason:** `canceled`, `orphaned` or `deadline`. The first one wins. A Run stopped by `canceled` reads `canceled`; one stopped by `orphaned` or `deadline` reads `interrupted`. A `pending` Candidate is live until a stop settles it; P1's pending grace is removed. | A Candidate can wait hours behind a full per-caller cap. The grace was sized for the Client's 900 s loop, which is gone. |
| D13 | **The Client follows a Run, not topics.** One owner-checked WebSocket carries every Candidate's events tagged with its index. A Candidate still running replays the events the stream holds; one that has ended sends its record. | One stream is what a live notebook and a reattaching one both need. Past progress lines are not kept. |
| D14 | **`detach=True` returns a `Run`; the default returns a `Report`.** `Run.wait()` follows the Run and returns its `Report`. `Run.report()` works on any machine. Ctrl-C on an attached `evaluate` cancels the Run. | The epic's API. P1's `Run.wait()` returns a `Run`; it is in no release. |
| D15 | **`OME-1617` reduces to following overnight.** A started Run never needs the Client's login again. A follow that outlives the login ends with a message that the Run is still going and how to pick it up. | The job uses the email in its env. The Client has no silent login refresh. |
| D16 | **Compatibility.** A released Client keeps working on a P2 Engine: it starts through the raw start route, which is unchanged, and gets no Run record. A P2 Client on an older Engine raises with the upgrade to make. | The Client tells an older Engine by its answer: it answers the new `POST /runs` body with a 422 or a 404 that has no `code`, and every 422 and 404 a P2 Engine sends there has one. A P2 Engine with Runs off answers 404 `runs_off`, which the Client reports as that, not as an upgrade. |

## 4. Contract

### 4.1 Engine HTTP (changes to P1 §4.1)

| Route | Request | Response |
|---|---|---|
| `POST /runs` | P1's body with `candidates: [{name, url4, answer_seed, capture, use_cache, replay_frozen_copy}]`, plus `context` (a string the Engine does not parse), `detach: bool` (default `false`) and `deadline_s: int \| null` | 201 or 200 with the Run as `?view=summary` reads it; 404 `runs_off` with Runs off; 413 `request_too_large` over `run_request_max_bytes` (8 MiB); 422 `deadline_too_long`, `deadline_needs_detach`, `context_too_large`, or `invalid_request` for any other invalid body (a url4 over 512 KiB as JSON, which one run-queue message could not carry, and a NUL or a lone surrogate in any text, which Postgres cannot hold, among them); 400 `x_profile_unsupported` for a stated `X-Profile`, as on the start route, before the body is read; 503 `result_store_unavailable` when the context cannot be stored, and then no Run is registered; a repeated `client_key` returns the first Run when its starts, `detach` and deadline match, else 409 `client_key_conflict` |
| `GET /runs/{id}` | as P1 | adds `detached`, `deadline_at`, `stopped_by` and `context` (`sha256`, `size_bytes`; `null` for a Run that has none); each Candidate adds `index`, `start` and `record` (`null` until it ends). `GET /runs` (the list) carries neither `start` nor `record` |
| `GET /runs/{id}?view=summary` | as P1 | the Run and its Candidates without `start` or `record`. `Run.progress()` and `Run.refresh()` read this |
| `GET /runs/{id}/context` | owner-checked | the context as it was sent, streamed from the run-results store, for the Client to check against the Run's checksum; 404 `context_not_found` for a Run that has none, or after retention |
| `GET /runs/{id}/events` | WebSocket, owner-checked | the frames of §4.2 |
| `GET /runs/{id}/candidates/{index}/result` | owner-checked | the result bytes, streamed from the run-results store, with their media type; 404 `result_not_found` before the Candidate ends, when it has no result, or after retention |
| `DELETE /runs/{id}` | as P1 | as P1; records `stopped_by: "canceled"` |
| `GET /` (start) | as today | unchanged for raw url4. The `X-SF-Run` binding (P1 R2) is removed |

`owner_email` is never returned. `start` and the context are returned only to the Run's owner, as
every `/runs` answer is. Every 404 and 422 on `/runs` carries a `code`.

### 4.2 Run event stream

JSON objects whose `type` is the frame's name, in order per Candidate:

| Frame | Fields | When |
|---|---|---|
| `candidate.state` | `index`, `state` | when a Candidate becomes `scheduled`, and `running` at its first event; a follower that joins gets each live Candidate's current state first |
| `candidate.event` | `index`, `event` (the Candidate's CloudEvent, unchanged) | each event of a running Candidate; a follower that joins late gets the events the stream still holds, from the oldest |
| `candidate.settled` | `index`, `state`, `record` | once per Candidate, when it is terminal in the registry and the route has forwarded its events up to the terminal frame, if the stream holds one; at once for one that ended before the follower joined. `record` is `null` when no runner reported one (§4.3) |
| `run.ended` | `state`, `stopped_by` | once, after every Candidate's `candidate.settled`; the route then closes the socket with 1000 |
| `heartbeat` | none | every `ws_heartbeat_s` with nothing else to send |

- The route sends every frame. It polls the registry's summary read (§4.4) every `run_events_poll_s`
  (1 s) for `scheduled` and terminal states, loading a record only for a Candidate that has just
  become terminal, and reads each live Candidate's event stream itself. `running` is not a registry
  state; the route derives it. It uses no driver state, so it works on any pod. A registry read that
  fails does not close the stream: the route keeps forwarding events and polls again.
- A Candidate the follower saw live is followed to its terminal frame, even one that ended between
  two polls. One that ended before the follower saw it is settled at once. A terminal frame not
  forwarded within 30 s does not hold `candidate.settled` back.
- With Runs off, no identity, or a Run that is not the caller's, the route accepts the socket and
  closes it with 1008, the reason being the code (`runs_off`, `identity_required`,
  `run_not_found`); when the registry cannot say whose the Run is, with 1013
  `registry_unavailable`, which the Client retries. WHY after the handshake: a close before it
  reaches a client as a bare HTTP 403. A Run deleted while followed closes it with 1008.
- A Candidate's result frame is forwarded unchanged. Its artifact ticket is not redeemable for a
  driver-started run; the Client reads the result route.
- A follower that reconnects gets the same frames again. The Client drops events it has seen by
  their sequence, and does not treat a gap as an error: the stream holds at most 20,000 frames per
  Candidate and there is no replay request.

### 4.3 The Candidate record

Reported by the runner when the run ends, and carried on the outcome:

`started_at`, `completed_at`, `usage`, `cache_hits`, `cache_unpriced_hits`,
`cache_saved_cost_usd`, `cache_saved_cost_archive_usd`, `frozen_copy_id`, `capture_status`,
`capture_replay`, `capture_partial_reasons`, `client_version`, `trace_id`, `error` (`code`,
`message`, `permanent`, `details`; only when it did not succeed), and `result` (`media_type`,
`size_bytes`, `sha256`; absent when there is none).

- **Storable.** Any text in a record has a NUL or a lone surrogate replaced by U+FFFD, and a number
  that is not finite becomes null, wherever the outcome is built or decoded: Postgres JSONB refuses
  them, and an outcome that could never be written would hold back those fetched with it. A record
  nested more than 32 levels is malformed.

- These are the fields of the Client's `_RunOutcome` (`sf/_core/ports.py:35`), plus `error`, which
  the Client raises from.
- The runner computes them by the rules of the Client's fold (`sf/_engine/contract.py:197-331`,
  `:408-467`), from the frames it published, the run's closing summary log among them. Both sides
  are tested against the same recorded runs.
- **Size.** A record is a few KiB. The runner cuts `error.message`, `error.details` and
  `capture_partial_reasons` so the encoded record, measured with non-ASCII escaped as the codecs
  write it, stays under 48 KiB, marking what it cut. If the record is still larger, it reports the
  outcome without it, so state, error code and cost are never lost to a large record.
- A Candidate has no record when no runner reported one: it was stopped before it ran, refused at
  start, lost, its child died before reporting, or its outcome was rebuilt from the stream (R7). Its
  state, error code and cost still come from its outcome. The Client reads a `succeeded` Candidate
  with no record as `run_result_lost`.
- A Candidate has one trace id for its whole life, kept on its row and sent with every start.

### 4.4 Ports and records

- **`CandidateOutcome`** gains `record`. Its 64 KiB limit is unchanged (§4.3 keeps a record under
  it). The outcome stream's size limit rises from 64 MiB to 512 MiB, since an outcome with a record
  is a few KiB.
- **`RunRecord`** gains `detached`, `deadline_at`, `stopped_by` and the context's checksum and size.
  The Run row also holds `owner_email`, `driver_lease_until` and `last_followed_at`.
- **`CandidateRecord`** gains `start` and `record`. The Candidate row also holds its `trace_id`.
  Reads other than `get` load neither. `summary(owner, run_id)` is `get` without them.
- **`RunRegistry`** keeps P1's methods and changes two:
  - `settle(topic, outcome)` also stores the outcome's record, in the same transaction. State and
    error code are first-wins. A later outcome with the same state fills a cost or a record that is
    still empty, and changes nothing else.
  - `mark_scheduled(topic)` also stamps the bind time, so P1's clocks count from the real start.
- It gains:
  - `lease_run(run_id, held_until, until)` and `release_run(run_id, held_until)` (R4);
  - `due_runs(now)`: Runs to drive, Runs past their deadline, attached Runs nobody follows, and
    stopped Runs with stops still owed, each with its owed topics;
  - `pending_starts(run_id)` and `overdue(run_id, before)` (R1, R7);
  - `followed(run_id, at)`, which never moves the stamp back (R10);
  - `stop(run_id, reason, unless_followed_since=None)`, which `cancel` calls (R9, R10);
  - `settle_startless()` (R11);
  - `records(owner, run_id, indexes)`, the named Candidates' records alone, for the event route and
    the result route;
  - `expiring(older_than)`; `expire` takes the Run ids to delete, not a cutoff (R13).
- **`RunResultStore`** (new port): `put(key, body)` for the runner, which already holds the result,
  and for the App, which stores the context; `open(key)`, streaming, `delete(keys)` and
  `delete_older_than(cutoff)` for the App. Adapters: an S3 bucket and a filesystem folder. The S3
  adapter never lists the bucket, so its signer keeps sending one object per request.
- **`IdentityAwareJobRunner`**: `schedule` gains `result_prefix` (`runs/{run_id}/{index}`) and
  `exclusive`, carried in the queue message, which is then version 3. The driver sets both on every
  start and nothing else sets either, so "driver-started", "`exclusive`", "has a result prefix" and
  "version 3" name the same runs. The port also gains `last_frame(topic)`, the topic's newest frame,
  which R7 settles a Candidate from.
- **`RunDriver`** (App): `drive(run_id)` until the Run is terminal.
- **`TopicClaims`** (worker): `claim(topic, worker_id)`, `take_over(topic, worker_id, revision)` and
  `finish(topic, worker_id)`. The adapter is a NATS key-value bucket, `url4-claims`. Its entries
  expire after the event stream's retention (`events_max_age_s`, 24 h), and its replicas and storage
  are the event stream's.

### 4.5 Rules

- **R1 Start.** For each `pending` Candidate, while fewer of the owner's Candidates, across their Runs, are
  scheduled or running than the runner's per-caller cap (`GET /v1/limits`, 24), the driver binds the Candidate's topic (minting it the
  first time; P1 `bind`), schedules it, then calls `mark_scheduled`. Bind to schedule runs inside
  the runner's `start_attempt`, as the start route's does.
  - A start carries what the start route gives a run: the Run's email and client version, a cache
    policy from `use_cache`, model admission as the owner, and `job_deadline_s`. It also carries the
    Candidate's trace, its result prefix and `exclusive`. It carries no enqueue time, so the queue
    stamps each publish.
  - **At capacity:** nothing was published. The Candidate stays `pending` with its topic, and the
    driver tries again after the delay the runner gives.
  - **Queue unreachable, or a publish whose result is unknown:** the Candidate stays `pending` and
    the driver sends the same start again later (D6).
  - **The registry unreachable** while binding, a connection lost mid-query among it: nothing was
    sent, and the same start goes later.
  - **Any other refusal** settles the Candidate `failed` with the refusal's code, or
    `start_refused`, and the driver goes on to the Run's next Candidates: a start the runner does
    not refuse as transient would fail the same way on every retry. A refusal that says it is not
    permanent is retried. A start that lost to a stop is not a refusal; the stop settles it (R9).
  - A `pending` Candidate whose publish is unknown is not counted among those in flight; the
    queue's own hold for that topic covers it.
  - Each pass loads the starts of only as many `pending` Candidates as fit beside the owner's in
    flight, so a Run waiting behind its owner's other Run loads none.
  - A Run that has a stop reason takes no new start (R9).
- **R2 Restart.** A driver that finds a `pending` Candidate with a topic sends its start again. The
  broker, or a worker, drops the repeat if the first one landed (§2, D7).
- **R3 One run per topic.** A worker that takes an `exclusive` start from the queue skips it when
  the run has a terminal frame or is running on this worker. Otherwise it claims the topic (D7). The
  claim comes before every check that could end the run (expiry, message version, world config), so
  a duplicate copy never publishes a terminal frame onto a live run, and it takes the place of
  today's cross-pod check for these starts.
  - **The claim is marked finished:** it acks its copy away.
  - **The claim is new, or names this worker:** it runs.
  - **Another worker holds it:** it asks that worker, by id, whether it still has the run. Only the
    claim's holder answers, and only while it holds the claim, from winning it until it marks it
    finished. On an answer within 0.25 s it acks its copy away. With no answer it reads the topic's
    last frame again and acks its copy away if the run has ended. Otherwise it takes the claim over
    by a compare-and-set on the entry's revision and runs; if another worker took it first, it reads
    the claim again.
  - **It cannot reach the claims bucket, or the step exceeds `topic_claim_budget_s` (5 s):** it
    runs, as a worker does today when it cannot tell (§2).

  A worker marks its claim finished once its run's terminal frame is published, before it acks
  its own message. A copy is acked away, never returned to the queue (§2). Two copies can both
  run only when the claim's holder is alive but does not answer in time, when the bucket is
  unreachable or slow, or when the repeat is sent after the claim and the terminal frame have
  both expired. A second outcome for the topic changes no state (§4.4), and each copy writes its
  result under its own checksum (D9a).
- **R4 Lease.** `run_driver_lease_s` is 60 s, renewed every third of it. A lease is taken by one
  UPDATE guarded on the lease being empty, expired, or the value this driver last wrote. On a clean
  shutdown the driver releases its leases.
- **R5 The record.** For a run started with a result prefix, the runner writes its result to the
  run-results store before it publishes the result frame, and its child reports the record with its
  outcome. A write that fails is retried with backoff for up to `run_result_write_budget_s` (60 s);
  if it still fails the run ends `failed` with `result_store_unavailable`, which is not permanent.
  The child reports only when its own terminal frame landed, as P1 R3 requires. The result frame
  keeps today's shape. A run that carries a result prefix on a pool with no run-results store fails
  `result_store_missing` before any model call. Before any model call, too, the runner writes the
  empty result under the Candidate's prefix (the pool's key may only write), retried as above, so a
  store it cannot reach fails the run `result_store_unavailable` before it spends.
- **R6 The outcome is retried.** For a driver-started run, the worker retries an outcome publish
  that failed because the broker was unreachable or the stream full, with backoff, until the stream
  accepts it or the worker drains. The retry runs apart from the run's queue message, which is acked
  as today, so it holds no worker slot. Any other refusal is logged and dropped, as today.
- **R7 A missing outcome.** On its tick the driver reads the last frame of each `scheduled`
  Candidate's topic. If that is a terminal frame and its time plus `run_outcome_grace_s` (120 s) has
  passed, the driver settles the Candidate from it: state and error code, no cost and no record. The
  Candidate then settles, its slot frees and the follower moves on. If the runner's own outcome
  arrives later, as after a database outage, it fills the cost and the record (§4.4). A run whose
  terminal frame never landed stays for P1's reconcile, which settles it `lost`.
- **R8 Clocks.** A Candidate's 16 h limit counts from the publish that a worker takes. P1's `lost`
  clock counts from `mark_scheduled`, and reconcile never settles a `pending` Candidate.
- **R9 Stops.** Cancel, orphaning and the deadline all go through `stop(run_id, reason)`. While any
  Candidate is live, in one transaction it:
  - sets the reason if none is set, and sets P1's cancel flag;
  - settles `pending` Candidates that have no topic `stopped`;
  - moves `pending` Candidates that have a topic to `scheduled`, stamping their clock, since their
    start may have landed;
  - owes a stop to every live Candidate that has a topic.

  On a Run with no live Candidate it does nothing. The owed stops are made as P1 D12 makes
  them: a queued start is cancelled in the queue, a running one is stopped, and each publishes a
  `stopped` outcome. The in-process runner publishes one too when it holds no task for the
  topic. A stop that fails stays owed, and the driver's tick makes it again. `bind` refuses a
  stopped Run; `mark_scheduled` on one still marks the Candidate and reports that its start
  must be stopped.
- **R10 Followers.** The event route stamps `last_followed_at` when a follower connects, every
  `run_follow_stamp_s` (30 s, or half a shorter `orphan_grace_s`) while one is connected, and when
  it leaves. The driver's tick stops, as `orphaned`, a live attached Run that has starts and whose
  stamp is older than `orphan_grace_s`; a Run never followed counts from its creation. The stop
  checks the stamp again in its own transaction, so a follower that returned in between keeps the
  Run.
  - **The clock runs only while the Engine can record a follow.** After the driver starts, and after
    any tick that could not reach the registry, the tick makes no orphan stop until `orphan_grace_s`
    of ticks have succeeded in a row. The event route keeps a follower's socket open through a
    registry failure and stamps at its next successful poll. So neither an App restart nor a
    database outage stops a Run that is being followed.
  - A Run registered by a Client from before P2 has no starts and is never orphaned.
  - With `orphan_grace_s` set to 0 the rule is off, as the reaper is, and an attached Run is given
    the default deadline (R11), so that it still ends.
- **R11 Deadline.** The driver's tick (`run_driver_tick_s`, 15 s) stops, as `deadline`, every Run
  whose `deadline_at` has passed. The same tick settles `stopped` any `pending` Candidate that has
  no start: one registered by a Client from before P2.
- **R12 State.** P1 R5 with two changes: a `pending` Candidate always counts as live, and the
  `canceled` fact is `stopped_by == "canceled"`, not the cancel flag. `run_pending_grace_s` and its
  validator are removed. The migration sets `stopped_by = "canceled"` on every Run P1 canceled, and
  a Run whose flag is set with no reason reads `canceled` too: an App from before P2 may cancel
  while a deploy rolls, after the migration ran.
- **R13 Retention.** P1's 30-day sweep first lists the Runs it is about to delete, deletes the
  objects each Run names, its context, each Candidate's result by the checksum in its record and
  each started Candidate's empty-result probe (R5), and
  only then deletes the rows of the Runs whose objects it deleted. A Run whose delete failed keeps
  its rows for the next sweep. Objects no record names (a second execution of one start, a lost
  outcome) are removed by age: on S3 by a lifecycle rule on the bucket one day longer than the
  retention (31 days), and in a folder by the adapter's `delete_older_than`, which the sweep calls.
- **R14 Local mode.** The same driver runs over the in-process runner, which has no per-caller cap
  and gives no retry delay; the driver uses a fixed backoff. That runner refuses a topic while its
  task is running, which the driver reads as "started". There is no owner email; the driver sends no
  identity, and no worker claims a topic. After a local restart, Candidates that were running read
  `lost` (P1 R6) and the driver starts the `pending` ones, so a detached local Run resumes on its
  own until its deadline. The reaper skips the topics of a Run that has starts, whoever attaches to
  them.
- **R15 Deploying.** No Run has starts until a P2 Client exists, so the Engine PR's own deploy has
  no driver-started runs in flight, and no App pod from before P2 receives a record. For later
  upgrades of this path, the runner pool should roll before the App. That is best-effort: one Helm
  release rolls both, and nothing orders them. A record only gains fields, and an
  App ignores fields it does not know. A driver-started start is a version 3 message, which an older
  worker refuses without running it (§2): with the pool behind, those Candidates fail at once with
  `unsupported_spec_version` and spend nothing.

### 4.6 Client API

```python
run = sf.evaluate(candidates, benchmark=..., detach=True, deadline=timedelta(hours=48))  # -> Run
report = sf.evaluate(candidates, benchmark=...)   # -> Report, attached, as today
run = sf.runs.get(run_id)                          # any machine
run.progress()         # Candidates done / total, spend so far
report = run.wait()    # follow until the Run ends, then its Report
report = run.report()  # local store first, else the Engine's context, records and results
run.cancel()
```

- `deadline` without `detach=True` raises.
- The transport port is "follow a Run". `run_transport` on `Client` and `AsyncClient` takes a
  transport of that shape; the per-Candidate `run()` port is removed.
- Removed from the Client: the in-flight pool sized from `GET /v1/limits` (`_engine/limits.py`,
  #1745), since the driver fills the same cap, the 900 s admission loop and its
  `waiting_for_capacity` and `admitted` notices, the per-Candidate token, WebSocket and start (with
  its 428 resend, replay acknowledgement and start refusals), gap replay requests, the cancel sweep,
  the `X-SF-Run` headers and the unbound path.
- The context is fetched from the context route and checked against the Run's checksum. A saved
  result is fetched again from the result route and checked against the record's checksum. The local
  manifest keeps the Run id and index. Manifests saved before P2 keep their artifact ticket.
- `on_event` and the progress table are fed from the Run's event stream. A Candidate waiting for a
  slot shows as queued, from `candidate.state`.
- One follower per Run resolves each Candidate's outcome; there is no thread per Candidate.

## 5. Landings

Four PRs, each with atomic commits. Each is a sub-issue under `OME-1837`.

1. **Docs.** This spec and its plan.
2. **Engine.** Storage and registry; the record on the outcome and the run-results store; the driver
   and the stop rules; the routes; removal of the P1 start binding. Deploying it changes nothing for
   running evaluations (R15).
3. **Client.** Following a Run; `detach`, `deadline`, `Run.wait()`, `Run.report()`; removal of the
   Client's fan-out from `Url4CloudTransport`. Merges after the Engine PR is deployed.
4. **Client port.** Removal of the per-Candidate `run()` port and the runner's pool, which after the
   Client PR only test fakes reach; those fakes move to the follow-a-Run port. It changes nothing a
   user of `evaluate` can observe, and merges before the next Client release, so `run_transport`
   changes shape once.

Between the Engine and Client PRs, a Client built from `main` gets a 422 on `POST /runs`, shows
P1's one notice and runs with no Run record, as a released Client does.

## 6. Tests (written first)

- **Driver:** starts every Candidate with at most the per-caller cap in flight; retries at-capacity;
  a queue or registry outage is retried, not failed; any other refusal settles `failed` and the
  Run's other Candidates still start; a Candidate that waited for a slot
  keeps its full 16 h and is never reconciled `lost`; a Candidate keeps one topic through every
  retry and restart.
- **Repeats:** a repeated start is skipped by the worker that is running it, by any worker while its
  claim's holder answers, and by any worker once the run has a terminal frame or its claim is marked
  finished; of two workers that take two copies, together or apart, one runs and the other acks its
  copy away; a claim whose holder is gone is taken over by exactly one of two contenders; a
  contender never answers for a topic it does not hold; a run whose holder has just finished is not
  run again; a duplicate copy of a live run that is expired, or from another world config, publishes
  no terminal frame; a worker that cannot reach the claims bucket, or that runs out of its budget,
  runs; a worker that knows versions 1 and 2 refuses a driver-started start; a second outcome for a
  topic changes no state.
- **Lease:** two drivers never drive one Run; an expired lease is taken over; a driver that lost its
  lease stops.
- **Reaper:** a driver-started topic with no WebSocket is not reaped; a raw url4 topic still is.
- **Record:** the runner's record equals what the Client's fold gives for the same run, on recorded
  runs for success, failure, a cache-hit run, a capture run and a large result; state, cost and
  record are written together or not at all; a redelivered outcome writes nothing more; a Candidate
  with no runner report settles with no record and the Run still ends; a Candidate whose run ended
  but whose outcome never arrived settles from its terminal frame, and the runner's outcome arriving
  after that fills the cost and the record; a record with a 100 KiB error text is cut and its
  outcome still lands.
- **Results:** a small and a large result are each written by the runner under their checksum and
  read from the route by a second client, streamed; a second execution does not overwrite the first;
  the same bytes in two Runs are two objects; retention deletes a Run's context and recorded results
  and keeps the rows of a Run whose delete failed, and the folder adapter removes by age what no
  record names; a store that fails briefly at the end of a run is retried and the run succeeds; the
  route serves only the key built from the Run, index and checksum; a pool with no run-results store
  fails the run `result_store_missing` before any model call.
- **Stops:** a stop that fails is made again on the next tick; a start that loses to a stop does not
  run; a queued start is cancelled in the queue; a stopped Run with a bound, unscheduled Candidate
  still ends, hosted and local; an orphaned or deadline-stopped Run reads `interrupted`.
- **Attached:** no follower for 120 s stops the Run with `stopped_by: "orphaned"`; a follower
  returning within the grace keeps it, as does one that returns between the tick's read and its
  stop; a Run never followed is stopped 120 s after it was created; a followed Run survives an App
  restart and a registry outage longer than the grace; a Run with no starts is never orphaned; with
  the rule off, an attached Run stops at the default deadline.
- **Detached:** runs with no follower; stops at `deadline_at` with `stopped_by: "deadline"`; a
  deadline over the cap is 422; following it and leaving does not stop it.
- **Context:** it is served to the owner only, byte for byte as sent, and its checksum is on the
  Run; over the cap is 422; a Run is not registered when its context cannot be stored; a context
  written for a repeated `client_key` is deleted; retention deletes it with the Run; no `/runs`
  answer carries `owner_email`; a stated `X-Profile` is 400 and keeps neither a Run nor a context.
- **Migration:** a Run P1 canceled still reads `canceled`; the tick settles a pre-P2 `pending`
  Candidate.
- **Events:** a silent Run sends heartbeats; a late follower gets a running Candidate's events and
  an ended Candidate's record; `run.ended` comes last; a registry failure does not close the stream.
- **Client:** `detach=True` returns at once; `Run.wait()` and `Run.report()` on a second machine
  return a `Report` equal field by field to an attached run's, with an empty local store; Ctrl-C
  cancels an attached Run; `deadline` without `detach` raises; an older Engine's code-less 422 or
  404 raises with the upgrade message, and an Engine with Runs off raises the Runs-off message; a
  follow that outlives the login ends with the D15 message; a follower that reconnects delivers no
  event twice; a context that does not match the Run's checksum is refused; a saved result is
  re-fetched from the result route.

## 7. Out of scope

- The spend cap (P4, `OME-695`) and the credit balance (P3).
- Notifications when a Run ends (`OME-1690`).
- Keeping a Candidate's past progress lines after it ends.
- Rebuilding a replay's reproduction details on another machine. A raw url4 or replay Run has no
  benchmark context; its Report is rebuilt from its record and result alone.
- `OME-1867` and `OME-1868` on the raw start path. D6 and D7 close both for driver-started runs
  only.
- Holding waiting Candidates in the queue. The queue refuses at its per-caller cap (§2); holding
  them there needs per-caller counting shared across runner pods and a second mechanism for local
  mode.

## 8. Risks

- **The Runs database is on every evaluation's path (D2).** An outage stops new evaluations.
  Accepted: P1 already fails fast at start. An attached evaluation whose follower has to reconnect
  during an outage longer than its 120 s budget ends in the Client, and its Run is stopped as
  orphaned once the registry is back (R10).
- **A Candidate can run twice (R3).** Rare, and it costs that Candidate's model calls twice. The
  worker already accepts this for redeliveries. A second message per topic also widens an existing
  exposure: a copy left unacked twice ends the live run as `failed / max_deliveries` (§2).
- **A record is lost with its outcome (R6, R7):** the child's report is unreadable, or the worker
  dies or drains before the publish lands. The Candidate still settles from its terminal frame, and
  the Client reads its result as lost.
- **The runner gains write access to a bucket whose objects live 30 days.** Its key is write-only:
  reads and deletes stay with the App. A write key can still overwrite an object, so results are
  keyed by checksum and the context's checksum is kept on the Run (D9a, D9b). On the bundled Garage
  a write key can also delete.
- **A registry outage leaves contexts behind.** When registering fails and the App cannot ask
  whether the Run exists, it keeps the context it wrote, since a Run whose answer was lost names it.
  A client retrying through the outage leaves one per attempt; the bucket's 31-day rule removes
  them (R13). The bundled Garage has no such rule.
- **A runner pool roll can interrupt the Candidates in flight.** A draining worker takes no new
  run and keeps its children running for `drainGraceS`, then stops the rest, each `stopped /
  worker_draining`; one topic for life (D6) means it is not started again, and the Run reads
  `interrupted`. With autoscaling on (#1738) the chart refuses a grace shorter than the 16 h job
  deadline, so a scale-down lets every run finish. With it off the grace is 30 s, so a deploy
  interrupts them; prod sets it to cover the job deadline (§9), and a deploy then keeps the old pods
  until their runs end. A node lost, or an eviction past the grace, still interrupts them.
  Restarting such Candidates is a follow-up.
- **The runner pool must roll before the App (R15).** With the order wrong, driver-started
  Candidates fail at once with `unsupported_spec_version` until the pool catches up. Nothing in the
  chart orders the two.
- **A result is lost when the store fails as its run ends.** The store is checked before any model
  call (R5), but a store that then stays down past the 60 s write budget at the run's end loses that
  Candidate's result after its spend: it ends `result_store_unavailable`. Accepted (§10): prod's
  bucket is a durable one (§9), and a longer budget only holds a runner slot longer.
- **Run rows are no longer small.** A Run keeps its starts in Postgres for 30 days: at most
  `run_request_max_bytes` (8 MiB) a Run, and a url4 at most 512 KiB, so the shared 4 GiB volume
  holds 512 Runs of the largest size. A typical start is a few KiB; the context is kept in the
  run-results store, not in Postgres.
- **The claims bucket is the Engine's first use of NATS key-value.** Its contract is tested against
  a real broker before any worker code depends on it.
- **Every result, and every new Run's context, depends on the run-results bucket.** The bundled
  Garage is one replica with no backup (`deploy/helm/values.yaml`: "not a durability tier"). A
  durable bucket in prod is a precondition for shipping (§9).
- **Two Runs by one owner share the queue's 24.** The second Run's Candidates wait until slots
  free. After an App restart the queue's caller counters start empty, so the cap is
  briefly not enforced. The count is kept per App pod, so it must be shared before the App scales
  out.
- **An attached Run can start spending before its first follower arrives.** Today's 428 check
  prevents that. The Client follows right after `POST /runs`, and R10 stops the Run after 120 s if
  it never does.
- **A detached Run spends until its deadline** if its owner forgets it. Bounded by 16 h per
  Candidate, the per-caller cap in flight and the deadline; the money guard is P4.

## 9. Owner actions

- Provide a durable run-results bucket in prod before the Client PR is released, and decide what
  backs it. Azure Blob does not speak the S3 API, so a managed bucket there needs its own adapter.
- Create that bucket and its lifecycle rule, one day longer than the Run retention (31 days), on
  staging and prod, with a write-only key for the runner pool. With the bundled Garage this is a
  third instance, as the blob store has its own, since one instance creates one bucket.
- Admit the App and the runner pool to the run-results store in the platform's NetworkPolicy (the
  bundled Garage's pods, `app.kubernetes.io/component: garage-run-results`, on port 3900, or the
  bucket's endpoint). The chart renders no policy; without the rule every driver-started run fails
  `result_store_unavailable` before it spends, and `POST /runs` with a context answers 503.
- Set the runner pool's `drainGraceS`, with its `terminationGracePeriodSeconds`, to cover the
  16 h job deadline in prod, so a deploy lets the Candidates in flight finish, as autoscaling
  already requires (§8). Size the namespace quota for the old pods a deploy keeps.
- Confirm on staging that the edge passes `X-User-Email` on a WebSocket upgrade to
  `/runs/{id}/events`.
- Confirm that the broker's JetStream file store holds the outcome stream's 512 MiB (§4.4) beside
  `events.maxBytes`, on staging and prod, before the Engine PR deploys.

## 10. Owner decisions

All by Tauquir (spec owner), approved 2026-11-11 to 2026-11-13.

- The Engine drives the fan-out for every `evaluate`, and Runs are required (D1, D2).
- The driver is an App task on a Postgres lease, and the queue does not hold waiting Candidates (D3,
  D4, §7). P2 adds nothing to a pod's memory that another pod would need (D5).
- A Candidate has one topic for life, a start is safe to repeat, and a worker claims a topic
  atomically before running it (D6, D7).
- The Engine keeps owner emails and start bodies in Postgres and the Client's context in the
  run-results store, and returns the starts and the context to the owner (D8, D9b).
- The runner produces the record and writes every result itself. The record lives in Postgres and
  results in an object store; event frames are not stored (D9, D9a).
- Retention deletes the objects a Run names, and a lifecycle rule removes the rest, so the S3
  adapter never lists the bucket (R13).
- P1's condition for a stateful App, that runners stay stateless, still holds: a runner keeps no
  database and nothing between runs; its one new access is a write-only key to the run-results
  bucket.
- A result whose store fails past the write budget as its run ends is lost (§8).
- A runner pool roll lets the Candidates in flight finish: the drain grace covers the job deadline
  (§8, §9). Restarting a Candidate that is still interrupted is a follow-up.
- What stops a Run: attached by the 120 s rule, detached by a 48 h deadline settable up to 7 days;
  no conversion between the two (D10 to D12).
- The Client follows one event stream per Run; `detach=True` returns a `Run` and the default a
  `Report`; a follow that outlives the login ends with a message; a released Client keeps working,
  and a P2 Client on an older Engine raises (D13 to D16).
- Four PRs with atomic commits (§5). Rewriting the P1 tests that P2's removals break is approved.
