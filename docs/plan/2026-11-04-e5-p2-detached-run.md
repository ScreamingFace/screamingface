# E5 P2 plan: a detached Run

Status: APPROVED by the owner 2026-11-11.

Spec (approved 2026-11-11): `docs/spec/2026-11-04-e5-p2-detached-run.md`. Issue `OME-1837`,
under epic `OME-1294`.

## Shape

Three code PRs after this docs PR, each with atomic commits: **Engine** (E1–E5), **Client**
(C1–C2) and **Client port** (CP1).

- **Each commit passes its own tests.** E1 changes how a Run's state is derived and adds storage
  nothing reaches yet. E2 extends what a runner reports; nothing asks for it yet. E3 wires the
  driver. E4 opens the routes. E5 removes the P1 start binding.
- **Order.** The Engine PR merges and deploys first. The Client PR branches from `origin/main` and
  merges after. Between the two, a Client built from `main` gets a 422 on `POST /runs`, shows P1's
  one notice and runs with no Run record (spec §5).
- **Linear:** each PR gets its own sub-issue under `OME-1837`, filed when that PR opens, with the
  owner's confirmation.
- **Per PR:** its own worktree and ledger in `docs/work/`, RED first, targeted tests locally, the
  gates in CI, a self-review, the ledger's outcome filled before the PR opens. Tortoise work follows
  the `tortoise-dev` skill (built-in migrations, never Aerich).

## Engine PR: `screamingface-engine`

Paths are under `apps/screamingface-engine/src/screamingface_engine/`. Tests are under
`apps/screamingface-engine/tests/unit/`.

### E1. Storage and registry

Changes state derivation (spec R12); the rest is not reachable yet.

- `runs/migrations/0003_detached_run.py`:
  - Run: `detached`, `deadline_at`, `stopped_by`, `owner_email`, `driver_lease_until`,
    `last_followed_at`, `context_sha256`, `context_bytes`.
  - Candidate: `start` (JSON), `record` (JSON), `trace_id`.
  - `stopped_by = "canceled"` on every Run whose P1 cancel flag is set (spec R12).
  - New non-null columns carry a `db_default`, as 0002's did: the migrate Job runs while the P1 App
    still serves.
- `runs/models/`: the new fields.
- `runs/records.py`: `CandidateStart(name, url4, answer_seed, capture, use_cache,
  replay_frozen_copy)`; `RunSpec` carries the Run id, starts, `detach` and `deadline`, and still
  accepts names alone until E5; `RunRecord` gains `detached`, `deadline_at`, `stopped_by` and the
  context's checksum and size; `CandidateRecord` gains `start` and `record`.
