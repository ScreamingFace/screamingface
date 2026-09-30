---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: scoreboard
status: done   # planned | in_progress | done | blocked
started: 2026-09-29
finished: 2026-09-29
---

# e14-system-registry — SB-registry: system names, revisions and fingerprints in the scoreboard

## Intent

E14 (epic OME-1307), wave 2, unit SB-registry. Add the system registry to `apps/scoreboard`: a
pure core (`core/registry`: names, pins, errors, ports, `RegistryService`), a url4 adapter
(`adapters/url4_fingerprinter.py`, D3: `exclude_bindings={"_sf_recipe"}`), a Tortoise repository
(`scores/system_registry_store.py`), the out-of-band `python -m scoreboard.backfill_systems`
command, and the layering guards C11-SB-1..3. No route, no migration. SB-submit (wave 3) calls the
service from `POST /v1/scores`; SB-grants (wave 4) calls `resolve_pin`.
Plan (the full spec): `docs/plan/2026-09-29-e14-reproducible-submission/SB-registry.md`.
Build on branch `unit/SB-registry` (D1): no PR, no Linear issue, no merge gate.

## Planned changes

- create `apps/scoreboard/src/scoreboard/core/registry/{__init__,model,errors,names,pins,ports,service}.py`
- create `apps/scoreboard/src/scoreboard/adapters/{__init__,url4_fingerprinter}.py`
- create `apps/scoreboard/src/scoreboard/scores/system_registry_store.py`
- create `apps/scoreboard/src/scoreboard/backfill_systems.py`
- change `apps/scoreboard/src/scoreboard/main.py` (one additive line: `app.state.system_registry`)
- change `apps/scoreboard/pyproject.toml`, `apps/scoreboard/uv.lock` (the `url4` path dependency)
- change `apps/scoreboard/Dockerfile` (mirror the repo layout for the path dependency)
- change `.github/workflows/scoreboard-tests.yml`, `.github/workflows/dev-build-scoreboard.yml`
- change `apps/scoreboard/DEPLOYMENT.md` (section "Backfill system names")
- create tests under `apps/scoreboard/tests/unit/registry/`, `tests/unit/test_backfill_systems.py`,
  `tests/unit/guards/test_scoreboard_layering.py`
- Migration: none (SB-schema owns the tables). If `makemigrations` writes a file: stop.

## Test plan

Owned ids (plan §1.1, §6): SR-1, SR-6..SR-20 (SR-12/14/15 also on PostgreSQL), SR-5-SB, SR-H3-SB,
SR-E6 (adapter), BF-1..BF-7, C11-SB-1..3. RED first in the risk order of plan §6 (stubs raise
`NotImplementedError`, so each RED fails on an assertion or `NotImplementedError`, never on an
import error). Oracle for SR-5-SB: `packages/url4/tests/fixtures/fingerprint_vectors.json`.

## Acceptance

- Every test of plan §6 green; the PostgreSQL module green when a PostgreSQL URL exists, and
  listed in the CI `postgres` job.
- `uv lock --check` passes; the image builds and imports `url4` (if docker is available).
- `run_gates.py scoreboard --base e14-reproducible-submission-spec` and the url4 gate are green.

## Approved exceptions

Standing approvals from the orchestrator, and what was used:

