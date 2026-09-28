# PRD: Shared events stream

**Source:** prompt, ans:Q1, ans:Q7, ans:Q11 · **Priority:** P0 (it removes the concurrency cap that the uniform path would hit first)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned

## 1. Summary and the flows it serves

This is a component PRD. No user flow drives it alone. Every run flow writes and reads run
events: the async run, the sync run (PRD 02), the mount call (PRD 04), the cancel, and the
orphan reaper.

The change replaces "one JetStream stream per run" with one shared stream, `url4-events`.
Subject names stay the same (`url4-cloud.<topic>`). The per-run producer sequence becomes the
authoritative frame sequence.

## 2. Background and constraints

- "make this architecture uniform and reliable" `[stated prompt]`
- Scope includes the shared events stream. `[stated ans:Q1]`
- "Drain window is fine": the rollout may pause the system, and in-flight runs need not
  survive the change of layout. `[stated ans:Q7]`
- "Drop oldest frames + alert" when the store is full. `[stated ans:Q11]`
- Entities: EVENTS_STREAM, EVENT_FRAME (see `erd.md` §5, §6).

### 2.1 Current behavior

- `add_stream(name=url4-cloud_<topic>, subjects=[url4-cloud.<topic>], max_age=86400, max_bytes=50 MB, discard=OLD)`, once per topic, memoized. `[existing adapters/jetstream.py:205-219]`
- `max_bytes` is a reservation. The store size divided by 50 MB caps concurrent runs. At
  256 MiB the cap was 40 runs, and it caused an outage. `[existing adapters/jetstream.py:64-76]`
- On error 10047, `_sweep_orphans` lists every stream and deletes empty or never-started
  ones. `[existing adapters/jetstream.py:223-289]`
- The child publishes with `publish_async`, no headers. `[existing adapters/jetstream.py:498-505]`
- The consumer subscribes with `DeliverPolicy.ALL`, or `BY_START_SEQUENCE` with
  `opt_start_seq=from_sequence` to resume, and `AckPolicy.NONE`. `[existing adapters/jetstream.py:91-113, 413-437]`
- The consumer decodes with `decode(msg.data, sequence=msg.metadata.sequence.stream)`. This
  replaces the producer sequence with the stream sequence. `[existing adapters/jetstream.py:409-437; packages/url4/src/url4/streaming/codec.py:8-15]`
- The producer sequence is gap-free by assertion. `[existing packages/url4/src/url4/streaming/lifecycle.py:57-66]`
- The client treats `sequence > last + 1` as lost frames and asks for a replay. It fails with
  `event_stream_replay_exhausted` after a few tries. `[existing packages/screamingface/src/screamingface/_engine/contract.py:141-160]`
- The runner deletes its stream 60 s after the terminal frame. `[existing runner/main.py:157-198]`
- `DELETE /` deletes the stream. `[existing rest/routes.py:579 stop_run]`
- The App writes a `Terminated(stopped)` tombstone for a queued run and re-reads the tail
  first. `[existing adapters/queue_runner.py:345-415]`
- The supervisor writes terminal frames for exits it classifies (`oom_killed`, `killed`,
  `child_exited`, `spawn_failed`, `queue_expired`, `worker_draining`, `deadline_exceeded`).
  `[existing worker/supervisor.py:875-933]`

**Delta.**

1. One stream, `url4-events`, created or updated at startup of the App, the worker and the
   child. No per-topic `add_stream`. Remove the memo, the 10047 path and `_sweep_orphans`.
2. The consumer keeps the producer sequence (no override).
3. Resume uses a subject-filtered consumer from the start of the subject. It drops frames
   whose producer sequence is below `from_sequence`.
4. Writers that are not the child use `Nats-Expected-Last-Subject-Sequence`, per I-EV3 in
   `erd.md` §5.
5. Every publish sets `Nats-Msg-Id = <topic>:<seq>` and `Url4-Seq = <seq>`.
6. Reclaim is a subject purge instead of `delete_stream`, in the runner teardown and in
   `DELETE /`.
