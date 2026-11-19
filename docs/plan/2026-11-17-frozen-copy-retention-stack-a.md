# Plan: frozen copy retention, stack A (abandoned copies)

- Spec: `docs/spec/2026-11-16-frozen-copy-retention/` (owner approved 2026-11-17). Read
  `00-overview.md` §2, `erd.md` §2 and §5, `prd/copy-sweep.md`, `contracts.md` K1, K2, K6, K7, K8.
- Ledger: `docs/work/2026-11-17-frozen-copy-retention-stack-a.md` (make it when the code starts).
- Issue: `OME-1947`. Base: `origin/main` at `e9db97cfb`. Paths are under `apps/aigateway/` unless
  they start with `docs/` or `.claude/`. Scope: pull requests A1, A2, A3 only.
- Order inside each unit: RED tests first, then code, then gates. Tests are append-only: never
  edit or delete an existing test. If an existing test fails because of a change below, STOP and
  report it (file, test name, failure). One exception is known and needs the owner's approval
  record before A1 starts: see A1.0.
- Commits, one for each pull request, each with `(OME-1947)` at the end:
  `feat(aigateway): add frozen copy retention states and migration 0018`,
  `feat(aigateway): sweep abandoned frozen copies`,
  `feat(aigateway): run the frozen copy sweep on a periodic trigger`.
- Gates for each commit (`.claude/sdlc.local.md:40-45`), run in `apps/aigateway`: `uv run ruff
  check`, `uv run ruff format --check`, `uv run pyright`, `uv run python
  scripts/check_no_enterprise.py`, `uv run pytest --cov=aigateway --cov-fail-under=80 -q`.
- Postgres lane (CI only, `.github/workflows/aigateway-tests.yml:88-91`): run
  `AIGW_TEST_PG=1 uv run pytest -m needs_postgres` with Docker for A1 and A2.

## Order of work
1. A1: A1.0 → RED S-28 → model and migration → RED S-9 → seal change → CH-1 and CH-2 confirmed
   green → gates → commit.
2. A2, risk first (`prd/copy-sweep.md` §7): S-2, S-5, S-7, S-8, S-10, S-11, S-12, S-27, S-29 →
   S-13, S-31, S-36, S-15, S-16 (Postgres) → S-22 → S-17, S-21, S-34 → gates → commit.
3. A3: S-23 → S-24 → S-25 → S-32 → chart → runbook → gates → commit.

## A1 — migration 0018, the two new states, seal only an open copy
### A1.0 Approval record for one existing test (do this first)
- `tests/unit/test_frozen_copy_migration.py:48-60`
  (`test_0014_creates_both_tables_with_the_design_columns`) migrates to the newest migration and
  asserts that the column set of `frozen_copies` is **equal** to the eight columns of 0014.
  Migration 0018 adds three columns, so this test fails.
- Necessary change, assertion only: `{…eight names…} <= set(copies)`. Nothing else changes.
- Before the edit, get the owner's record `.claude/test-change-approvals/OME-1947.json` (shape:
  `.claude/test-change-approvals/OME-939.json`). No record → STOP.
- `test_0014_downgrade_drops_both_tables` (`:117-127`) now also runs the reverse of 0018 on
  SQLite. It must stay green with no edit.

### A1.1 Model (`src/aigateway/core/frozen_copy/models.py`)
- After `STATUS_SEALED` (`:22`): `STATUS_ABANDONED = "abandoned"`, `STATUS_EXPIRED = "expired"`
  (stack A never writes `expired`; it is for stack C).
- In `FrozenCopy` after `sealed_at` (`:45`): `claimed_at`, `swept_at`, `purged_at`, each
  `fields.DatetimeField(null=True)`, with one comment line from `erd.md` §2.1.
- In `FrozenCopy.Meta` (`:26-27`): `indexes = (("status", "purged_at"),)`.
- Do not change the module docstring (F1, F2): that text is pull request C3.

### A1.2 Migration `src/aigateway/migrations/0018_frozen_copy_retention.py`
- `dependencies = [("models", "0017_drop_migration_note")]`.
- Generate with `uv run tortoise -c aigateway.db.TORTOISE_CONFIG makemigrations -n
  frozen_copy_retention models`, then edit. Remove the `AlterField` on `OAuthConnection.account`
  (`migrations/0015_cache_entry_write_order.py:11-15`).
