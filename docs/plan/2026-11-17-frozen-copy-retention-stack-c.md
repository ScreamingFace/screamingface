# Plan: frozen copy retention, stack C (expiry)

- Spec: `docs/spec/2026-11-16-frozen-copy-retention/` (owner approved 2026-11-17; owner
  decisions Q26 to Q32 of `00-overview.md` §5.4 are in this plan, see the last section). Read
  `00-overview.md` §2 and §7, `erd.md` §2.4, §2.5, §2.7, §5, `contracts.md` K3, K6, K8,
  `prd/expired-copy-replay.md`, `prd/copy-sweep.md` (tests S-1, S-4, S-6, S-14, S-33, S-35, S-37),
  `test-plan.md` §5.3 and §5.4.
- Ledgers, one for each pull request, named by the branch slug (made when the code starts):
  `docs/work/2026-11-17-frozen-copy-expiry.md` (C1),
  `docs/work/2026-11-17-engine-expired-copy-message.md` (C2) and
  `docs/work/2026-11-17-pinned-cache-retention-docs.md` (C3).
- Issue: `OME-1947` (all stacks stay under it, Q26). Base: `origin/main` after the pull
  request of stack A (#1911) and pull request B1 are merged. C1 paths
  are under `apps/aigateway/`. C2 paths are under `apps/screamingface-engine/`. A path that starts
  with `docs/`, `public-docs/`, `.claude/` or `CONTEXT.md` is from the repo root. All line
  references are from the worktree at stack A (branch `OME-1947-frozen-copy-retention-stack-a`).
- Order inside each unit: RED tests first, then code, then gates. Tests are append-only. Two
  existing assertions change in C1. The owner approved them (Q27); C1.0 has the record rules. If
  a different existing test fails, STOP and report it (file, test name, each assertion that
  fails).
- Commits, each with `(OME-1947)` at the end:
  `feat(aigateway): expire sealed frozen copies that no score claims`,
  `feat(screamingface-engine): say when a replayed frozen copy expired`,
  `docs: state the retention rule of the pinned cache`.
- Gates: `uv run .claude/scripts/run_gates.py aigateway` (C1, and C3 for the docstring),
  `uv run .claude/scripts/run_gates.py screamingface-engine` (C2). For `public-docs` (C3; not in
  the card): `npm ci`, `npx oxlint .`, `npx eslint .`, `npm run build`
  (`.github/workflows/public-docs-tests.yml:58-73`).
- Postgres lane for C1: in `apps/aigateway`, `AIGW_TEST_PG=1 uv run pytest -m needs_postgres`. On
  Colima, also set `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`.

## Release note (binding, not enforced by code)
- **Do not merge C1 until steps 3 and 4 of `00-overview.md` §7.1 (checks 3 and 4 of
  `test-plan.md` §5.2) are done in production.** Say so in the C1 pull request body.
- Cause: a merge to `main` puts C1 into the next gateway release. release-please has the
  component `apps/aigateway` (`release-please-config.json:20-26`), and the tag `aigateway-v*`
  starts `.github/workflows/release-aigateway.yml` (`:3-5`). No code holds C1 back.
- Migration 0019 starts the 90-day clock of each sealed copy at the time of the production
  release. A wrong order leaves 90 days in which one start of a scoreboard with a gateway URL
  claims the copies (`test-plan.md` X15).
- C3 is not tied to a release day (Q32). It is merged after C1 is merged, and the docs give no
  date.

## Pull request shape
- **C1, C2 and C3 are three independent pull requests, each cut from `main`.** Do not stack
  them. Cause: C1 changes two existing test assertions. The approval record names one branch, and
  the pre-push hook (`.githooks/pre-push`) compares each pushed branch with the merge base with
  `main`. A branch for C2 or C3 that contains the C1 commits fails the append-only check.
- **Merge gate of C1:** the first point of "Release note". The pull request can be open and
  reviewed before that; it must not be merged.
- C1 needs stack A and B1 on `main` (test S-14 calls `FrozenCopyStore.claim`). C2 needs nothing:
  an engine with C2 and a gateway with no C1 work as today (`prd/expired-copy-replay.md` R6).
- C3 changes one docstring in `apps/aigateway` (lines 6 to 7 of the model). C1 changes the same
  file near line 58. Merge C1 first, then rebase C3.
- C3 is merged after C1 is merged, on no fixed day (Q32). The merge publishes the docs
  (`.github/workflows/deploy-public-docs.yml`).
- Branch names: `OME-1947-frozen-copy-expiry`, `OME-1947-engine-expired-copy-message`,
  `OME-1947-pinned-cache-retention-docs`.

## Order of work
1. C1: C1.0 (the record rules) → S-33 → model and migration 0019 → C1.2 (all stack A tests
   green) → S-37 → S-6 (the builder gets the rule here: make the two approved edits of C1.0 in
   the same step) → S-1 → S-4 → S-35 → S-14 and the `EXPLAIN` check (Postgres) → K-25 → CH-1
   confirmed green → R-1, R-2, R-3 → chart → runbook → `ruff format` → the two `approved_blob`
   values in the record → gates (`run_gates.py` checks the record) → Postgres lane → commit.
2. C2: CH-2, CH-3 confirmed green → R-4 → R-5 → R-6 → R-7 → gates → commit.
3. C3: text edits → gates → review against `prd/expired-copy-replay.md` §3.1 and §4.3.

## C1 — migration 0019, the expiry rule, the setting, 410 on replay
### C1.0 Approval record for two existing assertions (approved by the owner, Q27)
`build_frozen_copy_sweep` gets a second rule, so the run report has a second key. Proof (offline
probe, 2026-11-17): a sweep with two rules gives `marked == {'abandoned': 0, 'expired': 0}`
(`core/frozen_copy/sweep.py:290-305` writes one key for each rule).

| File and test | Assertion that fails | Assertion-only change |
|---|---|---|
| `tests/unit/test_frozen_copy_sweep.py:345`, `test_the_builder_uses_the_idle_time_and_the_budget_of_the_settings` | `report.marked == {"abandoned": 1}` | `== {"abandoned": 1, "expired": 0}` |
| `tests/unit/test_frozen_copy_sweep_cli.py:131`, `test_run_marks_and_purges_in_one_pass` | `out["marked"] == {"abandoned": 2}` | `== {"abandoned": 2, "expired": 0}` |

- Each other assertion of the two tests was read and stays true. No other existing test builds
  the sweep through the builder and compares `marked` or `skipped`.
- **The record.** `.claude/test-change-approvals/OME-1947.json` is one file for the issue, and
  its `branch` field is one name (the matcher: `.claude/scripts/approved_test_changes.py:29-52`).
  After stack A is merged, its entry is not read again. Smallest honest handling: in the C1 pull
  request, set `branch` to the C1 branch, add the two files with their `base_blob` (the blob on
  `main`) and `approved_blob`, keep the old entry, and add one "Update <date>" sentence to
  `scope` and to `reason` (form: `OME-939.json`). The owner approved the two changes and this
  update on 2026-11-17 (Q27); write that in the "Update" sentence. The approval covers these two
  assertions only. A different change of an existing test → STOP.
- **The record pins the bytes of each file.** The matcher compares the hash of the file on disk
  with `approved_blob` (`approved_test_changes.py:104-105`). Thus a file with an approved change
  gets no other edit in C1: no test of C1 is appended to `tests/unit/test_frozen_copy_sweep.py`
  or to `tests/unit/test_frozen_copy_sweep_cli.py` (S-35 goes to the new file of C1.4). Compute
  `approved_blob` with `git hash-object` after the last edit of each file, also after `ruff
  format`. A later edit of such a file needs a new blob in the record.
- **Two more existing tests would fail, and the plan avoids both with no test change:**
  - `tests/unit/test_chart_render_frozen_copy_sweep.py:119` pins the keys of
    `config.frozenCopySweep` to three names. Thus the chart value of the new setting is a key of
    `config:` itself (C1.3), not of that block.
  - `tests/unit/test_frozen_copy_sweep_lifespan.py:136-138` pins the one record that starts with
    "frozen copy sweep armed". **Owner decision Q31:** the start log shows the new value in a
    second record (C1.3). The record of stack A does not change, and no stack A test changes
    (`prd/copy-sweep.md` §4.1, S-32, S-37).
- Checked, no effect: the migration tests of 0014 and 0018 migrate to the newest migration and
  then compare eight or three named columns
  (`tests/unit/test_frozen_copy_migration.py:48-95`,
  `tests/unit/test_frozen_copy_retention_migration.py:58-95`); they stay green when the reverse of
  0019 drops its column. The Postgres tests and the trigger tests build `IdleRule` directly or
  patch the builder. `tests/unit/test_frozen_copy_retention_states.py:57-61` pins the seal text of
  `_gone`; C1.5 keeps it as the default.

### C1.1 Model and migration 0019
- `src/aigateway/core/frozen_copy/models.py`, after `purged_at` (`:58`): `retention_from =
  fields.DatetimeField(null=True)`, with one comment line from `erd.md` §2.1. No index.
- New file `src/aigateway/migrations/0019_frozen_copy_retention_clock.py`.
  `dependencies = [("models", "0018_frozen_copy_retention")]`. Generate with `uv run tortoise -c
  aigateway.db.TORTOISE_CONFIG makemigrations -n frozen_copy_retention_clock models`, then edit
  (remove the `AlterField` on `OAuthConnection.account`). Docstring as 0018 (UPGRADE, DOWNGRADE,
  AUTHORING NOTE); DOWNGRADE text from `erd.md` §5.1.
- Operations in this order:
  1. `ops.RunPython(code=_bound_lock_wait, reverse_code=ops.RunPython.noop)`.
  2. `_AddColumn(model_name="FrozenCopy", name="retention_from",
     field=fields.DatetimeField(null=True, auto_now=False, auto_now_add=False))`.
  3. `ops.RunPython(code=_stamp_sealed_copies, reverse_code=ops.RunPython.noop)`.
- Copy `_LOCK_TIMEOUT_MS`, `_SET_LOCK_TIMEOUT_SQL`, `_dialect_of`, `_bound_lock_wait` and the
  class `_AddColumn` from `migrations/0018_frozen_copy_retention.py:30-60` (`_AddColumn` needs
  `_TABLE`, `:30`). Do not import from a
  different migration file. The downgrade is one `ALTER TABLE frozen_copies DROP COLUMN
  retention_from`.
- **The stamp:**
  ```python
  async def _stamp_sealed_copies(apps: Any, schema_editor: BaseSchemaEditor) -> None:
      del schema_editor
      model = apps.get_model("models", "FrozenCopy")
      await model.filter(status="sealed").update(retention_from=datetime.now(UTC))
  ```
  This is one `UPDATE` with one timezone-aware UTC parameter. The ORM writes it in the format
  that it uses for `sealed_at` (`core/frozen_copy/store.py:141`). No `CURRENT_TIMESTAMP` and no
  `now()`. Exemplar for a data step: `migrations/0010_simplify_request_cache.py:14-17`.
  `RunPython` gets the state after step 2, so the model has the field (Tortoise 1.1.8). Write the
  status as the literal `"sealed"`, not as an import from the app code.
- **S-33**, new file `tests/unit/test_frozen_copy_retention_clock_migration.py` (copy
  `_tortoise`, `_columns`, `_index_columns` from
  `tests/unit/test_frozen_copy_retention_migration.py:22-50`): the dependency is 0018; migrate,
  then `downgrade models 0018_frozen_copy_retention`. Insert with `sqlite3` one `accounts` row
  (form: `tests/unit/test_migration_0017_drop_migration_note.py:105-112`), **two** `sealed`
  copies with different `sealed_at`, and one `open` copy. Migrate again. Assert: the column is
  nullable; the `open` row keeps `NULL`; the two `sealed` rows have one equal value that is not
  `NULL` (with one sealed row, "equal" cannot fail). In a script out of process (form of
  `:111-138`): the value read through `FrozenCopy` has a `tzinfo`, it is between the start and
  the end of the test, and its text in the database ends with `+00:00`, as a `sealed_at` that
  `seal` writes. After the downgrade to 0018 the column is gone, and the index `(status,
  purged_at)` and the three columns of 0018 stay. The autodetector proposes no change.
- **S-33 on Postgres**, new module `tests/integration/test_frozen_copy_retention_clock_postgres.py`
  (`pytestmark = pytest.mark.needs_postgres`), with its own container fixture (copy
  `postgres_database_url`, `tests/integration/test_frozen_copy_sweep_postgres.py:65-91`, without
  `pg_client`). It must not use the database of the sweep tests: that fixture has module scope,
  and a downgrade there removes a column under the other tests. Form for the rows:
  `tests/integration/test_migration_0017_drop_migration_note_postgres.py:80-92`. The same down,
  insert (account, two `sealed`, one `open`), up; the value read through the model is aware, and
  it is equal for the two `sealed` rows.

### C1.2 Move the rules to their own module, and share the lock step
Owner decision Q30: the rule classes move to `core/frozen_copy/sweep_rules.py`, so that no file
is above 450 lines. This unit is more than a move. It has two parts, and no behaviour changes.
- **Part 1, the move.** `core/frozen_copy/sweep.py` has 395 lines; a second rule takes it above
  450. Move to a new file `core/frozen_copy/sweep_rules.py`: `MarkOutcome` (`:66`), `_utc`
  (`:69-71`), `_is_postgres` (`:74-75`), `_idle_since` (`:88-94`), `SweepCandidate`
  (`:104-112`), `SweepRule` (`:115-122`), `IdleRule` (`:125-195`), and the `asyncpg` import
  (`:28`).
- **Keep the names `_utc` and `_is_postgres`.** `sweep.py` imports them from `.sweep_rules`, so
  the call sites that stay in `sweep.py` do not change (`database_now` `:81-85`, `dry_run`
  `:233`, `purge_chunk` `:346`, `finish_purge` `:360`). A rename is the larger change. Pyright
  runs in basic mode (`pyrightconfig.json`), and the gateway imports private names of a sibling
  module in other places (`plugins/openrouter_provider/live_models.py:38`).
- `sweep.py` keeps the public names in `__all__` (`:39-48`), so each import of today works
  (`tests/unit/test_frozen_copy_sweep.py:17`,
  `tests/integration/test_frozen_copy_sweep_postgres.py:40`). No test patches a moved name: the
  one module patch is `sweep_module.database_now`
  (`tests/unit/test_frozen_copy_sweep_trigger.py:297`), and it stays in `sweep.py`.
- **Part 2, the lock step (a refactor of `IdleRule`).** Take the `except LockNotAvailableError`
  of `:164-171`, and the transaction, `SET LOCAL lock_timeout` and `select_for_update` of
  `:174-177`, into one function that both rules use:
  ```python
  Decide = Callable[[FrozenCopy | None], Awaitable[MarkOutcome]]
  async def mark_locked(copy_id: UUID, lock_timeout_ms: int, decide: Decide) -> MarkOutcome: ...
  ```
  `decide` is **async**: the idle check reads the newest entry under the lock (`_idle_since`,
  one query). It gets the locked row or `None`, evaluates the rule again, writes the row and
  returns the outcome. It runs inside the transaction of `mark_locked`.
- Proof: the stack A tests of the sweep, of the command and of the trigger, and the Postgres
  lane (S-13, S-15, S-31, S-36 test the lock step), are green with no edit. Then start C1.4.

### C1.3 Setting, chart value, start log
- `src/aigateway/config.py`, after `frozen_copy_sweep_max_entries` (`:220-222`):
  ```python
  frozen_copy_unclaimed_ttl_seconds: int = Field(
      default=7_776_000, gt=0, validation_alias="AIGW_FROZEN_COPY_UNCLAIMED_TTL_SECONDS"
  )
  ```
  Add one sentence to the comment block of `:207-213`. No switch and no date setting.
- `charts/aigateway/values.yaml`: a key of `config:` after the `frozenCopySweep` block
  (`:150-153`): `frozenCopyUnclaimedTtlSeconds: 7776000`. `templates/configmap.yaml`, after
  `:53`: `AIGW_FROZEN_COPY_UNCLAIMED_TTL_SECONDS: {{ .Values.config.frozenCopyUnclaimedTtlSeconds
  | int64 | quote }}`. Without `int64`, Helm renders 7776000 as `7.776e+06`, and the gateway
  refuses that text. `README.md`: one sentence.
- `src/aigateway/main.py` (527 lines, above 450 before this work), after the record of
  `:247-252`: `logger.info("frozen copy expiry armed (unclaimed_ttl_s=%s)", …)`. Add only this
  statement.
- **S-37**: append to `tests/unit/test_frozen_copy_sweep_settings.py` (helper `_settings`,
  `:21-25`): 0 and −1 raise a validation error that names the field. Append to
  `tests/unit/test_frozen_copy_sweep_lifespan.py` (`_app`, `_client`, `:40-56`; `caplog` with the
  logger name `aigateway.main`): the second record has the value. New file
  `tests/unit/test_chart_render_frozen_copy_expiry.py` (copy `_config_data`,
  `tests/unit/test_chart_render_frozen_copy_sweep.py:39-60`): the default renders `"7776000"`,
  a value from a values file reaches `Settings`, and the production values keep the default.

### C1.4 The expiry rule (`core/frozen_copy/sweep_rules.py`)
```python
class ExpiryRule:                    # name = STATUS_EXPIRED; it has the shape of SweepRule
    def __init__(self, *, unclaimed_ttl_seconds: int, lock_timeout_ms: int = 2000) -> None: ...
    async def candidates(self, at: datetime) -> list[SweepCandidate]: ...
    async def mark(self, copy_id: UUID, at: datetime) -> MarkOutcome: ...
```
- **`candidates(at)`**: `cutoff = _utc(at) - ttl`. One query, built in one method
  (`_candidates_query(cutoff)`, so that a test can read its plan), with the cutoff as a parameter:
  `FrozenCopy.filter(Q(retention_from__lte=cutoff) | Q(retention_from__isnull=True,
  sealed_at__lte=cutoff), status=STATUS_SEALED, claimed_at__isnull=True).values("id",
  "account_id", "entries")`. This is `COALESCE(retention_from, sealed_at) + ttl <= now`. Do not
  read all sealed rows into memory (about 130 000 rows after 90 days, `erd.md` §2.6).
  `SweepCandidate.entries` is the column `entries` (the count at seal). It sets no `skip`.
- **`mark(copy_id, at)`** through `mark_locked` (C1.2). Under the lock: `copy is None`, or
  `status != STATUS_SEALED`, or `claimed_at is not None` → `"rule no longer true"`. `start =
  copy.retention_from or copy.sealed_at`; `None`, or `_utc(at) < _utc(start) + ttl` → `"rule no
  longer true"`. Else `status = STATUS_EXPIRED`, `swept_at = at`, and `purged_at = at` when
  `entry_seq == 0`; `save(update_fields=[…])`; `"marked"`. Do not change `entries`. A claim that
  commits first wins, because the mark reads `claimed_at` under the lock.
- **`build_frozen_copy_sweep`** (`sweep.py:387-395`): the list becomes `[IdleRule(…),
  ExpiryRule(unclaimed_ttl_seconds=settings.frozen_copy_unclaimed_ttl_seconds)]` (idle rule
  first, `contracts.md` K7). Remove the sentence about C1 from its docstring.
- **Nothing else changes** (verified in the code): `dry_run` (`sweep.py:231-270`) has the key
  `expired` and counts each rule; `_mark_all` (`:290-305`), `_purge` (`:307-340`) and
  `_log_report` (`:372-384`) read no rule name; the command
  (`src/aigateway/frozen_copy_sweep.py:23`) and the trigger
  (`core/frozen_copy/sweep_trigger.py:129-136`) call the builder.
- Do not: add a switch, a date setting or an approval step; write `retention_from` in app code;
  evaluate the rule in `FrozenCopyStore.claim`.
- **Tests**, new file `tests/unit/test_frozen_copy_expiry.py` (the file
  `tests/unit/test_frozen_copy_sweep.py` has 450 lines: do not append there). Fixtures
  `seed_copy`, `account_id_of`, `run_async`; `make_entries`, `read_copy`
  (`tests/unit/test_frozen_copy_sweep_support.py:15-37`). A local helper sets `sealed_at`,
  `retention_from` and `claimed_at` with `FrozenCopy.filter(…).update(…)`. Build the sweep with
  `[ExpiryRule(unclaimed_ttl_seconds=…)]`, a fake `sleep` and a fake `clock`.

| Test | Assertion |
|---|---|
| S-6 (first) | an unclaimed sealed copy, sealed 91 days ago → `expired`, `swept_at` set, no entry row, `purged_at` set, the column `entries` not changed, the row present |
| S-1 | a claimed sealed copy, sealed 400 days ago → `sealed`, all entries present, `marked == {"expired": 0}` |
| S-4 | `retention_from` 10 days ago and `sealed_at` 200 days ago → not a candidate; a candidate at `retention_from + ttl`. `retention_from IS NULL` → a candidate at `sealed_at + ttl`, not one second before |
| S-4 (states) | a sealed copy inside its period stays; an `open` and an `abandoned` copy never become `expired` |
| S-37 (value) | the builder with `frozen_copy_unclaimed_ttl_seconds=3600` (`Settings(**{"_env_file": None, …})`) expires a copy that was sealed 2 hours ago |
| S-35 | in this new file, not in `test_frozen_copy_sweep_cli.py` (C1.0). Copy the helper `_command` and the fixture `_no_db_lifecycle` (`tests/unit/test_frozen_copy_sweep_cli.py:34-51`): the dry run of the command lists the copy for the rule `expired` with its entries, also with a future `--cutoff`; no row changes |

- **S-14** (Postgres), new module `tests/integration/test_frozen_copy_expiry_postgres.py`
  (`pytestmark = pytest.mark.needs_postgres`; copy the fixtures `postgres_database_url` and
  `pg_client`, `tests/integration/test_frozen_copy_sweep_postgres.py:65-121`). Do not append to
  the sweep module: it has 411 lines. Fixed order, as its tests of `:265-320`: task A opens
  `in_transaction()`, calls `FrozenCopyStore.claim(copy_id)` in it, sets an event and waits; the
  test starts B (`ExpiryRule(…, lock_timeout_ms=10_000).mark`), lets A commit, and asserts that B
  returned `"rule no longer true"`, that the copy is `sealed` with `claimed_at` set, and that
  each entry is present.
- In the same module: one test that `candidates` gives the same result on Postgres as S-4; and
  the **`EXPLAIN` check** of `erd.md` §2.6. In a transaction, `SET LOCAL enable_seqscan = off`,
  then `await rule._candidates_query(cutoff).using_db(conn).explain()` (`QuerySet.explain`,
  Tortoise 1.1.8). Assert that the plan uses the index on `(status, purged_at)` and has no
  sequential scan. (The test table is small, so the planner takes a sequential scan without the
  `SET`; the test proves that the index can serve the query.)
- **K-25**, append to `tests/unit/test_frozen_copy_claim.py` (file of B1): an unclaimed sealed
  copy, sealed 91 days ago and not marked → the claim answers 200 and sets `claimed_at`. Then
  one `run_pass` of `build_frozen_copy_sweep(Settings(**{"_env_file": None}))` leaves it
  `sealed` with its entries. In the same test, a second copy with the same age and no claim
  becomes `expired` in that pass: without this, the test passes when the builder has no expiry
  rule.

### C1.5 Replay of an expired copy (`src/aigateway/routes/frozen_copies.py`)
- `_gone` (`:209-218`) gets a second argument `message: str`, with the text of today as its
  default.
- `_sealed_copy` (`:100-116`), after the lookup of `:113`: `if copy is not None and copy.status
  == STATUS_EXPIRED: raise _gone(STATUS_EXPIRED, "the frozen copy expired and its entries were
  deleted")`. Each other case keeps the 404 of today, also `abandoned`. The 410 has no
  `X-AIGW-Replay` header (`_REPLAY_HEADER`, `:50`). Update the docstring of `:101`.
- **R-1, R-2, R-3**, append to `tests/unit/test_frozen_copy_replay.py`. Send valid call key
  headers: both routes read the key before the copy (`:146-147`, `:270-271`). R-1: a chat replay
  of an `expired` copy → 410, `code`, `state`, the message, and no `X-AIGW-Replay` header. R-2:
  the tool lookup → the same 410. R-3: an `abandoned` copy → 404 `frozen_copy_unavailable` on
  both routes.
- **CH-1**: `tests/unit/test_frozen_copy_replay.py:337` and
  `tests/unit/test_frozen_copy_routes.py:330`. Name them in the ledger.

### C1.6 Runbook (`DEPLOYMENT.md`, section of stack A, `:800-999`)
Update: what the sweep does (`:807`); the fourth setting (`:848`); the sentence "the counts under
`rules.expired` are always 0" (`:875`); the example of the run log record (`:899`, two keys for
each rule); the release checks → `test-plan.md` §5.3 (`:944`); the downgrade of 0019, which does
not limit its lock wait (`:956`); the order after a restore: migrate Job, then `claim_copies`
(`:993`).