- (a) regenerate a generated test artifact: not used.
- (b) small registry entry required by an existing guard test: USED. `tests/unit/guards/test_visibility_exit_guard.py`
  (not in the plan's file list) got three `EXPECTED_UNGUARDED` entries and two reason lines,
  because the guard walks every function whose text holds `visibility`:
  `service.py::resolve_for_submit` Return x3 and Raise x1 (it takes `board_visibility` as an input;
  the caller SB-submit owns revalidation), and `backfill_systems.py::_public_unlinked_heads` Return
  x1 (one-shot operator command, same class as the `check_rollback_safety` entries). The stale-entry
  test pins the counts exactly.
  - Side effect: `run_gates.py` append-only check reports this edit ("new content inserted after old
    line 90, inside an existing test/fixture", the module-level dict). The standing approval (a) allows
    `--skip-append-only` only for a regenerated artifact, so it was NOT used. Every other gate command
    was run by hand (see Outcome). The orchestrator must confirm this one edit, or run the gate with
    `--skip-append-only` (no other existing test file changed: `git diff --name-status` lists this file
    as the only M under `tests/`).
- (c) pin an existing migration test: not used (no migration).
- (d) timing-sensitive test failing under load: not used.

## Outcome

- **Actual files:** as planned, plus (1) the guard test entries above, (2) `DEPLOYMENT.md` section,
  (3) `.github/workflows/dev-build-scoreboard.yml` path filter, (4) tests beyond the plan list
  inside the planned test files (see Test notes). No route, no migration (`tortoise makemigrations`:
  "No changes detected"). `preview-images.yml` and `release-scoreboard.yml` build the scoreboard image
  from the same Dockerfile with the repo root as context, and were not changed (no path filter
  names `apps/scoreboard` in a way a guard requires).
- **Commits:** see `git log --oneline e14-reproducible-submission-spec..HEAD`.
- **Gates:** `run_gates.py scoreboard --base e14-reproducible-submission-spec` stops red at the
  append-only check on the one approved guard edit (above). Run by hand, all green: `ruff check`,
  `ruff format --check`, `pyright` (0 errors), `pytest --cov=scoreboard --cov-fail-under=80`
  (1011 passed, 12 skipped, coverage 89%), the `node --test` portal command. `uv lock --check`
  green. `run_gates.py url4 --base e14-reproducible-submission-spec`: ALL GATES GREEN. PostgreSQL:
  `test_system_registry_postgres.py` 3 passed against a local `postgres:16` container (port 55432,
  removed afterwards), plus `test_postgres_regressions_run_in_ci.py` green with the module named in
  the CI job. `docker build -f apps/scoreboard/Dockerfile .` builds; the image imports
  `url4.fingerprint` and `scoreboard.adapters.url4_fingerprinter`; `python -m tortoise migrate` then
  `python -m scoreboard.backfill_systems --dry-run` prints the banner on a fresh SQLite file.
- **Test notes:** mutation checks run by hand (each reverted): one attempt instead of two makes
  SR-12/14/15 (PostgreSQL) and the four SQLite race tests fail; dropping `exclude_bindings` makes the
  ten `c08-*`/`c09-*` vectors, SR-H3 (adapter and service) and SR-E6 fail.
- **Deviations:**
  - tortoise-dev waived by the user for E14.
  - RED process gap: the first RED run of `test_service.py` and `test_backfill_systems.py` failed
    because the module had no `@pytest.mark.asyncio` (strict mode), not for the plan's reason. The
    mark was added per async test, and the mutation checks above show the tests bite. The names, pins,
    guard and adapter tests had the plan's RED reason.
  - Plan row 19c: the "no weight" case is not an error as built. url4 parses `_sf_recipe:'...'`
    (no weight) as a plain Binding, not a Source, so `exclude_bindings` does not see it: it stays in
    the identity and raises nothing. The test parametrizes weight 1.0, non-text value and a `$`
    reference (all raise `InvalidUrl4` with `ExcludedBindingError` as cause), and a separate test
    pins that the no-weight binding stays in the identity.
  - Backfill report shape (plan §4.10 steps 6-7 read literally): a head that claims a system emits two
    rows, `claim` then `link`. So BF-4 sees `claim`, `link`, `duplicate_head` for two identical heads.
  - `tests/unit/registry/test_system_registry_postgres.py` puts `skipif` on each test (not a module
    `pytestmark`), because the CI guard only detects a decorator.
  - The `tortoise_db` fixture switches to PostgreSQL when `SCOREBOARD_TEST_DATABASE_URL` is set and
    then calls `asyncio.run` inside a running loop (existing behaviour), so the full suite must not
    run with that variable set. The PostgreSQL module builds its own connection and runs alone.
  - `# type: ignore` is not used in any new file.

## Review-fix round 1 (blocking findings of the design review)

Status: done.

### Planned changes

- `apps/scoreboard/src/scoreboard/adapters/url4_fingerprinter.py`: `identify` also catches
  `RecursionError` and raises `InvalidUrl4("url4 expression is nested too deeply")` from it. The input
  is not echoed.
- `apps/scoreboard/tests/unit/guards/test_scoreboard_layering.py`: the import walk resolves relative
  imports to absolute names (`importlib.util.resolve_name` against the module package) and checks
  `module.name` for `from pkg import name`. C11-SB-2 becomes an allowlist (standard library plus
  `scoreboard.core.registry`). The C11-SB-1 and C11-SB-3 denylists keep their form.
- `apps/scoreboard/tests/unit/registry/test_url4_fingerprinter.py`: add the deep-nesting test.
- `apps/scoreboard/tests/unit/test_backfill_systems.py`: add BF-1b (dry run over a registered
  fingerprint), BF-3b (dry run reports the DB clash), and BF-7b (a deep head does not stop the run).
- No production change other than the adapter. No migration.

### Test plan

- RED: deep-nesting adapter test and BF-7b fail with `RecursionError` before the fix.
- RED: the new guard self-test cases fail against the current helper (relative imports pass).
- RED for BF-1b and BF-3b: the code is correct today, so they are regression pins. Each is proven by
  its mutation (M1 `if known.ref is not None:` at the link write, M2 no DB lookup in the clash check).
- Finding 2 (behavioral RED of test_service.py and test_backfill_systems.py): put
  `NotImplementedError` stubs back for a short time, run both modules, record the failure reasons here,
  restore. The stubs are never committed.

### Acceptance

- All new tests green, mutation checks fail as stated, scoreboard gates green.

### Outcome

- **Adapter (finding 3):** `Url4Fingerprinter.identify` maps `RecursionError` to
  `InvalidUrl4("url4 expression is nested too deeply")`, with the `RecursionError` as cause. RED:
  the 200-level text (2,425 characters) raised `RecursionError` in the adapter test and in the
  backfill test (BF-7b). GREEN after the fix. The backfill needed no code change: `_check` already
  turns `InvalidUrl4` into an `invalid_url4` row, and BF-7b proves the next head is still processed.
- **Guard (findings 1 and 5):** the import walk resolves relative imports with
  `importlib.util.resolve_name` against the package of the file, and checks `module.name` for
  `from pkg import name`. C11-SB-2 is now an allowlist (`sys.stdlib_module_names` plus
  `scoreboard.core.registry`). RED: the old helper returned `[]` for `from ...scores.models import
  System`, `from scoreboard import scores` and `from ...config import Settings`. Mutation on the real
  file: appending each of `from ...scores.models import System`, `from ...config import Settings`,
  `from scoreboard import scores` and `import httpx` to `core/registry/pins.py` fails
  `test_c11_registry_core_imports_only_the_standard_library` (pins.py restored). The line
  `from .. import adapters` cannot be appended to the real file: it does not import (there is no
  `scoreboard.core.adapters`), so the literal self-test pins it.
- **Backfill pins (finding 4):** BF-1b and BF-3b added. Mutation M1 (`if known.ref is not None:` at
  the link write) fails BF-1b only. Mutation M2 (the clash check without the DB lookup) fails BF-3b
  only. Both reverted (`git diff` on `backfill_systems.py` is empty).
- **Behavioral RED (finding 2):** with `raise NotImplementedError` in `RegistryService.resolve_for_submit`,
  `resolve_pin`, `identify` and in `backfill_systems`, `pytest tests/unit/registry/test_service.py
  tests/unit/test_backfill_systems.py` gave 61 failed, 4 passed. All 61 failures are
  `NotImplementedError`, none an import or mark error. The 4 that pass do not call a stubbed body:
  `test_sr1_no_parameter_of_resolve_for_submit_is_a_fingerprint` (reads the signature),
  `test_the_app_wires_the_registry_service_with_the_real_adapters` (reads app state),
  `test_the_report_names_the_mode_and_counts_each_action` (`format_report`) and
  `test_bf7_the_command_requires_exactly_one_mode` (the argument parser). The stubs were restored and
  are not committed. This covers SR-6..11, 13, 18, 20 and BF-1..7 for the RED that the first run lacked.
- **Gates by hand (the append-only check fails on the same approved edit to
  `test_visibility_exit_guard.py` as before; no other prior test changed):** `ruff check`,
  `ruff format --check`, `pyright` (0 errors), `pytest --cov=scoreboard --cov-fail-under=80`
  (1016 passed, 12 skipped, coverage 89%), the `node --test` portal command, `uv lock --check`: green.
- **Deviations:** `_forbidden_imports` now takes a required `package` argument, and the existing
  literal self-test calls were updated for it (the helper file is new in this unit, so no prior-cycle
  test is weakened). The C11-SB-1 and C11-SB-3 checks keep their denylists.