- Operations in this order: `ops.RunPython(code=_bound_lock_wait,
  reverse_code=ops.RunPython.noop)` (copy `_LOCK_TIMEOUT_MS`, `_SET_LOCK_TIMEOUT_SQL`,
  `_dialect_of`, `_bound_lock_wait` from `0017_drop_migration_note.py:35-51`); three column adds;
  `ops.AddIndex(model_name="FrozenCopy", index=Index(fields=["status", "purged_at"]))` (exemplar
  `0015_cache_entry_write_order.py:28-33`). The index is last, so the downgrade drops it before
  `purged_at`.
- **Column add with a `DROP COLUMN` reverse** (`erd.md` §5). Subclass `AddField`, as
  `ForgetMigrationNote` subclasses `RemoveField` (`0016_forget_migration_note.py:24-46`):
  ```python
  class _AddColumn(ops.AddField):
      """`AddField` whose downgrade is one `ALTER TABLE … DROP COLUMN` (0017: `RemoveField`
      rebuilds the table on SQLite and loses its indexes)."""

      async def database_backward(self, app_label, old_state, new_state, state_editor=None):
          if state_editor is not None:
              await state_editor._run_sql(  # noqa: SLF001
                  f"ALTER TABLE frozen_copies DROP COLUMN {self.name}"
              )
  ```
  Use the typed signature of `0016:39-46`, and the `AddField(...)` arguments that
  `makemigrations` wrote.
- Docstring as `0015` (UPGRADE, DOWNGRADE, AUTHORING NOTE); DOWNGRADE text from `erd.md` §5.1.
- **S-28**, new file `tests/unit/test_frozen_copy_retention_migration.py` (copy `_tortoise`,
  `migrated`, `_columns`, `_index_columns` from `test_frozen_copy_migration.py:20-41, 86-92`):
  the dependency is 0017; the three columns exist and are nullable; the index
  `(status, purged_at)` exists; after `downgrade models 0017_drop_migration_note` the columns and
  the index are gone, and the account index and the foreign key of `frozen_copies` stay; the
  autodetector proposes no change (copy the script test of `:129-156`).

### A1.3 Seal only an open copy
- `src/aigateway/core/frozen_copy/store.py:135-136`: `if copy.status == STATUS_SEALED:` becomes
  `if copy.status != STATUS_OPEN:` (still `return copy`). The owner filter of `:129` stays
  first. Docstring: a copy that is not open is returned unchanged.
- `src/aigateway/routes/frozen_copies.py`, `seal_frozen_copy` (`:203-211`): after the
  `copy is None` check, `if copy.status in (STATUS_ABANDONED, STATUS_EXPIRED): raise
  _gone(copy.status)`.
- New helper next to `_sealed()` (`:196-200`): `def _gone(state: str) -> HTTPException`, status
  410, detail `{"code": "frozen_copy_expired", "state": state, "message": "the frozen copy was
  swept and its entries were deleted"}` (`contracts.md` K2).
- No change to capture (`store.py:171` already refuses each status that is not `open`), to the
  tool-results route, or to `_sealed_copy` (`routes/frozen_copies.py:94-110`; its 410 is C1).
- **S-9**, new file `tests/unit/test_frozen_copy_retention_states.py` (fixtures `client`,
  `seed_copy`, `account_id_of`, `run_async` from `tests/unit/test_frozen_copy_support.py:33-80`;
  set a status with `FrozenCopy.filter(id=…).update(status=…)` through `run_async`): an owner
  seal of an `abandoned` copy and of an `expired` copy → 410 with `state`, row unchanged; a seal
  by another account → 404 `frozen_copy_not_found`.
- **CH-1**, **CH-2**: existing tests pin them (`tests/unit/test_frozen_copy_routes.py:212`, and
  the repeat-seal test in `tests/unit/test_frozen_copy_store.py`). Name them in the ledger.

## A2 — the idle rule, the purge, the command
### A2.1 Settings (`src/aigateway/config.py`, after `frozen_copy_max_entry_bytes`, `:199-205`)
```python
frozen_copy_sweep_interval_seconds: int = Field(
    default=3600, ge=60, validation_alias="AIGW_FROZEN_COPY_SWEEP_INTERVAL_SECONDS"
)
frozen_copy_open_idle_seconds: int = Field(
    default=86_400, gt=0, validation_alias="AIGW_FROZEN_COPY_OPEN_IDLE_SECONDS"
)
frozen_copy_sweep_max_entries: int = Field(
    default=100_000, ge=1, validation_alias="AIGW_FROZEN_COPY_SWEEP_MAX_ENTRIES"
)
```

