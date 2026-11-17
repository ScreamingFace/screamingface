# Contracts — frozen copy retention

**Base:** `origin/main` at `e9db97cfb`. Paths are relative to the repo root.
One section for each connection that this spec adds or changes. Test numbers refer to the TDD
tables: `S-n` in `prd/copy-sweep.md`, `K-n` in `prd/score-claim.md`, `R-n` in
`prd/expired-copy-replay.md`. `CH-n` tests are named with their PRD.

Error bodies of the gateway use the shape that the frozen copy routes use today:
`{"detail": {"code": "<code>", "message": "<text>"}}`
`[existing apps/aigateway/src/aigateway/routes/frozen_copies.py:84-91]`. Where this spec adds a
`state` field, it is in `detail` next to `code`.

## K1 — Engine → AI Gateway, capture write (existing, behavior for new states) — sync, HTTP

- **Routes:** `POST /v1/chat/completions` with the header `X-AIGW-Frozen-Copy`, and
  `POST /v1/frozen-copies/{id}/tool-results`. No change to request, response or write path.
- **New states:** a write to a copy that is not `open` is refused as it is today
  `[existing apps/aigateway/src/aigateway/core/frozen_copy/store.py:171-172]`. This now includes
  `abandoned` and `expired`. The model call is still served, and the capture result is
  `refused`. The tool-result route answers 409 `frozen_copy_sealed` for each status that is not
  `open`, as today
  `[existing apps/aigateway/src/aigateway/routes/frozen_copies.py:241-242]`. `[implied]`
- **Contract tests:** `prd/copy-sweep.md` CH-1, S-13.

## K2 — Engine → AI Gateway, seal (existing, changed) — sync, HTTP

- **Route:** `POST /v1/frozen-copies/{id}/seal`. Owner only.
- **Shape, success (no change):** `200 {"id", "status": "sealed", "entries"}`
  `[existing apps/aigateway/src/aigateway/routes/frozen_copies.py:211]`.
- **Delta:** a seal by the owner of a copy with status `abandoned` or `expired` answers
  `410 {"detail": {"code": "frozen_copy_expired", "state": "abandoned" | "expired", "message": …}}`
  and changes nothing. A seal by a caller that is not the owner answers the 404
  `frozen_copy_not_found` of today, for each state. `[implied]`
- **Caller side:** the engine reads a seal as done only when the body says `sealed`
  `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:686-690]`. A
  410 thus gives the partial reason `seal`. No engine change. `[implied]`
- **Idempotency:** a repeat seal of a sealed copy returns it unchanged, as today.
- **Contract tests:** `prd/copy-sweep.md` CH-2, S-9.

## K3 — Engine → AI Gateway, replay read (existing, changed) — sync, HTTP

- **Routes:** `POST /v1/frozen-copies/{id}/chat/completions` and
  `POST /v1/frozen-copies/{id}/tool-results/lookup`.
- **Shape by copy status:**

  | Copy | Answer |
  |---|---|
  | `sealed` | as today |
  | `open`, unknown id, malformed id, `abandoned` | `404 {"detail": {"code": "frozen_copy_unavailable", …}}` (as today for the first three) |
  | `expired` | `410 {"detail": {"code": "frozen_copy_expired", "state": "expired", "message": "the frozen copy expired and its entries were deleted"}}` |

- **Rule:** the 410 never carries the header `X-AIGW-Replay`. That header marks a captured
  error; an engine that does not know the 410 then reads it as "the copy did not serve this
  call". `[implied]`
- **Caller side (engine):** 410 with `frozen_copy_expired` → permanent failure, code
  `frozen_copy_unavailable`, the engine's own expired text. No retry: a retry of a replay call
  reads the next occurrence
  `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:1499-1502]`.
- **Contract tests:** `prd/expired-copy-replay.md` CH-1, CH-3, R-1, R-2, R-3, R-4, R-6.

## K4 — Scoreboard → AI Gateway, claim (new) — sync, HTTP

- **Route:** `POST /v1/frozen-copies/{copy_id}/claim`. No request body.
- **Caller identity:** header `X-User-Email: <SCOREBOARD_GATEWAY_ACTOR>`. In
  `cloudflare_headers` mode the gateway accepts the call only from a peer in its trusted
  networks, and only when the email is in `AIGW_FROZEN_COPY_CLAIM_EMAILS`. The guard follows
  `require_admin` `[existing apps/aigateway/src/aigateway/core/auth/admin.py:79-129]` and makes
  no account row. `[proposed]`