## C2 — the engine message for an expired copy
Lint limits of the engine (`apps/screamingface-engine/pyproject.toml:168-173`): complexity 8, 7
branches and 3 `return` statements for each function. `replay_refusal_code` has 3 `return`
statements today (`capture_outcomes.py:98, 101, 103`), and `_replay_refusal` has 3
(`connector.py:1563, 1570, 1571`). Each change below uses a lookup and adds no `return`.
- `src/screamingface_engine/capture_outcomes.py`, after `REPLAY_UNAVAILABLE` (`:87`):
  ```python
  REPLAY_EXPIRED = "frozen_copy_expired"     # the gateway's code; never a code of the engine
  REPLAY_EXPIRED_TEXT = (
      "the frozen copy expired: no leaderboard score used it in its retention period, "
      "and the gateway deleted its answers"
  )
  _REFUSAL_CODES = {
      404: frozenset({REPLAY_MISS, REPLAY_UNAVAILABLE}),
      410: frozenset({REPLAY_EXPIRED}),
  }
  ```
  `replay_refusal_code` (`:90-103`) keeps 3 `return` statements: (1) `accepted =
  _REFUSAL_CODES.get(status)`; `accepted is None` or a payload that is not an object → `None`;
  (2) status 404 with `detail == "Not Found"` → `REPLAY_UNAVAILABLE`, as today; (3) `return code
  if code in accepted else None`. Update its docstring ("Only a 404 can be one"). Add the two
  public names to `__all__` (`:312`).