- Exemplar: `request_cache_default_ttl_seconds` (`:165-167`). One comment block above the three
  (no switch exists; keep the idle time above the engine deadline of 16 hours).
- All three fields go in A2, because test S-22 (A2) names the interval. A3 only uses it. Do not
  add `…_UNCLAIMED_TTL_SECONDS` (C1), and do not add an enable flag.
- **S-22**, `tests/unit/test_frozen_copy_sweep_settings.py`: `Settings(...)` raises a validation
  error that names the field for interval 59, idle 0 and budget 0.

### A2.2 Sweep module `src/aigateway/core/frozen_copy/sweep.py` (new)
It imports `tortoise`, `.models`, `aigateway.core.auth.models` (account name) and
`aigateway.config`. It does not import `routes`, `main` or `plugins`.

```python
MarkOutcome = Literal["marked", "rule no longer true", "lock timeout", "newest entry not found"]

@dataclass(frozen=True)
class SweepCandidate:                # rule is "abandoned" in stack A; entries = entry_seq
    rule: str; copy_id: UUID; account_id: UUID; entries: int   # one field for each line

class SweepRule(Protocol):           # the shape that C1 extends with an expiry rule
    name: str                        # the status that the rule sets
    async def candidates(self, at: datetime) -> list[SweepCandidate]: ...
    async def mark(self, copy_id: UUID, at: datetime) -> MarkOutcome: ...

class IdleRule:                      # name = STATUS_ABANDONED
    def __init__(self, *, open_idle_seconds: int, lock_timeout_ms: int = 2000) -> None: ...

@dataclass
class SweepReport:                   # one field for each line in the code
    trigger: str                     # "periodic" | "command"
    marked: dict[str, int]; skipped: dict[str, dict[str, int]]   # rule -> copies; rule -> cause -> copies
    entries_purged: int = 0; copies_completed: int = 0; copies_with_entries: int = 0
    purge_stopped: str | None = None                             # "budget" | "slow" | None

class FrozenCopySweep:
    def __init__(self, rules: Sequence[SweepRule], *, max_entries: int, chunk_size: int = 500,
                 chunk_pause_s: float = 0.2, slow_chunk_s: float = 5.0, slow_window: int = 10,
                 sleep: Sleep | None = None, clock: Callable[[], float] | None = None) -> None: ...
    async def dry_run(self, at: datetime | None = None) -> dict[str, Any]: ...
    async def run_pass(self, *, trigger: str, max_entries: int | None = None) -> SweepReport: ...
    async def purge_chunk(self, copy_id: UUID) -> int: ...
    async def finish_purge(self, copy_id: UUID, at: datetime) -> bool: ...

async def database_now() -> datetime: ...      # timezone-aware UTC
def build_frozen_copy_sweep(settings: Settings) -> FrozenCopySweep: ...
```

- **`database_now`**: Postgres `SELECT now()`; SQLite `SELECT
  strftime('%Y-%m-%dT%H:%M:%fZ','now')`, parsed to an aware UTC `datetime`. Dialect switch as
  `record_hit_metadata` (`core/request_cache/store.py:124-126`). Compare model datetimes through
  one helper `_utc(value)` that adds UTC to a naive value (`db.py:16-33` sets no `use_tz`).
- **`IdleRule.candidates(at)`**: `FrozenCopy.filter(status=STATUS_OPEN).values("id",
  "account_id", "entry_seq", "created_at")`. For each: `idle_since` is the `created_at` of the
  copy if `entry_seq == 0`, else `FrozenCopyEntry.filter(frozen_copy_id=id,
  seq=entry_seq).values_list("created_at", flat=True)` (one read on the unique index,
  `models.py:59`). Candidate when `at - idle_since >= open_idle_seconds`. A copy with
  `entry_seq > 0` and no such entry is not a candidate here; `mark` reports it.
