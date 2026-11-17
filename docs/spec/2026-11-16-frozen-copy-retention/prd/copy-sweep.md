# PRD: the frozen copy sweep

**Source:** prompt, ans:Q2, ans:Q5, ans:Q7, ans:Q12, ans:Q13, ans:Q16, ans:Q18, ans:Q22, ans:Q23,
ans:Q24 (ans:Q22 and ans:Q23 reverse ans:Q15 and ans:Q3)
· **Priority:** P0
**Lifecycle:** planned (new component in `apps/aigateway`)
**Owner:** unassigned

Paths are relative to the repo root. Gateway source paths that start with `core/`, `routes/`,
`main.py` or `config.py` are under `apps/aigateway/src/aigateway/`.

## 1. Summary

The sweep is a background job in the AI Gateway. No user flow starts it. It serves two rules:

1. **Idle rule.** An `open` copy that gets no entry for 24 hours becomes `abandoned`, and the
   sweep deletes its entries. `[stated ans:Q5]`
2. **Expiry rule.** A `sealed` copy that no Score claims becomes `expired` 90 days after its
   clock starts, and the sweep deletes its entries. `[stated ans:Q2]`

The sweep is always active. It has no switch, and no person approves a list before it deletes
`[stated ans:Q22]` `[stated ans:Q23]`. Its first run after a release is a normal run. An
operator can also run the sweep by hand as a command, or ask it for a report that changes
nothing (a dry run).

The idle rule is released first (stack A). The expiry rule is released after the claim is
live (pull request C1, `00-overview.md` §2).

The claim that keeps a copy alive is specified in `prd/score-claim.md`. The answer that a replay
of a swept copy gets is specified in `prd/expired-copy-replay.md`.

## 2. Background and constraints

- "the Postgres grew a lot in the last days … understand … if is something like temp frozen
  copies not related to submissions" and "work in a spec to properly fix all of these".
  `[stated prompt]`
- Audit of production, 2026-11-16 (read-only): `frozen_copy_entries` held 40.7 GB of the 47 GB
  database. 327 open copies with no entry for more than 24 hours held about 16 GB on disk
  (1.07 million entries). 12 188 sealed copies with no Score held about 9 GB.
- A manual cleanup on 2026-11-16 deleted a part of those open copies with direct SQL
  (`00-overview.md` §9.4). Its measurements are used in §4.2.
- The data model, the two rules and the invariants are in `erd.md` §2.

### 2.1 Current behavior

- A copy has two states, `open` and `sealed`. `[existing core/frozen_copy/models.py:21-22]`
- The engine seals a copy only when the run's process reaches the end of its work. It never
  seals after a cancellation.
  `[existing apps/screamingface-engine/src/screamingface_engine/runner/executor.py:1111-1113]`
  A cancel by the user, a deadline, a memory kill, a hard-wall kill, a crash and a pod drain all
  leave the copy `open`. A run that the queue delivers again opens a second copy.
  `[existing apps/screamingface-engine/src/screamingface_engine/runner/executor.py:1117-1127]`
- The supervisor process does not know the copy id, so it cannot close the copy for a killed
  child. The id is only in the memory of the child process.
  `[existing apps/screamingface-engine/src/screamingface_engine/capture_outcomes.py:136]`
- The gateway has no function that deletes a copy or an entry, and no periodic job for copies.
  `[existing core/frozen_copy/store.py:110-222]`
- A replay refuses an `open` copy. Thus an `open` copy whose run ended has no use.
  `[existing routes/frozen_copies.py:94-110]`
- An entry is stored when a model call or a tool call ends. Each insert adds 1 to `entry_seq`
  under the row lock of the copy. `[existing core/frozen_copy/store.py:169-176]`
- The one periodic job in the gateway is the cache snapshot scheduler.
  `[existing core/snapshot_scheduler.py:66]` `[existing main.py:224-244]`

**Delta.** This PRD adds the two end states, the rules that lead to them, the deletion of
entries, a periodic trigger and an operator command. It does not change the engine
`[stated ans:Q13]`: no process can run cleanup code after a `SIGKILL`, so a rule on the gateway
side is necessary in all cases.

## 3. Scenarios and acceptance criteria

Terms: `idle_since`, `retention_from` and the two rules are defined in `erd.md` §2.4. "Mark" = set
`status` and `swept_at` under the row lock. "Purge" = delete the entries of a marked copy, then
set `purged_at`.