- `src/screamingface_engine/world/connector.py`, `_replay_refusal` (`:1553-1571`): replace the
  `if / elif / else` of `:1565-1570` with one table, code → (message, code that leaves the
  engine): `REPLAY_MISS` and `REPLAY_UNAVAILABLE` keep their text and code; `REPLAY_EXPIRED` →
  (`REPLAY_EXPIRED_TEXT`, `REPLAY_UNAVAILABLE`). No entry → `None`. The function keeps 3
  `return` statements. A 410 with a different code falls to `_replay_unavailable()`
  (`:1538-1539`, `:1546-1550`), as today.
- `src/screamingface_engine/world/web_tools.py`, `lookup` (`:152-175`): `code =
  replay_refusal_code(response.status_code, payload)`; a 404 with no code stays `REPLAY_MISS`
  (the `or REPLAY_MISS` of `:159`). Replace the `if code == REPLAY_MISS` of `:165-170` with one
  table, code → (message, code): `REPLAY_MISS` keeps its text; `REPLAY_EXPIRED` →
  (`REPLAY_EXPIRED_TEXT`, `REPLAY_UNAVAILABLE`); the default is the last `raise` of today
  (`:171-175`). The function gets no new branch. Run `uv run ruff check` after the edit.
- No existing engine test names `replay_refusal_code`, and no test reads the source of
  `capture_outcomes.py`, `connector.py` or `web_tools.py` for these functions, so the new shape
  breaks no test.