7. A new admin command deletes legacy per-topic streams after the drained rollout.
8. New metrics for store use and publish conflicts.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **EV-H1 one run, one subject.** Given the `url4-events` stream exists, when a run
  publishes Started, three Log frames, Result and Terminated, then all six frames are on
  subject `url4-cloud.<topic>` in the shared stream with sequences 1–6, and no stream named
  `url4-cloud_<topic>` exists. `[stated ans:Q1]`
- **EV-H2 client sees the same sequences.** Given the run in EV-H1, when a WebSocket client
  attaches with no `from_sequence`, then it receives sequences 1–6 in order, and the client
  gap check does not fire. `[implied — I-EV2]`
- **EV-H3 many runs interleave.** Given 50 runs publish at the same time, when a client reads
  any one topic, then it sees only that topic's frames and sequences 1..n with no gap.
  `[implied — I-EV1, I-EV2]`
- **EV-H4 reclaim.** Given a run published its terminal frame, when `stream_grace_s` (60 s)
  passes, then the runner purges the subject, and the stream holds no frame for the topic.
  `[existing runner/main.py:157-198]` → purge `[proposed]`

### 3.2 Error paths (from the answers)

- **EV-E1 store full.** Given the stream is at `max_bytes`, when a run publishes a frame,
  then the publish succeeds, JetStream drops the oldest frames in the stream, and the gauge
  `screamingface_engine_events_store_utilization_ratio` reads ≥ 0.99. `[stated ans:Q11]`
- **EV-E2 alert.** Given the use ratio is above 0.8 for 5 min, then the documented alert
  rule fires. `[stated ans:Q11]`
- **EV-E3 drained rollout.** Given the queue depth is 0 and `worker_slots_busy` is 0, when the
  operator deploys the new version and runs `screamingface-engine admin purge-legacy-streams`,
  then every stream named `url4-cloud_*` is deleted, the command prints each name, and
  `url4-events` and `url4-runq` stay. `[stated ans:Q7]`

### 3.3 Derived scenarios (risk order)

| ID | Title | Tag | I×L |
|---|---|---|---|
| EV-D1 | Resume from the middle | [implied — I-EV2] | H×H |
| EV-D2 | Supervisor frame after child exit gets the next sequence | [implied — I-EV3] | H×H |
| EV-D3 | Late child frame races the supervisor frame | [proposed — gap §per-connection/async] | H×M |
| EV-D4 | Tombstone on an empty subject | [implied — I-EV3] | H×M |
| EV-D5 | Publish retry does not duplicate a frame | [proposed — gap §per-connection/async] | M×M |
| EV-D6 | Per-subject frame cap drops the oldest frames of that run only | [proposed — gap §per-element/store] | M×M |
| EV-D7 | Startup with an existing stream and changed mutable config | [proposed — gap §per-connection/data] | M×M |
| EV-D8 | Startup with an immutable mismatch | [proposed — gap §per-connection/data] | M×L |
| EV-D9 | Stream larger than the JetStream store | [proposed — gap §per-element/store] | M×L |
| EV-D10 | Resume from a sequence above the last frame | [existing tests/integration/test_attach_from_sequence_bounds.py] | M×M |
| EV-D11 | `DELETE /` on a finished run purges only its subject | [implied] | M×M |
| EV-D12 | NATS restarts during a run | [proposed — gap §cross-cutting/resilience] | H×L |
| EV-D13 | Crashed runner never purges | [proposed — gap §per-element/store] | L×M |

- **EV-D1.** Given a run with frames 1–40, when a client attaches with `from_sequence=25`,
  then the first frame it receives has sequence 25, and it receives 25–40 exactly once.
- **EV-D2.** Given a child published frames 1–7 and then exited with code 137, when the
  supervisor classifies the exit, then it publishes `Terminated(failed, oom_killed)` with
  sequence 8.
- **EV-D3.** Given the supervisor read last sequence 7, when a delayed frame 8 from the dead
  child lands before the supervisor publish, then the supervisor publish fails on
  `Nats-Expected-Last-Subject-Sequence`, the supervisor reads again, and it publishes its
  frame as sequence 9. `screamingface_engine_events_publish_conflicts_total` increments. If
  frame 8 is already terminal, the supervisor publishes nothing.