One periodic run does three steps in this order: mark by the idle rule, mark by the expiry
rule, purge up to the budget. Before pull request C1, the code has no expiry rule, and a run
does the other two steps.

Ids that are not used: S6, S8, S11, S14 and S15. They were scenarios of the two switches and
of the approved list, which the owner removed `[stated ans:Q22]` `[stated ans:Q23]`.

### 3.1 Happy path

- **S1. An idle open copy is abandoned.** `[stated ans:Q5]` Must
  - Given an `open` copy whose newest entry is 24 hours old or more
  - When the sweep runs
  - Then the copy has `status = abandoned` and `swept_at` set, and `entries` holds the value of
    `entry_seq`
  - And after the purge, the copy has no entry and `purged_at` is set
  - And the row of the copy stays. `[stated ans:Q12]`
- **S2. An active open copy is not touched.** `[stated ans:Q5]` Must
  - Given an `open` copy that is 40 hours old and got an entry 10 minutes ago
  - When the sweep runs
  - Then the copy stays `open` and keeps all its entries.
- **S3. An unclaimed sealed copy expires.** `[stated ans:Q2]` Must
  - Given a `sealed` copy with `claimed_at IS NULL` for which
    `COALESCE(retention_from, sealed_at) + 90 days` is in the past
  - When the sweep runs
  - Then the copy has `status = expired`, and after the purge it has no entry.
- **S4. A claimed copy never expires.** `[stated ans:Q2]` Must
  - Given a `sealed` copy with `claimed_at` set, sealed 400 days ago
  - When the sweep runs
  - Then the copy stays `sealed` and keeps all its entries.
- **S5. The clock of an old copy starts at the release.** `[stated ans:Q7]` `[stated ans:Q24]` Must
  - Given migration 0019 ran on 2026-12-01 and wrote that time into `retention_from` of an
    unclaimed copy that was sealed on 2026-10-15
  - When the sweep runs on 2027-02-01 (62 days after the stamp, 109 days after the seal)
  - Then the copy stays `sealed`
  - And when the sweep runs on 2027-03-01 or later, the copy becomes `expired`.
  - And a copy that is sealed after the migration has `retention_from IS NULL`, and its 90 days
    start at its seal.
- **S7. A dry run changes nothing and gives a report.** `[proposed]` Must
  - Given the operator runs `python -m aigateway.frozen_copy_sweep` with no other argument
  - Then the command changes no row. It prints one JSON document with: the time of the
    evaluation, the number of copies and entries for each rule, the same numbers for each
    account, and the list of candidates (rule, copy id, number of entries).
  - The dry run is a tool for the operator. No release step needs it, and no person must
    approve its document. `[stated ans:Q23]`
- **S26. A run by hand.** `[proposed]` Should
  - Given the operator runs the command with `--run`
  - Then the command does one full pass (mark by each rule, then purge up to the budget), with
    the same code as the periodic run, and prints the result of §4.4.
  - `--max-entries <n>` sets the purge budget of this pass.
- **S27. The first run after a release is automatic.** `[stated ans:Q23]` Must
  - Given the gateway starts for the first time with this code, and the database holds idle
    open copies
  - When the first periodic run comes, 1 to 5 minutes after the start
  - Then it marks each copy for which a rule is true, with no list and no approval, and purges
    up to the budget. The next runs purge the rest.

### 3.2 Error paths

- **S9. The database fails during a purge.** `[implied]` Must
  - Given the purge of a copy is in progress
  - When a statement fails
  - Then the run stops and logs the error. Entries that were deleted stay deleted. The copy
    stays `abandoned` or `expired` with `purged_at IS NULL`.
  - And the next run continues the purge of that copy.
- **S10. The sweep cannot lock a copy row.** `[proposed]` Must
  - Given another transaction holds the row lock of a candidate copy for more than 2 seconds
  - When the sweep tries to mark that copy
  - Then the sweep skips the copy in this run and continues with the next one.

### 3.3 Derived scenarios (risk order)

- **S12. A claim races the expiry mark.** `[proposed]` H×L Must
  - Given an unclaimed `sealed` copy that the expiry rule selects, and one claim and one sweep
    mark that start at the same time
  - Then either the claim commits first and the copy stays `sealed` with all its entries, or
    the mark commits first and the claim gets 410. A claimed copy never loses an entry (I1).