- `src/screamingface_engine/error_text.py:78-83`: update the comment only (one more fixed text
  under `frozen_copy_unavailable`). Do not add `frozen_copy_expired` to `ENGINE_ERROR_CODES`,
  `ENGINE_RESERVED_CODES` or `DECLARED_FAILURE_CODES` (`benchmarks/contract.py:88-92`). No SDK
  change.
- `connector.py` (2096 lines) and `web_tools.py` (588 lines) are above 450 lines before this
  work. Add only the lines above.
- **Tests**, new file `tests/unit/test_frozen_copy_replay_expired.py` (a new module, as
  `tests/unit/test_frozen_copy_replay_failures.py:10` says). Fixtures from `frozen_copy_support`
  (`:17-26` of that file); `_refusal` as `:34-35`.

| Test | Assertion |
|---|---|
| R-4 | a chat replay that gets 410 `frozen_copy_expired` → code `frozen_copy_unavailable`, permanent, the text is `REPLAY_EXPIRED_TEXT`, one POST (`gateway.paths() == [REPLAY_CHAT]`) |
| R-5 | the gateway `message` is not in the failure text |
| R-6 | a tool lookup that gets the 410 → `("frozen_copy_unavailable", True)` with the expired text; one lookup; Tavily is not called |
| R-7 | a 410 with a different code, and a 410 with no JSON body → `frozen_copy_unavailable` with the old text of each path |
| R-7 (codes) | `"frozen_copy_expired"` is not in the three code sets |