- **`IdleRule.mark(copy_id, at)`**, one transaction (`contracts.md` K8; exemplar
  `store.py:127-142`): `async with in_transaction() as conn`; on Postgres first
  `SET LOCAL lock_timeout = '2000ms'`; then
  `FrozenCopy.filter(id=copy_id).select_for_update().first()`. `None` or
  `status != STATUS_OPEN` → `"rule no longer true"`. Read the newest entry time again: missing
  with `entry_seq > 0` → `"newest entry not found"`; idle condition false →
  `"rule no longer true"`. Else set `status = STATUS_ABANDONED`, `swept_at = at`,
  `entries = entry_seq`, and `purged_at = at` when `entry_seq == 0`
  (`save(update_fields=[…])`) → `"marked"`. A Postgres lock timeout (SQLSTATE `55P03`, raised as
  `tortoise.exceptions.OperationalError`) → `"lock timeout"`; catch it outside the transaction
  block. Each other error propagates.
- **`purge_chunk(copy_id)`**, one transaction. Postgres, through
  `FrozenCopyEntry._meta.db.execute_query`: `DELETE FROM frozen_copy_entries WHERE id IN (SELECT
  id FROM frozen_copy_entries WHERE frozen_copy_id = $1 LIMIT $2 FOR UPDATE SKIP LOCKED)`; return
  the row count. SQLite: read `chunk_size` ids with `values_list("id", flat=True)`, then
  `FrozenCopyEntry.filter(id__in=ids).delete()`. Never select `request_json` or `response_json`.
- **`finish_purge(copy_id, at)`**. Postgres, one statement: `UPDATE frozen_copies SET purged_at =
  $1 WHERE id = $2 AND purged_at IS NULL AND NOT EXISTS (SELECT 1 FROM frozen_copy_entries WHERE
  frozen_copy_id = $2)`; return `rowcount == 1`. SQLite: in one transaction, an `exists()` check,
  then the filtered `update(purged_at=at)`. The time is a parameter, not `now()` in the
  statement, so both dialects store the same format.
- **`run_pass`**: `at = await database_now()`. For each rule: `candidates(at)`, then `mark` for
  each; count the outcomes. Purge: copies with `swept_at IS NOT NULL` and `purged_at IS NULL`,
  ordered by `swept_at`, `id`; for each, loop `purge_chunk` until it returns 0, then
  `finish_purge`; after each chunk `await self._sleep(chunk_pause_s)`. Stop when the deleted
  count reaches the budget (`"budget"`), or when the mean time of the last `slow_window` chunks
  is above `slow_chunk_s` (`"slow"`, measured with `self._clock`). Write one INFO record from the
  report: counts only, no account name, no copy id (`prd/copy-sweep.md` §4.4). On an exception:
  one ERROR record with the exception type, then raise.
- **`dry_run(at)`**: `at = at or await database_now()`; the candidates of each rule; the document
  of `contracts.md` K6. Account names: one read, `Account.filter(id__in=…).values("id",
  "username")`. Always emit the key `expired` with zero counts. It writes nothing.
- **`build_frozen_copy_sweep(settings)`**: one `IdleRule` and `max_entries`, from the settings.
- Bind `sleep` and `clock` in the constructor (`sleep or asyncio.sleep`, `clock or
  time.monotonic`), as `core/snapshot_scheduler.py:85-86`; type `Sleep` from `:36` of that file.
  `core/frozen_copy/__init__.py` exports nothing today: import from the module.
- Do not: add methods to `FrozenCopyStore` (the request-path store); add a global lock or a
  last-entry-time column; load entry bodies; add a rule for `sealed` copies (C1).

### A2.3 Unit tests `tests/unit/test_frozen_copy_sweep.py` (SQLite)
Fixtures as in A1.3. Make an old entry with `FrozenCopyEntry.filter(…).update(created_at=…)`
through `run_async`. Build the sweep directly with a fake `sleep` and a fake `clock`.

| Test | Assertion |
|---|---|
| S-2 | open copy, age 40 h, entry 10 minutes ago → stays `open` |
| S-5 | idle open copy → `abandoned`, `swept_at` set, `entries == entry_seq`; then no entry, `purged_at` set, row present |
| S-7 | `purge_chunk` patched to raise on its first call → the status is already `abandoned` |
| S-8 | a failed purge leaves `purged_at IS NULL`; the next `run_pass` completes it |
| S-10 | open copy with `entry_seq == 0`, made 25 h ago → `abandoned`, and the mark sets `purged_at` |
| S-11 | budget 3, 5 entries in 2 copies → `"budget"`; the next pass continues with the copy marked first |
| S-12 | a second pass changes nothing on a purged copy (`swept_at`, `purged_at` equal) |
| S-27 | `entry_seq > 0` and no entry with that `seq` → `"newest entry not found"`, still `open` |
| S-29 | the fake clock gives 6 s for each chunk → `"slow"` after 10 chunks |