- **S13. A capture write races the idle mark.** `[proposed]` H×L Must
  - Given an `open` copy at its idle limit, and one capture write and one sweep mark that start
    at the same time
  - Then either the write commits first, the sweep reads the new newest entry under the row
    lock, and the copy stays `open`; or the mark commits first, and the write is refused as a
    write to a copy that is not open.
  - In neither result does an entry exist for a copy that the sweep purged (I3).
- **S16. An open copy with no entry.** `[implied]` M×M Must
  - Given an `open` copy with `entry_seq = 0`, created 24 hours ago or more
  - Then the mark sets `status = abandoned` and `purged_at` in one transaction. The copy has no
    entry to delete, so it does not wait for the purge step and does not use the purge budget
    (`contracts.md` K8).
- **S17. The purge budget is reached.** `[proposed]` M×H Must
  - Given the marked copies hold more entries than the budget of one run
  - When one run reaches the budget
  - Then the run stops the purge and reports the number of copies that still have entries. The
    next run continues with the copy that was marked first.
- **S18. Two sweeps at the same time.** `[proposed]` M×L Must
  - Given the periodic sweep is in progress, and an operator starts the command with `--run`
  - Then both runs complete with no error and no lost update. Each mark is under the row lock,
    and each purge chunk selects its rows with `FOR UPDATE SKIP LOCKED`, so the two runs do not
    wait for each other.
  - And `purged_at` is set only by the statement of `contracts.md` K8, which checks that no
    entry remains. If one purge rolls back after the other found no row, `purged_at` stays
    `NULL`, and a later run completes the purge (I4).
  - The sweep has no global lock. A lock that stays held after a failure would stop all later
    runs with no signal.
- **S19. A seal comes for a swept copy.** `[implied]` M×L Must
  - Given a copy with status `abandoned` or `expired`
  - When its owner sends a seal
  - Then the gateway answers 410 with `detail.code = frozen_copy_expired` and `detail.state`,
    and the copy does not change.
  - When a caller that is not the owner sends a seal
  - Then the gateway answers the 404 of today.
  - Note: today the seal code seals each copy that is not `sealed`
    `[existing core/frozen_copy/store.py:135-141]`. It must seal only an `open` copy.
- **S20. A run repeats on a purged copy.** `[implied]` L×M Must
  - Given a copy that is `abandoned` with `purged_at` set
  - When the sweep runs again
  - Then the copy does not change, and `swept_at` and `purged_at` keep their values.
- **S21. A dry run for a future time.** `[proposed]` L×M Should
  - Given the operator passes `--cutoff` with a time in the future and no `--run`
  - Then the document shows the copies that the rules select at that time. This lets the owner
    see what expires on a date before it occurs.
  - Given `--run` together with `--cutoff`, the command refuses with status 2.
- **S22. Bad settings.** `[proposed]` M×L Must
  - Given one of the four settings of §4.1 has a value outside its limit (for example an
    interval below 60 seconds, or an idle time of 0)
  - Then the gateway refuses to start and names the setting.
- **S23. The gateway starts again and again.** `[proposed]` M×L Must
  - Given the gateway pod starts again more often than one time for each interval
  - Then the sweep still runs: the first run is 1 to 5 minutes after each start (a random
    delay), and the next runs follow at the interval.
- **S24. The database is slow during a purge.** `[proposed]` M×H Must
  - Given the mean time of the last 10 purge chunks is more than 5 seconds
  - Then the run stops the purge and reports the cause. The next run continues.
  - Reason: in the manual cleanup of 2026-11-16, the time of one chunk of 500 entries went
    from about 1 second to 10–15 seconds while the automatic vacuum of Postgres worked on the
    same table. A longer pause between chunks did not help.
- **S25. A seal races the idle mark.** `[proposed]` H×L Must
  - Given an `open` copy at its idle limit, and one seal and one sweep mark that start at the
    same time
  - Then either the seal commits first, the sweep reads `status = sealed` under the row lock,
    and the copy stays `sealed` with all its entries; or the mark commits first, and the seal
    gets 410 (S19).
  - A copy that is `sealed` is never marked `abandoned`. This race is possible when the idle
    setting is below the run deadline `[stated ans:Q18]`.