- **CH-2**: `tests/unit/test_frozen_copy_replay_failures.py:50-76`. **CH-3**:
  `tests/unit/test_frozen_copy_replay_unserved.py:59-70`. Both stay green with no edit. No
  existing engine test pins a 410 or calls `replay_refusal_code` directly.

## C3 — public docs, glossary, E14 record, model docstring
- `public-docs/src/pages/learn/CachingPage.vue`, section "Reproducing a submission" (`:84-91`):
  remove "and it is kept forever" (`:90`). Add one paragraph with the rule of
  `prd/expired-copy-replay.md` R2: a pinned cache that a leaderboard score uses is kept; a
  pinned cache with no submitted score is deleted 90 days after it is sealed (a run seals its
  pinned cache when it ends); for a pinned cache that was sealed before the rule started, the 90
  days count from the start of the rule; submit the score before that time; a replay of a
  deleted pinned cache fails with a message that says it expired; the rule also applies to a
  local engine; a score can be submitted with a pinned cache only when the service holds that
  pinned cache complete. Use "pinned cache", not "frozen copy" (`CONTEXT.md:190`). Do not change
  "Cache entries do not expire" (`:30`): that text is about the request cache.
- **No date (Q32).** The page gives no date for the start of the rule, and it names no release
  day and no person. It states the rule only. C3 has no placeholder and waits for no release
  day: it is merged after C1 is merged.