### A2.4 Postgres tests `tests/integration/test_frozen_copy_sweep_postgres.py`
- `pytestmark = pytest.mark.needs_postgres`. Copy the fixtures `postgres_database_url` and
  `pg_client` from `tests/integration/test_lifecycle_postgres_races.py:51-97` (skip when
  `AIGW_TEST_PG != "1"`; container `postgres:16-alpine`; `tortoise migrate` in a subprocess).
- Fixed order, two connections on the app loop (`run_async`): task A opens `in_transaction()`,
  takes `select_for_update()` on the copy, sets an `asyncio.Event`, waits on a second event,
  then writes and commits. The test starts B after the first event, releases A, and reads the
  result of B. Assert the cause string of B, not only the final state.
- **S-13** A inserts an entry → B `"rule no longer true"`, copy `open`. **S-31** A seals → B
  `"rule no longer true"`, copy `sealed` with its entries. **S-36** A is a second `mark` → one
  `"marked"`, one `"rule no longer true"`, `swept_at` written one time. **S-15** A holds the lock
  for more than 2 s → B `"lock timeout"`. **S-16** two purges: each entry is deleted one time;
  when A holds the last rows and rolls back, `finish_purge` of B returns `False`.

### A2.5 Command `src/aigateway/frozen_copy_sweep.py` (new; `python -m aigateway.frozen_copy_sweep`)
- `def main(argv: Sequence[str] | None = None) -> int` with `argparse`; last lines
  `if __name__ == "__main__": raise SystemExit(main())`.
- Arguments: `--cutoff` (ISO time; refuse a value with no zone), `--run`, `--max-entries` (int
  ≥ 1, only with `--run`). `--run` with `--cutoff` → `parser.error(...)`. Exit status: 0 done;
  2 bad arguments; 1 for an exception (print its type to stderr). No `--execute`, list or digest.
- Body: `settings = Settings()`; `asyncio.run(_amain(args, settings))`. `_amain`:
  `await init_db(settings.database_url.get_secret_value())` (`db.py:42-43`, as
  `main.py:189-190`); `try:` build with `build_frozen_copy_sweep(settings)`; dry run →
  `print(json.dumps(await sweep.dry_run(cutoff)))`; `--run` → `run_pass(trigger="command",
  max_entries=args.max_entries)`, printed as JSON (`dataclasses.asdict`); `finally: await
  close_db()`.
- Tests `tests/unit/test_frozen_copy_sweep_cli.py`: call `_amain` through `run_async` on the
  database of the `client` fixture (patch `init_db` and `close_db` of the module to no-ops), and
  `main([...])` for the argument errors. **S-17** no argument → no row changes; the document
  has `evaluated_at`, `rules`, `by_account`, `candidates`. **S-21** `--run --cutoff …` → exit 2;
  a future `--cutoff` lists a copy that is idle at that time. **S-34** `--run` gives the same
  final rows as one `run_pass`; `--max-entries 1` stops with `"budget"`.

## A3 — the periodic trigger, the chart values, the runbook
### A3.1 Trigger `src/aigateway/core/frozen_copy/sweep_trigger.py` (new)
```python
class FrozenCopySweepTrigger:
    def __init__(self, run: Callable[[], Awaitable[object]], *, interval_s: float,
                 start_delay_s: Callable[[], float] | None = None,
                 now: Callable[[], datetime] | None = None, sleep: Sleep | None = None) -> None: ...
    def start(self) -> None: ...
    async def stop(self) -> None: ...
    # read-only properties: busy -> bool, runs -> int

def build_sweep_trigger(settings: Settings) -> FrozenCopySweepTrigger: ...
```

- Copy `start`, `stop` and the bound `now` and `sleep` from `CacheSnapshotScheduler`
  (`core/snapshot_scheduler.py:84-114`). Task name `"frozen-copy-sweep"`.