- **Not applicable.** Empty state: a database with no copy gives an empty report (covered by
  the test of S7). Unicode and nested input: the sweep reads no user text.

## 4. Non-functional requirements

### 4.1 Settings

All settings are declared in `apps/aigateway/src/aigateway/config.py` with an explicit
`validation_alias`, as `request_cache_enabled` is `[existing config.py:162-163]`. Each one gets a
key in `charts/aigateway/values.yaml` and a line in `templates/configmap.yaml`
`[existing apps/aigateway/charts/aigateway/templates/configmap.yaml:46]`.

| Setting | Type | Default | Limit | Source |
|---|---|---|---|---|
| `AIGW_FROZEN_COPY_SWEEP_INTERVAL_SECONDS` | int | `3600` | ≥ 60 | `[proposed]` |
| `AIGW_FROZEN_COPY_OPEN_IDLE_SECONDS` | int | `86400` | > 0 | `[stated ans:Q5]` `[stated ans:Q18]` |
| `AIGW_FROZEN_COPY_UNCLAIMED_TTL_SECONDS` | int | `7776000` | > 0 | `[stated ans:Q2]` |
| `AIGW_FROZEN_COPY_SWEEP_MAX_ENTRIES` | int | `100000` | ≥ 1 | `[proposed]` |

- No setting turns the sweep or a rule on or off, and no setting holds a date.
  `[stated ans:Q22]` The gateway always arms the periodic trigger. The settings that an earlier
  version of this spec had (`…_SWEEP_ENABLED`, `…_UNCLAIMED_EXPIRY_ENABLED`,
  `…_UNCLAIMED_EXPIRY_FROM`) do not exist.
- This is true for each gateway, also a local or development gateway on SQLite. There, an open
  copy that is idle for 24 hours is abandoned, and a sealed copy expires after 90 days, because
  no scoreboard claims it. `[stated ans:Q22]`
- The 90-day clock of a copy that exists at the release comes from the database, not from a
  setting (`erd.md` §2.1, `retention_from`). `[stated ans:Q24]`
- The idle setting has no lower limit. `[stated ans:Q18]` The operator must keep it above the
  engine deadline of 16 hours
  `[existing apps/screamingface-engine/src/screamingface_engine/config.py:222]`. A lower value
  abandons the copy of a run that is in progress; the capture of that run then stops, and its
  result reports a partial capture. The time of one model call (1800 seconds,
  `[existing apps/screamingface-engine/url4.toml:56]`) is not the limit, because a run can have
  many calls with no stored entry (a call that streams, or that is too large, stores none).
- At start, the gateway logs the values of these settings. `[proposed]`
- Stack A adds three of the four settings (interval, idle time, purge budget).
  `AIGW_FROZEN_COPY_UNCLAIMED_TTL_SECONDS` is used only by the expiry rule, so C1 adds it:
  the field in `config.py`, the chart value, its limit test and its line in the start log.
  `[proposed]`

### 4.2 Performance and load

- The sweep must not delay live captures. Each mark is one short transaction on one row. Each
  purge chunk is one transaction that deletes at most 500 entries. The sweep waits 200 ms
  between chunks. `[proposed]`
- A mark waits at most 2 seconds for the row lock (`lock_timeout`), then skips (S10).
  `[proposed]`
- Measured in production on 2026-11-16: one chunk of 500 entries took 0.8 to 2.2 seconds when
  the database was quiet (about 230 to 600 entries each second). One run with the default
  budget of 100 000 entries thus needs about 3 to 7 minutes. The abandoned copies get about
  45 000 new entries each day at the current rate. `[implied]`
- A purge that becomes slow stops by itself (S24). `[proposed]`
- The rules read the current time from the database. `[proposed]`

### 4.3 What the deletion does to the disk

- A delete in Postgres does not give disk space back to the operating system. After
  autovacuum, the space is free for new rows of the same table. `[implied]`
- Azure Database for PostgreSQL cannot reduce the provisioned storage. Thus the result of the
  sweep is that the table stops growing for some weeks and then grows slower. The size on disk
  does not go down. Do not run `VACUUM FULL`: it locks the table and gives no benefit here.
  `[implied]`
- A large purge writes WAL and starts the automatic vacuum, which uses the same disk. The
  budget, the pause and the stop of S24 spread the load over time. `[proposed]`

### 4.4 Observability