- **Shape:**

  | Case | Answer |
  |---|---|
  | `sealed`, first claim | `200 {"id", "status": "sealed", "claimed_at": "<ISO time>", "already": false}` |
  | `sealed`, claimed before | `200 {…, "claimed_at": "<first time>", "already": true}` |
  | `open` | `409 {"detail": {"code": "frozen_copy_not_sealed", …}}` |
  | `abandoned` or `expired` | `410 {"detail": {"code": "frozen_copy_expired", "state": "abandoned" | "expired", …}}` |
  | unknown or malformed id | `404 {"detail": {"code": "frozen_copy_not_found", …}}` |
  | `cloudflare_headers` mode: claim list empty | `503` |
  | `cloudflare_headers` mode: untrusted peer, or email not in the list | `403` |
  | `cloudflare_headers` mode: no identity header | `401` |
  | `jwt` mode | `503` |
  | `disabled` mode (loopback only) | the call is accepted with no list |

- **Policies:**
  - Timeout on the caller side: `SCOREBOARD_GATEWAY_TIMEOUT_S` (5 s). No retry in the
    scoreboard. `[proposed]`
  - Idempotent: a claim can be sent any number of times. `[proposed]`
  - The gateway takes the row lock of the copy, reads the status under the lock, and sets
    `claimed_at` only for `sealed` with `claimed_at IS NULL`. `[proposed]`
- **Failure behavior, caller side:** the decision table of `prd/score-claim.md` §3.4. The
  caller reads `detail.code` and `detail.state`. Each answer that the table does not name is
  "unavailable": this includes a 404 with no `detail.code` (a wrong URL, or a gateway with no
  claim route). `[proposed]`
- **Failure behavior, callee side:** a database error gives 500 and no change. `[implied]`
- **Network:** the gateway NetworkPolicy must admit the scoreboard pod. In the chart, add one
  element to `networkPolicy.allowFrom` that has both the namespace selector and the pod selector
  of the scoreboard
  `[existing apps/aigateway/charts/aigateway/templates/networkpolicy.yaml:31-32]`. Do not use
  `clientPodNames`: that list is for one namespace only
  `[existing apps/aigateway/charts/aigateway/templates/networkpolicy.yaml:20-26]`. The
  production values are in the infrastructure repo.
- **Contract tests:** `prd/score-claim.md` K-1 to K-8, K-25; race: `prd/copy-sweep.md` S-14.

## K5 — SDK → Scoreboard, submit (existing, changed) — sync, HTTP

- **Route:** `POST /v1/scores`. No change to the request.
- **Delta, three new refusals.** The text below is the exact message.

  | Case | Answer |
  |---|---|
  | the copy expired | `422 {"detail": {"code": "frozen_copy_expired", "message": "the pinned cache of this run expired: no score used it in its retention period. Run the evaluation again with capture=True to submit a reproducible score."}}` |
  | the copy is open, abandoned, or not known to the gateway | `422 {"detail": {"code": "frozen_copy_unavailable", "message": "the pinned cache of this run is not available: the run did not seal it, or this gateway does not hold it. Run the evaluation again and submit the new result."}}` |
  | the gateway did not answer the claim | `503 {"detail": {"code": "frozen_copy_check_unavailable", "message": "the pinned cache of this run could not be checked. Try again."}}` with `Retry-After: 5` |

- **Caller side (no SDK change):** the SDK shows `code: message` for a 422
  `[existing packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:552-562]`. It
  reads a 422 as permanent and a 503 as temporary. For a 503 it makes 3 attempts in total
  `[existing packages/screamingface/src/screamingface/_core/retry.py:38-40]`, each with the same
  `Idempotency-Key`
  `[existing packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:182]`.
- **Order on the callee side:** identity → benchmark check → claim (K4) → store. The claim is
  outside each database transaction. `[proposed]`
- **Contract tests:** `prd/score-claim.md` CH-1, CH-2, K-9 to K-16, K-35.

## K6 — Operator → AI Gateway, sweep command (new) — process, CLI

- **Command:** `python -m aigateway.frozen_copy_sweep`, run in the gateway pod with
  `kubectl exec`.