- Loop: `await self._sleep(self._start_delay_s())` (default `lambda: random.uniform(60.0,
  300.0)`); then forever: set `busy`; `await self._run()` inside `try/except Exception` (one
  ERROR record with the exception type; the loop never ends); clear `busy`; add 1 to `runs`;
  `await self._sleep(interval_s)`. One loop, so two runs never overlap.
- `build_sweep_trigger`: `sweep = build_frozen_copy_sweep(settings)`; `run = lambda:
  sweep.run_pass(trigger="periodic")`; `interval_s = settings.frozen_copy_sweep_interval_seconds`.
- **S-23**, `tests/unit/test_frozen_copy_sweep_trigger.py`: a fake `sleep` records each delay
  and blocks on an event. Assert: the first delay is the injected start delay; then one run for
  each interval; a run that raises does not stop the next one. **S-25** (file of A2.3): the INFO
  record of `run_pass` has the counts and no account name (`caplog`).

### A3.2 Lifespan wiring (`src/aigateway/main.py`)
- Import `build_sweep_trigger` next to `build_snapshot_scheduler` (`:47`).
- After the snapshot block (`:222-233`), before `yield` (`:235`), with **no condition**:
  ```python
  trigger = getattr(app.state, "frozen_copy_sweep_trigger", None)
  if trigger is None:
      trigger = build_sweep_trigger(app.state.settings)
      app.state.frozen_copy_sweep_trigger = trigger
  trigger.start()
  logger.info("frozen copy sweep armed (interval_s=%s, open_idle_s=%s, max_entries=%s)", …)
  ```
  The `getattr` lets a test put a fake trigger on `app.state` before the lifespan starts.
- Stop: in the `finally` chain (`:239-246`), before the snapshot scheduler, in its own
  `try/finally`, so that each later step still runs.
- **S-24**, `tests/unit/test_frozen_copy_sweep_lifespan.py`: with the `client` fixture,
  `app.state.frozen_copy_sweep_trigger` exists and its task is live; after the client exits the
  task is done; no name in `Settings.model_fields` contains `sweep_enabled`. **S-32**: the start
  log record has the three values (`caplog`).

### A3.3 Chart (`charts/aigateway/`)
- `values.yaml`, in `config:` (`:40`) after `requestCache` (`:146-147`):
  ```yaml
  # The frozen copy retention sweep (OME-1947). It has no switch: it runs in each gateway.
  frozenCopySweep:
    intervalSeconds: 3600
    openIdleSeconds: 86400     # keep above the engine run deadline (16 hours)
    maxEntries: 100000         # purge budget of one run
  ```
- `templates/configmap.yaml`, after `AIGW_REQUEST_CACHE_ENABLED` (`:46`), three lines in the same
  form: `AIGW_FROZEN_COPY_SWEEP_INTERVAL_SECONDS`, `AIGW_FROZEN_COPY_OPEN_IDLE_SECONDS`,
  `AIGW_FROZEN_COPY_SWEEP_MAX_ENTRIES`, each `{{ .Values.config.frozenCopySweep.<key> | quote }}`.
- `values-prod.yaml`: no change. `README.md`: one line. `tests/unit/test_chart_render_*.py` stay green.

### A3.4 Runbook (`DEPLOYMENT.md`)
- New section `## Frozen copy retention sweep (OME-1947)` before `## Operations Notes` (`:800`):
  what the sweep does, with no switch; the three settings; the command; the run log record; the
  size on disk does not go down (`prd/copy-sweep.md` §4.3); the rollback notes of `erd.md` §5.1;
  the advice of `test-plan.md` §5.4. Point to the spec; do not copy the SQL of the checks.

## What stack A leaves ready for stacks B and C
- **B1** uses the column `claimed_at` (0018) and the row-lock pattern of `store.seal`. Stack A
  writes no code that reads or sets `claimed_at`.
- **C1** uses `STATUS_EXPIRED` and the 410 helper `_gone` (A1.3). It adds one `SweepRule` class
  (name `STATUS_EXPIRED`) to the list in `build_frozen_copy_sweep`; the purge, the dry-run
  document, the command and the trigger need no change. C1 also adds migration 0019 (after
  `0018_frozen_copy_retention`) and `AIGW_FROZEN_COPY_UNCLAIMED_TTL_SECONDS` (S-37).

## Release notes for the operator
The release of stack A is `00-overview.md` §7.1 step 1, and its checks are `test-plan.md` §5.1.
No approval step exists: the first run marks each idle open copy 1 to 5 minutes after the start.