- Each run writes one log record at INFO with: the trigger (periodic or command), and
  for each rule the copies marked and skipped, the entries purged, the copies that still have
  entries, and the cause if the purge stopped early. Counts only. `[stated ans:Q16]`
- A run that fails writes one record at ERROR with the exception type. `[proposed]`
- This PRD adds no metric, no endpoint and no alert. `[stated ans:Q6]`

### 4.5 Security

- The command runs in the gateway pod with the gateway's own database access. It adds no
  network surface. `[proposed]`
- The dry-run document contains account names (email addresses). It goes to the operator's
  terminal only. The log record of §4.4 has counts only. `[stated ans:Q16]`
- Stored entries are plaintext requests and responses. The deletion removes them from the
  table. Backups keep them until the backup retention of the server ends. `[implied]`

## 5. Out of scope

- A change in the engine to close a copy at once after a cancel or a kill. `[stated ans:Q13]`
- A quota for each account. `[stated ans:Q2]`
- Metrics, endpoints and alerts for storage. `[stated ans:Q6]`
- The request cache table. `[stated ans:Q1]`
- Deletion of swept rows (tombstones). `[stated ans:Q12]`
- A move of sealed copies to object storage, and compression. `[stated ans:Q4]`

## 6. Open questions

None. All product decisions and the main engineering decisions are in the interview ledger
(`00-overview.md` §5). The items still tagged `[proposed]` are implementation details.

## 7. TDD plan (RED → GREEN → REFACTOR)

**Order:** core-out. First the idle rule and the purge as pure store methods (unit, SQLite),
then the races (integration, Postgres), then the command, then the periodic trigger. The expiry
rule and migration 0019 come last, in pull request C1. The tests with the highest
risk (loss of data that must stay) come first.

**Rules.** Write the test first and see it fail for the right reason. Then write the smallest
change that makes it pass. Refactor only when all tests pass. One behavior for each test.