- `CONTEXT.md:187`: the first sentence of "Pinned Cache" becomes the text of R4.
- `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md`: add the rows Q33
  to Q36 after its row Q32 (`:54`; these are row numbers of the E14 record, not of the ledger of
  this spec), with the text of `prd/expired-copy-replay.md` §4.3. Replace the text
  of F1 (`:89`) and F2 (`:90`) with `erd.md` §2.5 (I6, I7). Do not edit the row Q15 (`:37`).
- `apps/aigateway/src/aigateway/core/frozen_copy/models.py:6-7`: the same new F1 and F2.
- No automated test. The reviewer searches `public-docs/` for "kept forever" and for "permanent"
  near "pinned cache" (11 pages name the pinned cache; only `CachingPage.vue:90` says "forever"
  today), and compares the four rows with §4.3.

## What stack C leaves
The work of the spec is complete. The first copies expire 90 days after the production release
of C1, with no further action (`00-overview.md` §7.1 step 6).

## Release notes for the operator
`00-overview.md` §7.1 steps 5 and 6, with the checks of `test-plan.md` §5.3. Handoff to the
infrastructure repo: `AIGW_FROZEN_COPY_UNCLAIMED_TTL_SECONDS` (the default is correct for
production). After a restore of the gateway database: the migrate Job first, then
`python -m scoreboard.claim_copies` at once (`test-plan.md` §5.4).