## Risks during the build
1. **An existing migration test must change** (A1.0). No approval record → A1 cannot start.
2. **Each lifespan now starts a background task.** 24 unit test files build a `TestClient`. The
   first run is 60 seconds or more after the start, so no test reaches it; `stop()` must cancel
   a task in its first sleep. Some tests patch the global `asyncio.sleep`: bind `sleep` early.
3. **`AddField.database_backward`.** `_AddColumn` depends on Tortoise 1.1.8 (`uv.lock`). Confirm
   the signature against `0016:39-46`. S-28 and the 0014 downgrade test prove it on SQLite.
4. **Time values.** `TORTOISE_CONFIG` sets no `use_tz`, and SQLite stores text. Compare only
   through `_utc(...)`, and pass each time as a parameter. S-2 and S-5 find a wrong comparison.
5. **The lock timeout error type.** The plan assumes `OperationalError` with SQLSTATE `55P03`.
   If S-15 shows a different type, catch that type, and nothing wider.

## Corrections found during the build (2026-11-17)
The code follows these points. Where a point and the text above disagree, the point is correct.

1. **A1.0:** the test has two assertions that 0018 breaks, not one: the column set, and the list
   of nullable columns of `frozen_copies`. The owner approved both changes; the second check is
   limited to the eight columns of 0014. The record has the two changes.
2. **A1.3:** CH-2 (the repeat seal) is pinned by `tests/unit/test_frozen_copy_routes.py:102`
   (`test_seal_is_owner_only_idempotent_and_counts_entries`), not by a test of the store.
3. **A2.2, lock timeout:** Tortoise 1.1.8 does not convert SQLSTATE `55P03`. `IdleRule.mark`
   catches `asyncpg.exceptions.LockNotAvailableError`, and nothing wider (risk 5).
4. **A2.2, candidates:** a copy with `entry_seq > 0` and no entry with that `seq` IS returned by
   `candidates`, with the skip cause `newest entry not found` (`SweepCandidate.skip`). The run
   counts it and does not call `mark` for it; the dry run does not list it (`erd.md` §2.4).
5. **A2.2, budget:** `purge_chunk(copy_id, *, limit=None)`; a run passes
   `min(chunk_size, remaining budget)`, so a run never deletes more entries than the budget.
   When a chunk uses the budget exactly, the run still calls `finish_purge` for that copy.
6. **A2.2 and A3.1, sleep:** the default `sleep` is bound when the module loads
   (`_ASYNC_SLEEP`), because some tests replace `asyncio.sleep` for all code.
7. **A2.2 and A3.1, failed run:** only `run_pass` writes the ERROR record. The trigger writes a
   DEBUG record, so one failure gives one ERROR record (`prd/copy-sweep.md` §4.4).
8. **A3.1:** the trigger has the read-only properties `task`, `interval_s` and
   `last_started_at` (the reader of the `now` seam of K7), in addition to `busy` and `runs`.
9. **A3.2:** at shutdown the lifespan removes a trigger that it built, so a later lifespan of
   the same app builds a new one from its settings. A trigger that a test put there stays.
10. **A3.3:** the chart is at `apps/aigateway/charts/aigateway/`. Each of the three ConfigMap
    values goes through `int64` before `quote`: Helm writes a number of 1,000,000 or more from a
    values file as `1e+06`, and the gateway refuses that text. New render test:
    `tests/unit/test_chart_render_frozen_copy_sweep.py`.
11. **Tests:** shared helpers are in `tests/unit/test_frozen_copy_sweep_support.py`. Tests build
    `Settings` with `_env_file=None`. The frozen copy fixtures use `authenticated_client`. S-24
    and S-32 build their own `TestClient`, and capture logs with the logger name.
12. **File size:** `main.py` (499 → 527 lines) and `config.py` (489 → 506 lines) were above the
    450-line guide before this work. This work does not refactor them.
13. **Local Postgres lane on Colima:** set
    `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`. CI does not need it.
14. **One pull request.** A1, A2 and A3 are one pull request on branch
    `OME-1947-frozen-copy-retention-stack-a`, with one commit for each (owner decision,
    2026-11-17). The approval record names one branch, and the pre-push check compares each
    pushed branch with `main`, so stacked branches for A2 and A3 fail it.