Test files: `apps/aigateway/tests/unit/test_frozen_copy_sweep.py`,
`apps/aigateway/tests/unit/test_frozen_copy_sweep_cli.py`,
`apps/aigateway/tests/integration/test_frozen_copy_sweep_postgres.py` (marker `needs_postgres`
`[existing apps/aigateway/pyproject.toml:56]`). Fixtures: `seed_copy` and `account_id_of`
`[existing apps/aigateway/tests/unit/test_frozen_copy_support.py:60-80]`.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| CH-1 | CHAR: a capture write to a sealed copy is refused | unit | `[existing store.py:171]` | — | passes today (`test_capture_after_seal_is_refused`) |
| CH-2 | CHAR: a repeat seal returns the sealed copy unchanged | unit | `[existing store.py:135]` | — | passes today |
| S-1 | a claimed sealed copy keeps status and entries after a sweep at any age (S4) | unit | `[stated ans:Q2]` | H×M | the expiry query filters `claimed_at IS NULL`. Write this test after S-6: before the expiry rule exists, it cannot fail |
| S-2 | an open copy with an entry 10 minutes ago stays open at age 40 h (S2) | unit | `[stated ans:Q5]` | H×M | `idle_since` from the entry with `seq = entry_seq` |
| S-4 | a copy with `retention_from` set expires at `retention_from + ttl`, not at `sealed_at + ttl`; a copy with `retention_from IS NULL` expires at `sealed_at + ttl` (S5) | unit | `[stated ans:Q24]` | H×M | `COALESCE(retention_from, sealed_at)` |
| S-5 | an idle open copy becomes `abandoned`, then has no entry and `purged_at` set; its row stays (S1) | unit | `[stated ans:Q5]` | M×H | mark, then chunked delete |
| S-6 | an unclaimed sealed copy past its period becomes `expired` and is purged (S3) | unit | `[stated ans:Q2]` | M×H | same path as S-5 with the expiry rule |
| S-7 | the status is set before the first entry is deleted (I3) | unit | `[proposed]` | H×L | a store that fails on the first delete: the status is already final |
| S-8 | a failed purge leaves `purged_at NULL`, and the next run completes it (S9) | unit | `[implied]` | M×M | purge selects swept copies with `purged_at IS NULL` |
| S-9 | a seal by the owner of an `abandoned` copy, and of an `expired` copy, answers 410 and changes nothing; a seal by another account answers 404 (S19) | unit | `[implied]` | M×L | seal only when `status == open`; keep the owner filter first |
| S-10 | an open copy with no entry is abandoned and purged in one run (S16) | unit | `[implied]` | M×M | zero entries → set `purged_at` in the mark transaction |
| S-11 | the purge stops at the budget, and the next run continues with the copy marked first (S17) | unit | `[proposed]` | M×H | count deleted rows; order by `swept_at` |
| S-12 | a second run changes nothing on a purged copy (S20) | unit | `[implied]` | L×M | idempotent queries |
| S-13 | Postgres: with the row lock of an idle open copy held by a writer that then inserts an entry, the mark that waited leaves the copy `open` (S13) | integration | `[proposed]` | H×L | evaluate the rule again under `select_for_update` |
| S-14 | Postgres: with the row lock of an expiry candidate held by a claim that then commits, the mark that waited leaves the copy `sealed` with its entries (S12) | integration | `[proposed]` | H×L | same lock; the mark checks `claimed_at` under the lock. The test calls the claim store method of B1 (C1 comes after B1) |
| S-15 | Postgres: a mark skips a copy whose row lock is held for more than 2 s (S10) | integration | `[proposed]` | M×L | `SET LOCAL lock_timeout` |
| S-16 | Postgres: two purges of one copy at the same time delete each entry one time and end with no error; when purge A holds the last rows and then rolls back, purge B does not set `purged_at` (S18) | integration | `[proposed]` | M×M | `FOR UPDATE SKIP LOCKED` in the chunk query; `NOT EXISTS` guard in the `purged_at` statement |
| S-17 | the command with no argument changes no row and prints the evaluation time, the counts for each rule and each account, and the candidates (S7) | unit | `[proposed]` | H×M | dry run is the default |
| S-21 | `--run` with `--cutoff` is refused with status 2; a dry run accepts a future `--cutoff` and evaluates the rules at that time (S21) | unit | `[proposed]` | L×M | argument check |
| S-22 | the gateway refuses to start when the interval, the idle time or the purge budget is outside its limit, and names the setting (S22) | unit | `[proposed]` | M×L | field limits in `Settings`; the fourth setting comes in C1 (S-37) |
| S-23 | the periodic trigger runs one time after the start delay, then one time for each interval, and not while a run is in progress (S23) | unit | `[proposed]` | M×M | loop with `now`, `sleep` and delay bound in the constructor; the test builds the trigger with fakes (`contracts.md` K7) |
| S-24 | the lifespan always arms the trigger, with no setting that can stop it, and stops it at shutdown (S27) | unit | `[stated ans:Q22]` | M×L | wire in `main.py` next to the snapshot scheduler, with no condition; the test reads `app.state.frozen_copy_sweep_trigger` |
| S-25 | the run log record has counts and no account name (§4.4, §4.5) | unit | `[stated ans:Q16]` | M×L | build the record from the totals |
| S-27 | an open copy with `entry_seq > 0` and no entry with that `seq` is skipped with `newest entry not found` | unit | `[proposed]` | L×L | no fallback to the age of the copy |
| S-28 | migration 0018: three columns, index, downgrade, silent autodetector | unit | `[proposed]` | M×L | see `erd.md` §5 |
| S-29 | the purge stops when the mean time of the last 10 chunks is above 5 s, and reports the cause (S24) | unit | `[proposed]` | M×H | injected clock around each chunk |
| S-31 | Postgres: with the row lock of an idle open copy held by a seal that then commits, the mark that waited leaves the copy `sealed` with its entries (S25) | integration | `[proposed]` | H×L | the idle branch checks `status = open` under the lock |
| S-32 | at start, the gateway logs the values of the sweep settings (§4.1) | unit | `[proposed]` | M×L | one log record in the lifespan; three settings in A3, and C1 adds the fourth (S-37) |
| S-33 | migration 0019: the column `retention_from`; each row that is `sealed` gets one value, and each other row keeps `NULL`; the value read back through the model is timezone-aware and compares correctly with `sealed_at`; downgrade; silent autodetector (S5) | unit | `[stated ans:Q24]` | H×M | a `RunPython` step that passes one UTC time as a parameter of one `UPDATE`; see `erd.md` §5 |
| S-34 | the command with `--run` marks and purges in one pass, with the same result as one periodic run; `--max-entries` sets the budget (S26) | unit | `[proposed]` | M×M | the command and the trigger call one function |
| S-35 | a dry run lists an unclaimed sealed copy for the rule `expired` when its period ended, also with a future `--cutoff`, and changes no row (S7, S21) | unit | `[proposed]` | M×M | the dry run calls the rule code of C1 |
| S-36 | Postgres: two runs mark the same idle copy at the same time: one marks it, the other skips it, and `entries` and `swept_at` are written one time (S18) | integration | `[proposed]` | M×L | the second mark reads the status under the row lock and skips a copy that is not `open` |
| S-37 | `AIGW_FROZEN_COPY_UNCLAIMED_TTL_SECONDS`: the gateway refuses to start with a value of 0 or less; the expiry rule uses the value; the start log shows it (§4.1) | unit | `[stated ans:Q2]` | M×L | C1 adds the setting to `Settings`, the chart and the start log |