## Risks during the build
1. **Two existing assertions change** (C1.0, approved in Q27). The record must have the C1
   branch name and the final blobs before the push, or the pre-push check fails.
2. **The stamp through the state model.** The plan assumes that `apps.get_model` in step 3
   gives a model with `retention_from` and that its `update` works on both dialects. S-33 proves
   it on SQLite and on Postgres. If it fails, pass the same Python value as a parameter of
   `schema_editor.client.execute_query`, and keep the rule "no `now()` in the statement".
3. **Time values on SQLite.** Proof (offline probe, 2026-11-17): `save()` and `create()` write
   an aware time as UTC text (`…+00:00`), but `QuerySet.update()` writes the offset that it
   gets (`12:00:00+02:00` stays as it is). SQLite compares these values as text. Rules:
   - The migration stamp and each test helper pass a timezone-aware **UTC** value to
     `.update()` (`datetime.now(UTC)`), never a local time and never a naive time.
   - The SQL filter of `candidates` only selects candidates. The check under the lock decides:
     it compares in Python through `_utc(...)`, so a row that the filter selects wrongly is not
     marked. A row that the filter misses is found by a later run.
   - Postgres compares `timestamptz` values, so this risk is for SQLite only (local gateways and
     the unit tests). S-4 and S-33 prove both dialects.
