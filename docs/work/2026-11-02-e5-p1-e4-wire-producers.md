---
ticket: OME-1802
stack: screamingface-engine
status: done
started: 2026-11-02
finished: 2026-11-02
---

# e5-p1-e4-wire-producers — PR 3: wire the Run registry, its writer and every outcome producer

## Intent

PR 3 of the E5 P1 Engine stack (`docs/plan/2026-10-30-e5-p1-first-class-run.md`, units E4, E5
and E6; spec `docs/spec/2026-10-27-e5-p1-first-class-run.md`), stacked on PR 2 (#1634), under
`OME-1785`. It wires the registry and its one writer into the App and local mode, and makes every
terminal writer publish its Candidate's outcome when its own terminal frame landed (spec R3, R4).
The first PR that changes runtime behaviour: a hosted App without a database URL runs with Runs
off, exactly as today.

## Planned changes

E4, wiring (paths under `apps/screamingface-engine/`):
- `src/screamingface_engine/runs/consumer.py` (new): consume, `settle`, ack only after the
  commit; restart the consumer after an error.
- `src/screamingface_engine/runs/wiring.py` (new): open the database, refuse an un-migrated one
  or a hosted SQLite URL, start and stop the consumer; Runs off (a warning) on a hosted App with
  no URL.
- `src/screamingface_engine/app.py`, `local.py`, `cli.py`: call the wiring; `serve --local`
  migrates first; the App and the runner pool `ensure_stream()` the outcome stream.
- `deploy/helm/`: the database Secret on the App only, `templates/job-migrate.yaml`, and
  `candidateOutcomes.maxAge`/`maxBytes` on both the App and the runner pool (`values.yaml`,
  `values.schema.json`).
- `DEPLOYMENT.md`: the R10 runbook.

E5, App-side producers:
- `adapters/inprocess.py` `_on_done`: a `SettlementWatch`, and one outcome per run.
- `adapters/queue_runner.py` `_publish_tombstone` and `adapters/max_deliveries.py`
  `_publish_failure`: write the frame with `publish_next`, and publish the outcome only when it
  returns True (owner decision 2026-11-02).

E6, worker-side producers:
- `child_protocol.py`: `SETTLED {json}` encoder and decoder (stdlib only, cost as a string).
- `runner/main.py`: the warm child keeps its control pipe open through the run and sends
  `SETTLED` when its own frames were not dropped (`JetStreamPublisher.dropped(topic)`).
- `worker/warm_pool.py`, `worker/supervisor.py`: read `SETTLED` after the child exits; publish it,
  or the supervisor's own classification (no cost) when its `publish_next` landed;
  `_publish_terminal` publishes for a run that never executed.

Every outcome publish is best effort: a failed publish is logged and never fails the run, its
terminal frame or its ack.

## Test plan

- E4: a registry that raises leaves the delivery unacked, and the redelivery settles after it
  recovers; a repeat after success is a no-op; a hosted App with no URL starts with Runs off and
  warns; a hosted SQLite URL refuses to start; a fresh SQLite migrates at local start; an
  un-migrated database stops the App naming the migrate step; the chart tests, with no database
  URL or Secret on the runner Deployment.
- E5: in-process success, failure, timeout and cancel; a tombstone; max deliveries; max
  deliveries losing to a final success publishes nothing.
- E6: the `SETTLED` round trip and malformed lines refused; a child's `SETTLED` with cost; a child
  killed before reporting; a spawn failure and an expired message; a tombstone then the worker's
  later claim publishes nothing more; a duplicate claim.

## Acceptance

- Each terminal writer publishes exactly one outcome, only when its own frame landed.
- A hosted App without a database URL behaves as today.
- Full engine gates and the chart tests green in CI.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the spec and plan updated to match what was built, plus `src/screamingface_engine/adapters/factory.py`
  (`build_candidate_outcome_stream`), `worker/loop.py` (the worker declares and passes the
  outcome stream), `adapters/jetstream.py` (`JetStreamPublisher.dropped`), `run_evidence.py`
  (`publish_landed`), `candidate_outcomes.py` (`publish_outcome`; `consume` typed as an async
  generator; `ensure_stream(update=)`), and `tests/conftest.py` (a per-test local Run database).
  `cli.py` is unchanged: `serve --local` already builds the App through `create_local_app`.
- **Commits:** `af28c6f83` E4 wiring; `6d20612ae` E5 App-side producers; `e82bbe9f8` E6
  worker-side producers.
- **Gates:** targeted suites, lint, types, the layering gate and the append-only check green
  locally; the full gates run in CI.
- **Deviations:**
  - Landed-frame detection uses `publish_next`'s return value, through `publish_landed`, and a
    read-only `JetStreamPublisher.dropped(topic)` for the child (owner decision 2026-11-02). A
    publisher without `publish_next` has no first-terminal rule, so its frame counts as landed.
  - The local database is the Engine's own, `engine.sqlite3`, beside the artifacts dir when no
    URL is given (owner decision 2026-11-02, matching `aigateway.sqlite3`). C2 has the Client
    pass it explicitly in its data dir.
  - Chart values follow the existing `events.*` naming: `candidateOutcomes.maxAgeS` and
    `maxBytes`; the Secret key defaults to `database-url`, as for aigateway and scoreboard. The
    migrate Job uses the namespace default ServiceAccount with no token, because a pre-install
    hook runs before the chart's own ServiceAccount exists.
  - The warm child keeps its control pipe open through the run to send `SETTLED`; the pool reads
    it after the child exits (`WarmChildPool.settlement`).
  - `mark_scheduled` reporting whether it applied moves to E8, where the start route uses it.
  - Not exercised in CI: a real warm child sending `SETTLED` over a real pipe
    (`tests/integration/test_warm_child_process.py` needs a broker and is not in the conformance
    job).

## Review of #1634 and #1639 (2026-11-05)

- Done: `ensure_stream` refuses a live stream whose `max_age`, `max_bytes` or `max_msg_size` is
  below this code's (widening and unlimited stay allowed); startup applies `max_msg_size`.
- Done: outcomes are capped at 64 KiB (`MAX_OUTCOME_BYTES`), on the stream and in the decoder.
- Done: SETTLED carries the child's `finished_at`; the supervisor relays it.
- Done: an unreachable database at start raises `DatabaseUnreachableError`, naming the host with
  the password hidden; spec R9 and §9 record fail-fast.
- Kept: `db.using` sets Tortoise's private context variable, because the public `with context:`
  shares one token across tasks. A test fails if Tortoise stops reading it; the pin is held by
  hand (#1634).
- Done: a bare `serve --local` keeps its database in `~/.screamingface-engine/`, not beside the
  temp artifacts dir (spec D2).
- Done: local shutdown stops the runner before the Runs writer.
- Done: the R10 runbook (`DEPLOYMENT.md`) has a NetworkPolicy step.
- Open: checking NetworkPolicy reach, Cloudflare Access and Envoy-only ingress in dev, staging
  and prod needs new Firecall sessions.