Ids that are not used: S-3, S-18, S-19, S-20, S-26 and S-30. They tested the two switches and
the approved list `[stated ans:Q22]` `[stated ans:Q23]`.

Pull requests: A1 has CH-1, CH-2, S-9, S-28. A2 has S-2, S-5, S-7, S-8, S-10 to S-13, S-15 to
S-17, S-21, S-22, S-27, S-29, S-31, S-34, S-36. A3 has S-23 to S-25, S-32. C1 has S-1, S-4, S-6,
S-14, S-33, S-35, S-37. In C1, write S-6 before S-1.

**How to write the race tests (S-13 to S-16, S-31, S-36).** Use two database connections and a fixed order:
connection A takes the lock and waits on an event; the test starts B; the test lets A commit;
the test reads the result. A test that only starts two tasks at the same time passes even when
the lock is not there.

In S-13, S-14, S-31 and S-36, A must commit before the lock timeout of B ends (2 s), or the test must set a
longer timeout for B. The test must assert that B reported the cause `rule no longer true`. If B
ends with `lock timeout`, the copy also keeps its state, so the test would pass with no check
under the lock. S-15 is the one test in which B must end with `lock timeout`.

### 7.1 Implementation notes

- **Where the code goes.** A new module `core/frozen_copy/sweep.py` holds the rules and the
  purge. The command is `aigateway/frozen_copy_sweep.py` (run with `python -m`). The periodic
  trigger is a small class next to the sweep module. `[proposed]`
- **Exemplars.**
  - Row lock and transaction: `FrozenCopyStore.seal`
    `[existing core/frozen_copy/store.py:127-141]`.
  - Clock and sleep that are bound in the constructor, start and stop of one owned task:
    `CacheSnapshotScheduler` `[existing core/snapshot_scheduler.py:74-114]`. The trigger must
    not look up `asyncio.sleep` at call time, and the lifespan puts it on
    `app.state.frozen_copy_sweep_trigger` (`contracts.md` K7). Its cron code is fixed to one weekly time
    and cannot be used again; the interval loop is new code.
  - Arm and stop in the lifespan: `[existing main.py:224-244]`.
  - A statement that is different for Postgres and SQLite: `record_hit_metadata`
    `[existing core/request_cache/store.py:124-141]`. The chunk delete with `SKIP LOCKED` and
    the `lock_timeout` need this split.
  - Operator command with a dry run as the default (argument and exit style only):
    `apps/scoreboard/src/scoreboard/delete_scores.py`
    `[existing apps/scoreboard/src/scoreboard/delete_scores.py:155-223]`. The gateway has no
    such command today.
- **One function does a pass.** The periodic trigger and `--run` call it. The dry run calls the
  same rule queries and stops before the first write.
- **Do not** add a setting that turns the sweep or a rule on or off, and do not add a list, a
  digest or an approval step to the command. `[stated ans:Q22]` `[stated ans:Q23]`
- **The expiry rule is not in stack A.** A2 builds the pass so that C1 adds one rule to it.
- **Do not** load the entries of a copy into memory. Delete by id in chunks with one statement.
  On 2026-10-29 a bulk read in the serving pod caused an out-of-memory kill of the gateway.
- **Do not** add a column for the time of the last entry, and do not use the age of the copy as
  the idle time (`erd.md` §2.1, §2.4).
- **SQLite.** `select_for_update` does nothing on SQLite. The unit tests prove the rules; the
  integration tests prove the locks.