- `runs/registry.py` and `runs/store.py`. Every method runs under `@_in_context`, and every write is
  guarded on the state it expects inside one transaction, as `settle` is (`store.py:273`).
  - New: `lease_run`, `release_run`, `due_runs` (with each Run's owed topics), `pending_starts`,
    `overdue`, `expiring`, `settle_startless` (spec R11) and `summary`, which is `get` without
    `start` and `record`.
  - New: `followed(run_id, at)`, which never moves the stamp back, as `_touch` does not
    (`store.py:340`), and `stop(run_id, reason, unless_followed_since=None)` (spec R9). An orphan
    stop passes its cutoff and does nothing when the Run was followed after it (spec R10).
  - `expire` takes the Run ids to delete (spec R13).
  - `register` takes the owner's email, the Run id the route minted and the context's checksum and
    size (E4 stores the context under that id first). Its `client_key` check also compares the
    starts, `detach` and the deadline. With `orphan_grace_s` at 0 it gives an attached Run the
    default deadline (spec R10).
  - `cancel` calls `stop`. `bind` refuses a Run that has a stop reason; `mark_scheduled` on one
    marks the Candidate and returns False.
  - `mark_scheduled` stamps the bind time; `bind` does not. `reconcile` skips `pending` Candidates
    (spec R8).
  - `list`, `_records`, `summary` and the internal reads defer `start` and `record`; only `get`
    loads them.
- `runs/state.py`: a `pending` Candidate is always live. The store passes `stopped_by == "canceled"`
  as the `canceled` fact, not the flag.
- `runs/wiring.py`: stop passing `pending_grace` (`:145`).
- `config.py`: remove `run_pending_grace_s`, its validator and `CLIENT_ADMISSION_BUDGET_S`; add
  `run_driver_lease_s` (60), `run_driver_tick_s` (15),
  `run_outcome_grace_s` (120), `run_result_write_budget_s` (60), `run_events_poll_s` (1),
  `run_follow_stamp_s` (30; a shorter non-zero `orphan_grace_s` lowers it to half that grace, as
  `Settings.follow_stamp_s`), `run_context_max_bytes` (4 MiB), `run_request_max_bytes` (8 MiB),
  `run_detached_deadline_s` (48 h), `run_detached_deadline_max_s` (7 d).

Tests, on SQLite and Postgres through `run_registry_support.py`:
- The lease: one of two drivers takes it; an expired lease is taken; a stale holder's renewal fails.
- `due_runs` returns live Runs with a free lease, Runs past `deadline_at`, and stopped Runs with
  stops still owed.
- `followed` stamps the Run. `due_runs` returns an attached Run with starts whose stamp, or creation
  when it has none, is older than the grace; never a detached Run or one without starts; none at all
  with the grace at 0, when an attached Run is registered with the default deadline. A later
  `followed` with an earlier time changes nothing. An orphan `stop` does nothing when the Run was
  followed after its cutoff.
- `settle_startless` settles `pending` Candidates that have no start, and no others.
- `stop`: the first reason wins; a `pending` Candidate without a topic settles `stopped`; one with a
  topic becomes `scheduled` and is owed a stop; a later `bind` is refused; `orphaned` and `deadline`
  read `interrupted`; on a Run with no live Candidate it changes nothing.
- A Candidate that waited `pending` past `run_lost_after_s` is not reconciled `lost`; one scheduled
  that long ago is.
- A list or summary read does not select the JSON columns.
- `expiring` lists the Runs; `expire` deletes only the ids it is given.
- After the migration, a Run P1 canceled still reads `canceled`.
- The migration autodetector proposes no change (`test_run_migrations.py`).

### E2. The record on the outcome, and the run-results store

Nothing asks a runner for a record yet. The new message fields are written only when set, so a
start without them is today's path, byte for byte.

- `candidate_outcomes.py`: `CandidateOutcome` gains `record`; the codec carries it within the
  existing 64 KiB limit. `candidate_outcomes_max_bytes` rises to 512 MiB in `config.py` and in the
  chart, which sets the deployed value (`candidateOutcomes.maxBytes`, `deploy/helm/values.yaml:211`,
  with its schema text and README); the broker's JetStream file store must hold it (Owner actions).
- New `candidate_record.py`, a shared leaf beside `run_evidence.py`: builds the record of spec §4.3
  by the Client fold's rules (`contract.py:197-331`, `:408-467`) and applies its size rule: it cuts
  the error text and capture reasons to keep the encoded record under 48 KiB, measured with
  non-ASCII escaped as the codecs write it, and returns none if it is still larger. It folds the
  frames the run published, the closing summary log among them, so it needs nothing from
  `runner/summary.py`. `run_evidence.py`: `SettlementWatch` feeds it the frames the stream accepted,
  for a run with a result prefix only.
- New `artifacts/run_results.py`: the `RunResultStore` port. Adapters: S3 on its own bucket (`put`
  as one PUT with the known length and sha256, retried with backoff within
  `run_result_write_budget_s`; a streaming `open`; `delete` of the keys a Run names), and a
  filesystem folder under the Engine data dir. The S3 adapter never lists the bucket, so
  `artifacts/sigv4.py` keeps its one-object bound; the S3 store's response helpers move to
  `artifacts/s3_responses.py` so `artifacts/s3.py` stays under 450 lines. `artifacts/wiring.py`: a
  from-env builder for the runner, which cannot reach `adapters/factory.py` or `config.py`;
  `adapters/factory.py`: `build_run_result_store` for the App.
- `job_env.py`: the keys for the result prefix, the `exclusive` flag and the run-results store. A
  message that carries them is version 3: `SUPPORTED_SPEC_MAJORS` gains 3, and
  `CURRENT_SPEC_VERSION` stays 2 for every other message. `ports.py`, `adapters/queue_runner.py`,
  `adapters/inprocess.py`, `runner_queue.py`: `schedule(..., result_prefix=None, exclusive=False)`,
  carried in the queue message.
- The runner (`runner/main.py`, `runner/executor.py`): with a result prefix, the result is written
  to `{prefix}/{sha256}` in the run-results store before the result frame is published, and the
  child reports the record with its outcome. A write that still fails after its retries ends the run
  `failed` with `result_store_unavailable`, not permanent. A run that carries a result prefix on a
  pool with no run-results store fails `result_store_missing`, before any model call.
- New `topic_claims.py`, the `TopicClaims` port (`claim`, `take_over`, `finish`), and
  `adapters/topic_claims_jetstream.py`: a key-value bucket `url4-claims`, keyed by the topic's
  sha256 so any topic is a valid key.
  - Its age limit is `events_max_age_s`, and its replicas and storage are the event stream's.
  - It is declared at startup by look-then-reconcile, as the Engine's streams are
    (`adapters/jetstream.py:179`). nats-py's `create_key_value` adds the stream without looking, so
    the adapter does not use it.
  - A failed create does not name the holder, so `claim` reads the entry after it and treats a
    missing key as "try again".
  - Its contract test against a real broker is the first thing written in E2. It declares the bucket
    twice and runs in the `EventStream conformance (real NATS)` CI job.
- `child_protocol.py`: `Settled` carries the record, written only when set.
- `worker/supervisor.py` and `worker/loop.py`:
  - `_child_outcome` (`:1331`) passes the record on.
  - With `exclusive`, the claim step of spec R3 runs after the terminal-frame and same-pod gates,
    takes the place of `_refuse_cross_pod_duplicate` (`:637`) and comes before the expiry, version
    and world refusals (`:547-561`). Its total budget is `topic_claim_budget_s` (5 s, well inside
    the queue's 60 s `ack_wait`); past it, or with the bucket unreachable, the worker runs. A copy
    is always acked away, never nak'd (`max_deliver` is 2, `:644`).
  - The worker asks a claim's holder on a subject of its own, `url4.runclaim.<topic>`, with the
    holder's id as the payload (`subjects.py:52`). A worker answers only when the id is its own and
    it holds the topic's claim, from winning it until it marks it finished, which covers the spawn
    window too. `_starting` is set when a message is pulled (`worker/loop.py:325`), so the handler
    does not answer from it. The cross-pod check on `url4.runown.<topic>` stays as it is for every
    other run. The claim step lives in a new `worker/topic_claim.py`, the retries below in a new
    `worker/outcome_retry.py`.
  - The worker calls `finish` once its run's terminal frame is published and before it acks its
    message (`:765`).
  - For a driver-started run, an outcome publish that failed for an unreachable broker or a full
    stream is retried with backoff until it lands or the worker drains (spec R6). The retry is its
    own task, started after the run's queue message is acked, and the drain awaits it.
- `adapters/inprocess.py`: `_on_done` (`:218`) reports the same record for local runs; `stop_bound`
  publishes a `stopped` outcome when it holds no task for the topic (spec R9).
- `runs/store.py` `settle`: stores the record with the state and cost; an outcome for an
  already-settled Candidate with the same state fills a cost or a record that is empty, and changes
  nothing else.
- `config.py`: the run-results store's bucket, endpoint and keys. `deploy/helm/`: values and schema;
  `templates/configmap-runner-env.yaml`; the App's Secret and an optional write-only one for the
  pool; a third bundled Garage for the bucket, as the blob store has its own; the chart fails to
  render with Runs on and no run-results store; README and `DEPLOYMENT.md`.
- The recorded runs used by the record tests live in
  `apps/screamingface-engine/tests/fixtures/candidate_runs/`. The Client's tests in C1 read the same
  files, so `.github/workflows/screamingface-tests.yml` gains that path.

Tests:
- The record equals what the Client's `_RunState` gives for the same recorded run: success, failure,
  a cache-hit run, a capture run, a large result.
- The codec round-trips an outcome with a record, and one without is unchanged.
- `settle` writes state, cost and record together; a second `settle` for the topic writes nothing;
  an outcome with no cost and no record settles with both null, and a later outcome with the same
  state fills them; one with a different state changes nothing.
- A record with a 100 KiB error text is cut to fit and its outcome is published; the SETTLED line
  stays under the control pipe's 64 KiB.
- A store that fails twice and then accepts: the run succeeds. One that keeps failing: the run ends
  `result_store_unavailable`. A pool with no run-results store: the run ends `result_store_missing`
  before any model call.
- One contract suite over both store adapters, beside `test_s3_artifact_store.py`.
- The claims contract, on the real broker and on an in-memory fake: one of two creates wins; a
  takeover with a stale revision fails; a finished entry reads as finished; an entry expires;
  declaring the bucket twice changes nothing.
- The worker, with `exclusive`:
  - of two workers that take two copies of a start, together or apart, one runs and the other acks
    its copy away;
  - a claim whose holder is gone is taken over by exactly one of two contenders, and a contender
    never answers for a topic it does not hold;
  - a copy that arrives as the holder finishes is acked away, by the finished mark or by the second
    read of the last frame;
  - a copy whose claim names this worker, with no run in flight here, runs;
  - a duplicate copy of a live run that is expired, of an unknown version or from another world
    config publishes no terminal frame;
  - with the bucket unreachable, or the budget spent, the worker runs.
- The worker, other cases: without the flag, behaviour and the message are unchanged; a worker that
  supports majors 1 and 2 refuses a version 3 message; a failed outcome publish is retried and ends
  on drain.
- A start without the new fields produces today's message, outcome and artifact write.
- The chart renders the store settings on the App and the runner pool, and fails without them.

### E3. The driver and what stops a Run

From this commit the Engine starts Candidates itself.

- New `scheduling.py`, added to `CONTROL_PLANE` in `.claude/scripts/check_layering.py`: the
  Request-free core of what the start route does for a run, model admission as the caller (`:322`)
  and the schedule call (`:353`); the runner's errors propagate. The selector refusal and the cache
  policy's convergence read the request's headers, so they stay in the route; for the driver the
  cache policy comes from the start's `use_cache`. The route maps the errors to the same Problems,
  keeps its "run scheduled" log line and keeps `_named_dynamic_models` importable, so no start test
  is edited.
- New `stopping.py` (control plane): the core of `rest/stopping.py::stop_topic`, raising
  `QueueReadError`; `rest/stopping.py` maps it to the 503 Problem.
- New `runs/driver.py`:
  - `RunDriver.drive(run_id)`: spec R1 and R2. Bind to schedule runs inside
    `job_runner.start_attempt(topic)`. A Candidate keeps its topic and trace through every retry.
    `JobAlreadyExists` from the in-process runner counts as started. A permanent refusal settles the
    Candidate `failed` with its code, through the registry; `StoppedBeforeSchedule` is not one and
    is left to the stop. The driver renews its lease on each pass.
  - `RunDrivers`: takes the leases of `due_runs` at start and every `run_driver_tick_s`. Each tick
    it stops Runs past their deadline and attached Runs nobody follows (R10, R11), settles startless
    `pending` Candidates (R11), makes owed stops again (R9), and settles overdue Candidates from
    `job_runner.last_frame`: a terminal frame older than `run_outcome_grace_s` settles the
    Candidate, through the registry, with its state and error code (R7). It makes no orphan stop
    until `orphan_grace_s` of ticks have succeeded in a row since it started or since a tick last
    failed (R10). It releases its leases at shutdown. `POST /runs` wakes it so a new Run starts at
    once.
- `reaper.py`: skips a topic bound to a Run that has starts (spec R14).
- `ports.py`, `adapters/queue_runner.py`, `adapters/inprocess.py`: `last_frame(topic)`, the topic's
  newest frame, beside `status` (`adapters/queue_runner.py:632`), which R7 settles a Candidate from.
- New `runs/stopping.py`: `make_stops(topics)` makes owed stops through `stopping.py` and
  `stop_done`, and returns what failed. `DELETE /runs/{id}` uses it in place of its own copy
  (`rest/runs.py:156`) and keeps its recheck and 503; the tick uses it after `registry.stop`.
- `runs/wiring.py`: `install_runs` starts the drivers after the first sweep and stops them before
  the writer. Its new parameters (the job runner, the event stream, the run-results store) are
  keyword-only and default to "no driver", so its existing callers and tests are unchanged.
  `runs/sweeps.py`: for each Run `expiring` lists, delete its context and each Candidate's result by
  its record's checksum, then call `expire` with the ids whose delete succeeded; then
  `delete_older_than` the retention plus one day, which only the folder adapter acts on (spec R13).
- `local.py` and `app.py`: pass those three to `install_runs`.

Tests, on `_fakes.RecordingJobRunner`, `InMemoryCandidateOutcomeStream` and the fake `Clock`.
The restart and repeated-start tests are written before any driver code.
- The spec §6 Driver, Repeats, Lease, Reaper, Stops, Attached and Detached rows.
- An App restart: `install_runs` twice over one database resumes the Run with the same topics.
- A Run with no starts (registered P1's way) is not driven and never orphaned, and its `pending`
  Candidates settle on the tick.
- No orphan stop is made within the grace after the driver starts or after a failed tick.
- A raw WebSocket that attaches to a driver-started topic and leaves does not get it reaped.
- A Candidate whose run ended with no outcome settles from its terminal frame, with its error code,
  and frees its slot; one whose terminal frame is younger than the grace is left alone.
- A sweep whose delete fails for one Run keeps that Run's rows and deletes the others.
- The layering gate passes with the two new control-plane modules.

### E4. Routes

- `rest/runs.py`, `rest/runs_boundary.py`, and new `rest/runs_wire.py` (the wire models) and
  `rest/capped_body.py` (the body cap, shared with the blob upload):
  - `POST /runs` with starts, the context, `detach` and `deadline_s`; a `code` on every 422 and on
    the Runs-off 404; the body cap. The route mints the Run id, streams the context to
    `runs/{run_id}/context` while computing its checksum and size, and then registers the Run with
    them. A store that refuses answers 503 `result_store_unavailable` and registers nothing. A
    context written for a Run that was not registered (a failed register, a repeated `client_key`)
    is deleted. A stated `X-Profile` answers 400 `x_profile_unsupported` before the body is read,
    as on the start route.
  - The starts, the records and the context's checksum on `GET /runs/{id}` only, and `?view=summary`
    without them.
  - `GET /runs/{id}/context` and `GET /runs/{id}/candidates/{index}/result`, in new
    `rest/runs_objects.py`, both streamed from the store through `rest/artifacts.py`'s
    `content_response`; the result's key is built from the Run id, the index and the record's
    checksum, read through the registry's new `records`.
- New `rest/runs_events.py`: the WebSocket, on its own router with its own Runs-off and owner
  checks, since `RunsRoute` covers HTTP routes only (`rest/runs_boundary.py:79`). It polls the
  registry's `summary` and reads each live Candidate's event stream itself, forwards a Candidate's
  events up to its terminal frame before `candidate.settled`, sends every frame of spec §4.2,
  heartbeat included, and stamps the Run through `registry.followed` when a follower connects, every
  `run_follow_stamp_s` and when it leaves. A registry failure does not close the socket; the route
  polls again and stamps at its next success.
- `README.md` (`## Runs — /runs`), `CHANGELOG.md`, `DEPLOYMENT.md`.

Tests, on the `_Engine` harness in `test_runs_routes.py`:
- The spec §6 Events, Context and Results rows and each new answer of §4.1.
- A foreign owner gets 404 on every new route and a close on the WebSocket; no answer carries
  `owner_email`.
- A silent Run gets heartbeats; `running` is sent at a Candidate's first event.

### E5. Retire the P1 start binding

- Remove `rest/runs_start.py`, its call sites in `rest/routes.py` (`:301`, and in `start_run`),
  the bind moment it gave the queue (`enqueued_at` on `scheduling.schedule_run`) and the
  names-only `POST /runs` body. The start route still answers a topic stopped before its schedule
  `409 run_canceled`.
- No test file is deleted or renamed: the append-only gate has no approval for that
  (`.claude/scripts/run_gates.py:392`). A file whose tests all go is rewritten onto P2.

Tests: a start with `X-SF-Run` headers runs as a plain start; a names-only body is 422.

## Client PR: `screamingface`

Paths are under `packages/screamingface/src/screamingface/`. Tests are under
`packages/screamingface/tests/`.

### C1. Follow a Run

- `_engine/runs.py`: `RunRequest` carries starts, `detach`, `deadline_s` and one `context` (the
  benchmark info, the selected Cases and, per Candidate, `_results/codec.py::candidate_data` without
  its url4 and seed); `create_*` raises instead of returning `Unavailable`; an older Engine's
  code-less 422 or 404 raises `EngineCapabilityError` with the upgrade to make, and 404 `runs_off`
  says Runs are off; the context and result fetches, each checked against its checksum.
- New `_engine/run_follow.py`, sync and async: one WebSocket per Run; frames routed by index;
  reconnect inside the Engine's 120 s grace; the D15 message when the login has expired.
- `_engine/transport.py`: `Url4CloudTransport` gains `follow_run(...)`, which registers the Run,
  follows it and yields each Candidate's `_RunOutcome`, built from the Engine's record and result.
  Removed from it: the per-Candidate token, WebSocket and start, the admission loop, the cancel
  sweep (`DELETE /runs/{id}` only).
- `_core/ports.py` and `_evaluation/runner.py`: the runner uses `follow_run` when the transport has
  it, with one follower and no pool. A transport that has `run()` alone, which is every test fake,
  keeps the pool path until the Client port PR removes it, so this PR's diff holds the feature only.
- `_engine/result_download.py` and `_results/codec.py`: a saved result is re-fetched from the result
  route and checked against the record's checksum; the manifest stores the Run id and index; a
  manifest from before P2 keeps its artifact ticket and path.
- `_engine/contract.py`: `_RunState` decodes events for display only. Building the outcome, gap
  checks and replay requests are removed.
- Remove `_engine/admission.py` and `_engine/run_binding.py`.
- `_evaluation/url4.py` and `_replay.py` use the same path with one Candidate.

Tests, on `tests/_isolation_engine.py` extended to serve the Run event stream:
- The recorded runs from E2 give the same `_RunOutcome` through the Engine's record.
- A Candidate waiting for a slot shows as queued.
- 256 Candidates are followed without a thread each.
- On the follow path: results come back in declared order; a Candidate that settles first completes
  first; a failed Candidate's row shows while its sibling runs; an owner abort sends one `DELETE
  /runs/{id}` and the siblings read `stopped`.
- A saved large result is re-fetched from the result route; a pre-P2 manifest still redeems its
  ticket.
- `on_event` and the progress table get every event, in order, per Candidate.
- Ctrl-C sends one `DELETE /runs/{id}`.
- An older Engine's code-less 422 or 404 raises with the upgrade message; an Engine with Runs off
  raises the Runs-off message.
- A follow that outlives the login ends with the D15 message.
- A follower that reconnects delivers no event twice.
- A context that does not match the Run's checksum is refused.

### C2. Detach, reattach, report anywhere

- `client.py` and `_default_client.py`: `evaluate(..., detach=False, deadline=None)`.
- `runs.py`: `Run.progress()` and `Run.refresh()` read `?view=summary`; `Run.wait()` follows and
  returns the `Report`; `Run.report()` reads the local store, else builds the Report from the
  Engine's context, records and results and saves it.
- README "Your runs", `CHANGELOG.md`, `tests/public_surface_snapshot.json`; notebooks are
  regenerated only if their output changes.

Tests: the spec §6 Client rows.

## Client port PR: `screamingface`

Opens right after the Client PR merges and merges before the next Client release. It changes
nothing a user of `evaluate` can observe.

### CP1. One transport port

- `_core/ports.py`: `SyncRunTransport` and `AsyncRunTransport` become the follow-a-Run port
  (`follow_run`, `close`); the per-Candidate `run()` and `cancel_active` go.
- `_evaluation/runner.py`: remove `_run_candidates_sync`, `_run_candidates_async`,
  `_MAX_CANDIDATES_IN_FLIGHT`, the `load_caller_cap` loaders with `_engine/limits.py` (#1745), the
  sweep through `cancel_active` and the capability check that chose between the two paths.
- `client.py`: `run_transport` takes the follow-a-Run port. `CHANGELOG.md`: one entry for the
  parameter's new shape; `tests/public_surface_snapshot.json`.
- New `tests/_run_transport.py`: a helper that turns a scripted per-Candidate function (return an
  outcome, raise, emit events, wait for a signal) into a follow-a-Run fake that settles Candidates
  in the scripted order.

Tests:
- The 29 fakes that fail if called or return a canned outcome are rebuilt on the helper; their
  tests' assertions are unchanged.
- The 11 files that script concurrency, ordering, sibling failure and abort keep each assertion
  about what the Client shows and returns, driven by the order of settled frames. Assertions about
  threads in flight inside the Client are replaced by "the Client starts no Candidate"; the
  8-in-flight assertion lives in the Engine driver's tests (E3).

## Prior tests

No prior assertion is loosened. P2 removes behaviour that many P1 tests set up through, so
these rewrites are expected and approved by the owner. Each is listed in that PR's
`.claude/test-change-approvals/<OME-N>.json`.

No test file is deleted or renamed; a file whose tests all go is rewritten. The manifest holds
exact blob ids per branch name, so it is regenerated after the last edit and after the branch is
renamed to `OME-N-…`, and again after a merge of `main` that touches a listed file.

Engine (`tests/unit/`):
- E1: `test_run_settings.py` and `test_run_state.py` for `run_pending_grace_s`;
  `run_registry_support.py` (`pending_grace=GRACE`, imported by the lifecycle and contract suites);
  and the tests of when a Candidate's clock is stamped and when reconcile settles it:
  `test_run_registry_lifecycle.py`, `test_run_registry_contract.py`, `test_run_sweeps.py`,
  `test_run_wiring.py`. The files that build `RunSpec` from names keep working until E5.
- E2: `_fakes.py` (`RecordingJobRunner`) and `test_run_queue_codec.py`, for the two new message
  fields; the outcome codec tests (`test_candidate_outcome*.py`); the settled-line tests of
  `child_protocol.py`. Also, each confirmed with the owner: the fake `schedule` of
  `test_answer_seed_threading.py`, `test_cache_policy_threading.py`, `test_queue_admission.py` and,
  under `tests/integration/`, `test_e2e_compose_flow.py` and `test_run_control_resilience.py`, which
  gains the two new parameters; the stand-in run params of `test_runner_settlement.py` and
  `test_supervisor_terminal_root_source.py`, which gain `result_prefix`;
  `test_supervisor_launch.py`, whose unknown spec version is no longer 3; and
  `test_catalog_wiring.py`, which pins the run-results store's two credential settings.
- E4: `test_runs_routes.py` and `test_runs_local_lock_and_not_found.py` where they assert the P1
  body, the code-less 422 and the plain Runs-off 404.
- E5: every test that sets a Run up through a names-only create or an `X-SF-Run` start:
  `test_runs_routes.py`, `test_runs_cancel_*.py`, `test_runs_owed_stops_and_boundary.py`,
  `test_runs_start_never_blocks.py`, `test_runs_stop_before_enqueue.py` and
  `test_runs_local_lock_and_not_found.py`. They move onto the P2 body; a start-binding test goes
  where the driver's tests (E3) hold its P2 version. The registry suites that build `RunSpec`
  from names stay: a Run registered before P2 has no starts, and the registry still handles it.

Client (`tests/`):
- C1:
  - The fakes that implement `run()` alone are untouched in this PR.
  - The 25 files that build `Url4CloudTransport`, including those that serve `/token` and those on
    `protocol_server.py`, are rewritten onto the Run event stream; `_isolation_engine.py`,
    `_reconnect_engine.py` and `protocol_server.py` themselves are protected helpers and are listed
    too.
  - `test_admission_retry.py`, `test_run_registration.py`, `test_terminal_running_score.py` and the
    reconnect, cancel-sweep and unbound-path tests.
  - The seven files that assert `_RunState.accept(...).outcome`: `test_cache_hit_contract.py`,
    `test_cached_run_not_complete.py`, `test_candidate_root_lifecycle.py`,
    `test_capture_summary.py`, `test_engine_contract.py`, `test_report_client_provenance.py`,
    `test_span_time_tolerance.py`.
  - `test_runs_wire.py` and `test_runs_wire_state_shapes.py`, for `create_*` and `RunRequest`.
  - `test_transport_artifact_fetch.py`, the `test_recovery_*` download files and
    `test_saved_runs.py`, for the result fetch.
- C2: `public_surface_snapshot.json`; `test_runs_api.py` (`Run.wait()` returning a `Run` and taking
  `timeout=`, `results_not_local`).

Client port (`tests/`):
- CP1: the 40 files that define a fake transport with `run()`.
  - Fail-if-called guards (13): `test_logprobs_parameter_preflight.py`,
    `test_dynamic_admission_preflight.py`, `test_model_parameter_preflight.py`,
    `test_url4_replay_operator_check.py`, `test_fixed_seed_sitting_warning.py`,
    `test_logprob_source.py`, `test_provider_access_preflight.py`, `test_hosted_byom_preflight.py`,
    `test_samples_preflight.py`, `test_reducer_slot.py`, `test_consistency_rebuild.py`,
    `test_unsupported_provider_parameter_preflight.py`, `test_benchmark_extract_evaluation.py`.
  - Canned outcomes (16): `_vote_run_fixtures.py`, `test_answer_seed_report.py`,
    `test_reproduce_review.py`, `test_reproduce.py`, `test_accounting_token_unknowns.py`,
    `test_accounting_evaluation.py`, `test_inverted_grade_report.py`, `test_use_cache.py`,
    `test_cache_hit_contract.py`, `test_cached_run_not_complete.py`,
    `test_cache_saved_cost_submission.py`, `test_combine_evidence.py`,
    `test_recovery_failure_paths.py`, `test_frozen_copy_evaluate.py`, `test_capture_summary.py`,
    `test_benchmark_compilation.py`.
  - Concurrency, ordering, sibling failure and abort (11): `test_evaluation_outcome_runner.py`,
    `test_live_candidate_progress.py`, `test_draco_vertical_slice.py`,
    `test_evaluation_outcome_abort.py`, `test_client_run.py`, `test_candidate_completion.py`,
    `test_evaluation_outcome_cancelled.py`, `test_run_resume_reconnect.py`,
    `test_case_selection.py`, `test_run_registration.py`, `test_evaluation_outcome.py`.

If a prior test outside these groups needs a change, I stop and ask first.

## Owner actions

- Create the run-results bucket, its lifecycle rule (the Run retention plus one day, 31 days) and
  the runner pool's write-only key on staging and prod before the Engine PR deploys. A durable
  bucket in prod is a precondition for releasing the Client PR (spec §9).
- Confirm on staging that the edge passes `X-User-Email` on a WebSocket upgrade to
  `/runs/{id}/events`, before E4.
- Confirm that the broker's JetStream file store holds the outcome stream's 512 MiB beside
  `events.maxBytes`, before the Engine PR deploys.
- Confirm each sub-issue at its PR's open.

## Risks to watch while building

- `rest/routes.py`, `adapters/queue_runner.py`, `worker/supervisor.py` and `_engine/transport.py`
  are large. New logic goes in new modules; these files lose code or gain call sites and parameters
  only.
- E2 touches the runner and the worker. Everything it adds is switched on by a field in the start
  message, so a start without it is byte-for-byte today's path; its tests assert that.
- The topic claim (spec D7, R3), the missing-outcome tick (R7) and a stop on a bound, unscheduled
  Candidate (R9) each get their test before their code.
- `run_gates.py` runs before a push, not in the Engine's CI: run its append-only check before each
  push of a branch that edits prior tests.
- The record is built on both sides until C1 lands. The shared recorded runs keep them equal.
- Local mode: the in-process runner gives no retry delay; the driver uses a fixed backoff there.