- **Modes and arguments:**

  | Arguments | Mode |
  |---|---|
  | (none) | **Dry run** at the current database time. Changes nothing. |
  | `--cutoff <ISO time with zone>` | Dry run that evaluates the rules at this time. A future time is allowed. |
  | `--run [--max-entries <n>]` | **One full pass** by hand: mark by each rule, then purge up to the budget. The same code as one periodic run (K7). |

  `--run` with `--cutoff` is refused.
- **No list and no approval.** The command has no `--execute`, no candidate list and no
  digest. The dry run is a read-only report for the operator, and no release step needs an
  approval of it. `[stated ans:Q23]` The command reads no switch, because none exists.
  `[stated ans:Q22]`
- **Dry-run output (stdout, one JSON document):**
  ```json
  {
    "evaluated_at": "<ISO time>",
    "rules": {"abandoned": {"copies": 0, "entries": 0}, "expired": {"copies": 0, "entries": 0}},
    "by_account": [{"account": "<name>", "rule": "abandoned", "copies": 0, "entries": 0}],
    "candidates": [{"rule": "abandoned", "id": "<uuid>", "entries": 0}]
  }
  ```
  Before pull request C1, the code has no expiry rule, and the numbers for `expired` are 0.
- **Output of `--run` (stdout, JSON):** for each rule the copies marked and the copies skipped
  with the cause (`rule no longer true`, `lock timeout`, `newest entry not found`); the
  entries deleted, the copies completed, the copies that still have entries, and the cause if
  the purge stopped early.
- **Exit status:** 0 = done; 2 = bad arguments; 1 = a failure during the run (the changes
  before the failure stay).
- **Idempotency:** each mode can be run again. `[proposed]`
- **Contract tests:** `prd/copy-sweep.md` S-17, S-21, S-34, S-35.

## K7 — Periodic trigger → sweep (new) — in process

- **Start and stop:** the gateway lifespan always starts the trigger, with no condition, and
  stops it at shutdown, next to the snapshot scheduler
  `[existing apps/aigateway/src/aigateway/main.py:224-244]`. No setting turns it off.
  `[stated ans:Q22]`
- **Policies:** the first run is 1 to 5 minutes after the start (a random delay); then one run
  for each interval; no run starts while one is in progress in the same process; a failed run
  is logged and the next interval runs as normal. `[proposed]`
- **Test seam.** The trigger gets its `sleep`, its `now` and its start delay as constructor
  arguments and binds them when it is built, as `CacheSnapshotScheduler` does
  `[existing apps/aigateway/src/aigateway/core/snapshot_scheduler.py:85-86]`. It never looks
  up `asyncio.sleep` at call time: some existing tests patch the global `asyncio.sleep`, and
  each gateway test that uses `TestClient` runs the lifespan with the trigger armed. The
  lifespan puts the trigger on `app.state.frozen_copy_sweep_trigger`, so that a test can
  inject one and inspect it. `[proposed]`
- **One run:** idle rule → expiry rule → purge up to `AIGW_FROZEN_COPY_SWEEP_MAX_ENTRIES`. The
  expiry rule is in the code from pull request C1. The first run after a release is a normal
  run. `[stated ans:Q23]`
- **More than one replica, or a command at the same time:** no global lock. Runs are safe
  together (K8). `[proposed]`
- **Contract tests:** `prd/copy-sweep.md` S-16, S-23, S-24.

## K8 — Sweep → Postgres (new) — data

- **Mark (one transaction for each copy):** `SELECT … FOR UPDATE` on the copy row with
  `lock_timeout` 2 s → evaluate the rule again → update `status`, `swept_at`, and `entries` for
  an abandoned copy → commit.
  - Idle rule under the lock: `status = open` first. A copy that was sealed while the mark
    waited for the lock is skipped (`rule no longer true`). Then read the `created_at` of the
    entry with `seq = entry_seq`. If `entry_seq > 0` and that entry does not exist, skip the
    copy (`newest entry not found`).
  - A copy with `entry_seq = 0` has no entry to delete. Its mark sets `purged_at` in the same
    transaction, with the statement of "End of a purge" below (`prd/copy-sweep.md` S16).
  - Expiry rule under the lock: `status = sealed`, `claimed_at IS NULL`, and
    `now ≥ COALESCE(retention_from, sealed_at) + ttl` (`erd.md` §2.4).
- **Purge (one transaction for each chunk):** delete at most 500 entries of one marked copy by
  id, selected with `FOR UPDATE SKIP LOCKED` → commit → wait 200 ms.