- **EV-D4.** Given a queued run has no frame, when `DELETE /` tombstones it, then the App
  publishes `Terminated(stopped)` with sequence 1 and `Nats-Expected-Last-Subject-Sequence: 0`.
  If a frame appeared first, the App follows today's re-read rule and does not write a second
  terminal frame.
- **EV-D5.** Given a publish of frame 5 times out on the client side but the server stored
  it, when the producer retries with the same `Nats-Msg-Id` (`<topic>:5`), then the stream
  holds frame 5 once.
- **EV-D6.** Given `max_msgs_per_subject=100` in a test config, when one run publishes 150
  frames, then that subject holds frames 51–150, the terminal frame is kept, and other
  subjects keep all their frames.
- **EV-D7.** Given `url4-events` exists with `max_bytes=1 GiB`, when the App starts with
  `max_bytes=2 GiB`, then startup calls `update_stream`, and the stream reports 2 GiB.
- **EV-D8.** Given `url4-events` exists with memory storage, when the App starts with file
  storage configured, then startup fails, and the message names `storage`.
- **EV-D9.** Given `events.maxBytes` is above the JetStream store limit, when the App starts,
  then startup fails with a message that names `events.maxBytes` and the store limit.
- **EV-D10.** Given a run's last frame is sequence 6, when a client attaches with
  `from_sequence=10`, then the behavior equals today's pinned behavior in
  `test_attach_from_sequence_bounds.py` (characterize first).
- **EV-D11.** Given two finished runs A and B, when `DELETE /` runs for A, then subject A is
  empty, and subject B is unchanged.
- **EV-D12.** Given a run is publishing, when the NATS server restarts, then the publisher
  reconnects, the run's frames stay gap-free, or the run ends `failed` with code
  `stream_failed`. A silent gap is not allowed.
- **EV-D13.** Given a child is killed before its teardown, when 24 h pass, then `max_age`
  removes the subject's frames. No sweep is needed.

Cancel, retry, concurrent and empty-state variants: covered by EV-D4 (cancel on empty),
EV-D5 (retry), EV-H3 (concurrent), and EV-D10 (empty or beyond end).

## 4. Non-functional requirements

- **Capacity.** Concurrent runs are no longer capped by stream reservations. The cap is now
  `url4-runq` depth (10 000) and worker slots. `[existing runner_queue.py:86]` A per-run frame
  bound is `max_msgs_per_subject × max_msg_size`. `[proposed]`
- **Throughput.** Target: 2 000 frames/s sustained into `url4-events` on a single-replica
  JetStream in kind, with p99 publish ack under 50 ms. Report only. `[proposed — ans:Q3 report only]`
- **Resume cost.** Resume scans at most `max_msgs_per_subject` frames of one subject.
  `[proposed]`
- **Observability.** New metrics `[proposed]`:
  - `screamingface_engine_events_store_bytes` (gauge)
  - `screamingface_engine_events_store_utilization_ratio` (gauge, bytes ÷ max_bytes), with an
    alert rule at > 0.8 for 5 min, documented in the chart README `[stated ans:Q11]`
  - `screamingface_engine_events_publish_conflicts_total` (counter, label `writer=app|supervisor`)
  - `screamingface_engine_events_subject_purges_total` (counter)
- **Security.** No new trust boundary. Subject names come from the topic, which the App mints.
  `[existing subjects.py:64-65]`

## 5. Out of scope

- A stateless NATS interest gate and more than one App replica (OME-890 follow-up). `[stated ans:Q1]`
- Zero-disruption dual-layout reads. `[stated ans:Q7]`
- Changes to the `url4-runq` stream. `[implied]`

## 6. Open questions