4. **S-14 and the nested transaction.** The plan assumes that `claim` inside an outer
   `in_transaction()` uses the same connection and keeps the row lock until the outer block
   ends. If not, write task A by hand, as the stack A tests do (`:265-320`).
5. **The move of C1.2** changes no behaviour, but it moves code that deletes production data.
   Do it as its own step, and run the Postgres lane before the next step.
6. **A local or development gateway** also runs the rule: a sealed copy there expires after 90
   days, because no scoreboard claims it (`prd/copy-sweep.md` §4.1). The docs of C3 say this.
7. **Files above 450 lines before this work:** `config.py` (506), `main.py` (527),
   `connector.py` (2096), `web_tools.py` (588). `tests/unit/test_frozen_copy_sweep.py` is at 450:
   C1.0 changes one line there and adds none.

## Owner decisions (2026-11-17)
The owner answered the open questions of this plan. The decisions are in `00-overview.md` §5.4.
- **Q26:** all work stays under `OME-1947`; no sub-issue for each app. Each pull request body has
  `Refs: OME-1947`. The issue stays open until stack C is released.
- **Q27:** the two assertion-only changes of C1.0 are approved. The record
  `.claude/test-change-approvals/OME-1947.json` is updated in the C1 pull request, with the C1
  branch name and the blobs computed after the last edit of each file.
- **Q30:** C1.2 moves the rule classes to `core/frozen_copy/sweep_rules.py`.
- **Q31:** the 90-day setting is in a second start log record, "frozen copy expiry armed
  (unclaimed_ttl_s=…)" (C1.3). The record of stack A does not change.
- **Q32:** the public docs give no date, and no person is named for a release day. C3 is merged
  after C1 is merged (C3, "Release note", "Pull request shape").