- **End of a purge:** when a chunk finds no row, set `purged_at` with one statement that has
  its own check and no `SKIP LOCKED`:
  `UPDATE frozen_copies SET purged_at = :now WHERE id = :id AND purged_at IS NULL AND NOT EXISTS (SELECT 1 FROM frozen_copy_entries WHERE frozen_copy_id = :id)`.
  The time `:now` is a timezone-aware UTC value that the code passes as a parameter, so that
  Postgres and SQLite store one format.
  "A chunk found no row" is not sufficient: a second purge can hold locks on the last rows, and
  it can roll back. If the statement changes no row, the next run tries again. `[proposed]`
- **Read-modify-write races:** the row lock of the copy is the one lock point for capture
  `[existing apps/aigateway/src/aigateway/core/frozen_copy/store.py:169-170]`, seal
  `[existing apps/aigateway/src/aigateway/core/frozen_copy/store.py:127-132]`, claim (K4) and
  mark. `[proposed]`
- **Partial write:** a failure between two chunks leaves a marked copy with some entries and
  `purged_at IS NULL`. The next run completes it. No reader can see such a copy as `open` or
  `sealed` (I3). `[proposed]`
- **Storage full:** a delete needs WAL space. If the server has no space, the run fails and is
  logged; nothing is lost. `[implied]`
- **SQLite:** no row lock, no `SKIP LOCKED`, no `lock_timeout`. The rules are the same; the lock
  tests run on Postgres only.
  `[existing apps/aigateway/src/aigateway/core/frozen_copy/store.py:5-7]`
- **Contract tests:** `prd/copy-sweep.md` S-7, S-8, S-13, S-14, S-15, S-16, S-31, S-36.

## K9 — Scoreboard claim pass: start task and operator command (new) — in process, CLI

- **One function, two callers.** The claim pass sends one claim (K4) for the copy of each
  Score with a `frozen_copy_id`, one call at a time, with the claim client of the submit
  route. `[stated ans:Q25]`
- **The query:** one read of each Score with a `frozen_copy_id`, on all boards, with no filter
  on the board or on its visibility. `[proposed]`
- **Results for one Score:** `claimed`, `already`, `not_sealed`, `abandoned`, `expired`,
  `not_found`.
- **Caller 1, the start task.** The scoreboard lifespan starts one background task when
  `SCOREBOARD_GATEWAY_URL` is set. It does not delay startup or readiness.
  - Each pod runs the pass at each start. This is safe: a claim is idempotent (K4).
  - If the gateway does not answer, the pass stops, the task writes one WARNING record, waits
    10 minutes and starts the pass again from the first Score. It repeats until one pass
    completes. Then the task ends. `[proposed]`
  - At the end of a complete pass, the task writes one INFO record with the number of Scores
    and the count of each result.
  - If one or more results are not `claimed` or `already`, it writes one WARNING record with
    the Score ids and the copy ids of those results (one record, not one for each Score). The
    list is information for the owner. `[stated ans:Q20]`
  - At shutdown, the lifespan cancels the task and waits for it, then closes the claim client,
    then closes the database.
  - With no gateway URL, no task runs.
  - No schedule, no table, no interlock. `[stated ans:Q17]`
- **Caller 2, the command.** `python -m scoreboard.claim_copies [--dry-run]`, run by hand in a
  scoreboard pod.
  - **Output (stdout, one JSON line for each Score that names a copy):** `score_id`,
    `frozen_copy_id`, `result`. Then one summary line with the number of Scores and the count
    of each result. With `--dry-run` it prints the Scores and makes no call.
  - **Exit status:** 0 = each copy is `claimed` or `already`; 3 = one or more copies have a
    different result; 1 = the gateway did not answer (the command stopped); 2 = no gateway
    URL.
- **Idempotency:** safe to run again at any time (K4). `[proposed]`
- **Contract tests:** `prd/score-claim.md` K-18 to K-22, K-27 (command), K-28 to K-34 (start
  task).

## K10 — Layering (dependency rules)

- The scoreboard depends on the gateway only through K4. It does not read the gateway
  database. `[proposed]`
- The gateway does not call the scoreboard. `[proposed]`
- The engine does not call K4. Only the scoreboard knows that a Score exists.
  `[proposed]`
- Check: the layering script of the repo (`.claude/scripts/check_layering.py`) and the review.