None. `events.maxMsgsPerSubject` has a default (20 000). Phase 0 measures the real frame count
and reports it. The default changes only if the measured p99 frame count is above 2 000
(10× headroom rule). `[proposed]`

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: core-out. The sequence invariant is the highest risk, so the consumer and writer rules
come before the stream swap. Tests at the integration level need a real JetStream
(`URL4_CLOUD_TEST_NATS_URL`). `[existing tests/integration/test_worker_spine.py:27-46]`

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| EVT-C1 | CHAR `frame_sequence_on_wire_equals_producer_sequence_for_fresh_run` | integration | [existing adapters/jetstream.py] | H×H | passes today by design |
| EVT-C2 | CHAR `attach_from_sequence_bounds_behavior` (copy the current asserts) | integration | [existing test_attach_from_sequence_bounds.py] | M×M | passes today |
| EVT-C3 | CHAR `queued_cancel_writes_single_terminal_tombstone` | unit | [existing adapters/queue_runner.py:345-415] | H×M | passes today |
| EVT-1 | `consumer_keeps_producer_sequence_when_stream_sequence_differs` | unit | [implied — I-EV2] | H×H | call `decode(payload)` with no `sequence` argument |
| EVT-2 | `resume_from_sequence_25_delivers_25_to_40_once` | integration | [implied — EV-D1] | H×H | filtered consumer from subject start; skip `seq < from_sequence` |
| EVT-3 | `fifty_interleaved_runs_each_read_gap_free` | integration | [implied — EV-H3] | H×H | shared stream + filter subject |
| EVT-4 | `supervisor_terminal_frame_takes_last_plus_one` | integration | [implied — EV-D2] | H×H | helper `publish_next(topic, frame)`: get last msg for subject, expected-last-subject-seq |
| EVT-5 | `supervisor_retries_on_expected_sequence_conflict` | integration | [proposed — EV-D3] | H×M | retry max 3; skip if the new last frame is terminal |
| EVT-6 | `tombstone_on_empty_subject_is_sequence_1_with_expected_zero` | integration | [implied — EV-D4] | H×M | reuse `publish_next` |
| EVT-7 | `publish_retry_with_same_msg_id_stores_frame_once` | integration | [proposed — EV-D5] | M×M | `Nats-Msg-Id=<topic>:<seq>`, duplicate_window 120 s |
| EVT-8 | `run_frames_land_in_url4_events_and_no_per_topic_stream_exists` | integration | [stated ans:Q1 — EV-H1] | H×M | `ensure_events_stream()` at startup; delete per-topic `_declare` |
| EVT-9 | `teardown_purges_subject_after_grace` | integration | [proposed — EV-H4] | M×M | `purge_stream(filter=subject)` |
| EVT-10 | `delete_run_purges_only_its_subject` | integration | [implied — EV-D11] | M×M | same purge helper in `stop_run` |
| EVT-11 | `per_subject_cap_drops_oldest_of_that_run_only` | integration | [proposed — EV-D6] | M×M | `max_msgs_per_subject` in config |
| EVT-12 | `full_store_drops_oldest_and_gauge_reports_ratio` | integration | [stated ans:Q11 — EV-E1] | M×M | small `max_bytes` in test; gauge from `stream_info` |
| EVT-13 | `startup_updates_mutable_stream_config` | integration | [proposed — EV-D7] | M×M | `update_stream` path |
| EVT-14 | `startup_fails_on_immutable_mismatch_naming_field` | integration | [proposed — EV-D8] | M×L | compare config; raise |
| EVT-15 | `startup_fails_when_max_bytes_exceeds_store` | integration | [proposed — EV-D9] | M×L | map `JSInsufficientResourcesErr` to a startup error |
| EVT-16 | `nats_restart_mid_run_never_leaves_silent_gap` | integration | [proposed — EV-D12] | H×L | reconnect; on unrecoverable publish error end `failed/stream_failed` |
| EVT-17 | `purge_legacy_streams_deletes_only_url4_cloud_prefix` + `--dry-run` lists | integration | [stated ans:Q7 — EV-E3] | M×M | new `admin` CLI subcommand; uses `owns_stream()` rule |
| EVT-18 | `sweep_and_10047_paths_are_gone` (import / grep test) | unit | [proposed] | L×M | delete `_sweep_orphans`, memo, 10047 handling |
| EVT-19 | `chart_renders_events_values_and_alert_doc` | unit (chart render) | [stated ans:Q11 — EV-E2] | L×M | values `events.*`; schema; README alert rule |

**Refactor notes.** Put `publish_next` in one module (`adapters/jetstream.py`) and use it from
the App tombstone and the supervisor. Delete `stream_for()` when no caller is left. The
subject helper `subject_for()` stays.
