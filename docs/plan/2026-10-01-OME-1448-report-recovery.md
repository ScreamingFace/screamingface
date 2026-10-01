# Plan — recover a finished Evaluation, and export with bounded memory (OME-1448)

- Spec: `docs/spec/2026-10-01-OME-1448-report-recovery/` (read `00-overview.md` first).
- Ticket: OME-1448 (design, under E5 OME-1294). Ledger: `docs/work/2026-10-01-report-recovery.md`.
- Root: `packages/screamingface/`. Stack card: `screamingface` (`.claude/sdlc.local.md`). Skill: `sdlc-python`.
- No Engine, AIGateway, or chart change. No new dependency.
- **Status: waiting for your approval. No code starts before it.**

## 0. Slicing, branches, and filing

Four PRs. Each one is green alone. Each one gets its own worktree from `origin/main`
(`git worktree add .claude/worktrees/<slug> -b <slug> origin/main`).

| PR | Slug | Content | Depends on | Spec tests |
|---|---|---|---|---|
| A | `report-recovery-export` | atomic-file helper, streaming writer, `Report.export` (D); also carries the spec + plan docs | — | RW-*, EX-* |
| B | `report-recovery-local-dir` | durable local artifact folder | — (parallel with A) | LA-* |
| C | `report-recovery-record` | recovery port + store + codec, Candidate slot, record hook, delivered marking | A merged (uses the atomic-file helper) | RS-*, RE-* |
| D | `report-recovery-recover` | `ArtifactRedeemer`, recover service, `sf.recover` / `sf.recoverable`, notice, CLI, public surface | C merged | RC-*, RN-*, ARCH-1 |

**Filing (at each PR-open, after you confirm):** I propose one leaf under OME-1294 for each PR,
with the SDK component label, `who-acts`, and `actor` from `.claude/task-board.local.md`,
self-assigned, related to OME-1448, plus a `docs/tasks/` mirror. Each PR body gets
`Refs: OME-<leaf>`. OME-1448 closes when PR D merges. If you prefer one issue (OME-1448) for all
four PRs, say so at the first PR-open.

**This worktree** (`OME-1448-report-recovery`) holds the spec and the plan. PR A copies the two
doc folders, the ledger, and the mirror. Then this worktree is removed.

## 1. Rules for every step

- RED first: write the test, run it, and see it fail on the missing behavior. Then GREEN with the
  smallest change.
- Tests are append-only. Do not edit an existing test. The public surface snapshot is the only
  planned exception (PR D, owner-approved: `--skip-append-only` for the snapshot only).
- Gates for each PR: `python3 .claude/scripts/run_gates.py screamingface` (ruff check, ruff
  format, pyright, pytest `-n auto --dist worksteal --cov-fail-under=95`, notebooks, build,
  distribution).
- `tests/conftest.py` already sets `SCREAMINGFACE_DATA_DIR` to a temp folder for every test
  (autouse). No test may write under the real `~/.screamingface`.
- Comment style: match the files you edit (`WHY:` / `INVARIANT:` / `FEATURE (OME-1448):`).
- Delegation: steps marked **[impl]** are fully specified for the `implementer` agent, with a
  `design-reviewer` pass after. Steps marked **[main]** change a structural seam (the transport
  hook, the runner flow), so I write them in the main loop.

## PR A — streaming writer and export (option D)

**A1. Atomic file helper [impl].** New `src/screamingface/_atomic_file.py`:

```python
def write_atomic(
    target: Path,
    write: Callable[[BinaryIO], None],
    *,
    private: bool = False,
) -> Path:
    """Write `target` through a sibling temp file; replace it only on success."""
```

- Resolve symlinks first: `final = Path(os.path.realpath(target))` (EX-D3).
- Temp name: `final.parent / f".{final.name}.{uuid4().hex}.tmp"`. Open it with
  `os.open(tmp, O_WRONLY | O_CREAT | O_EXCL, 0o600 if private else 0o666)`. The kernel applies
  the umask, so do not call `os.umask` (it is process-global and not thread-safe).
- If `final` exists and `private` is false, `os.chmod(tmp, stat.S_IMODE(final.stat().st_mode))`
  (EX-D4).
- Wrap the fd in `io.BufferedWriter` (1 MiB buffer). Call `write(fp)`, then `flush`, `os.fsync`,
  `os.replace(tmp, final)`.
- On any exception: close the file, `tmp.unlink(missing_ok=True)`, and re-raise.
- Exemplar: `apps/screamingface-engine/src/screamingface_engine/artifacts/filesystem.py:51`
  (same tmp + replace pattern).
- Tests: EX-1, EX-4, EX-5, EX-6 (they go through `export` in A3, but write a direct unit test of
  `write_atomic` first).

**A2. Streaming writer [impl].** In `src/screamingface/report.py`, next to `Report.to_json`:

```python
def _write_report_json(
    fp: BinaryIO,
    *,
    benchmark: BenchmarkInfo,
    case_count: int,
    started_at: datetime,
    completed_at: datetime,
    candidate_names: Sequence[str],
    candidates: Iterable[CandidateResult],
) -> None:
```

- Emit, in order: `{"schema":…,"started_at":…,"completed_at":…,"benchmark":…,"candidates":[`,
  then each `CandidateResult.to_dict()` with `,` between them, then `],"usage":…}`. Encode every
  fragment with `json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")`.
  Use the same helpers as `Report.to_dict` (`_timestamp_text`, `benchmark._result_dict`).
- Collect each `candidate.usage` in a list, and emit `_combined_usage(tuple(usages)).to_dict()`.
- Validation (RW-D4): extract the checks in `Report.__init__` (`report.py:400`) into
  `_require_report_candidate(benchmark, case_count, candidate)`, and make `Report.__init__` call
  it. Check the unique, non-empty `candidate_names` before the first byte, with the same rule that
  `_CandidateResults` applies. Call `_require_report_candidate` before you write each Candidate.
- Refactor on green: `Report.to_json()` writes through `_write_report_json` into a `BytesIO` and
  decodes it. RW-0 must stay green.
- Tests: RW-1 (hypothesis property: bytes equal `json.dumps(report.to_dict(), …)`; the oracle is
  the pre-change `to_dict` path, kept as a test helper), RW-2 … RW-6.

**A3. Export [impl].** `Report.export` JSON branch (`report.py:467`): keep every path check and
error message. Replace `selected.write_text(self.to_json(), …)` with
`write_atomic(selected, lambda fp: _write_report_json(fp, …self…))`. Keep the
`selected.parent.mkdir(parents=True, exist_ok=True)` call. The inspect branch does not change.
- Tests: EX-0 (existing tests green and unchanged), EX-1 … EX-7.
- Do not: change `to_dict`, add a parameter to `export`, or touch the inspect path.

**A4.** CHANGELOG entry (Fixed: "export no longer holds a second full copy of the Report").
Copy the docs listed in §0 into this branch.

## PR B — durable local artifact folder

**B1 [impl].** `src/screamingface/_runtime/config.py`: add
`RuntimeConfig.artifacts_dir -> Path` (`self.data_dir / "artifacts"`). Exemplar: `assets_dir`.

**B2 [impl].** `src/screamingface/_runtime/server.py` `_build_apps` (line 246):

```python
artifacts_dir = os.environ.get(job_env.ARTIFACTS_DIR, "").strip() or str(config.artifacts_dir)
if artifacts_dir == str(config.artifacts_dir):
    config.artifacts_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
run_env = {**os.environ, …, job_env.ARTIFACTS_DIR: artifacts_dir}
engine = create_local_app(
    settings=EngineSettings(aigateway_base_url=…, artifacts_dir=artifacts_dir), env=run_env
)
```

- WHY `.strip() or`: the Engine treats a blank value as unset (`config.py:397`). Both sides must
  get the same non-blank value (OME-929).
- Tests: LA-0 (CHAR, write first; it must pass today), LA-1, LA-2, LA-4 … LA-6, LA-8.

**B3 [impl] (Should).** `screamingface status` prints the folder path and its total size (LA-7).
Find the status handler from `cli.py:53`.

**B4.** CHANGELOG (Changed: "the local stack keeps spilled results in `~/.screamingface/artifacts`").

## PR C — recovery store and the record hook

**C1. Port and types [impl].** `src/screamingface/_core/ports.py`:

```python
RecoverySlot = tuple[str, int]

class RecoveryStoreUnavailable(Exception): ...

@dataclass(frozen=True, slots=True)
class _CandidateEntry: index: int; name: str; url4: str; answer_seed: int | None

@dataclass(frozen=True, slots=True)
class EvaluationManifest:
    evaluation_id: str; created_at: datetime; origin: Literal["recipes", "url4"]
    engine_url: str; sdk_version: str; owner_pid: int; owner_hostname: str
    benchmark: BenchmarkInfo | None; case_count: int | None; limit: int | None
    candidates: tuple[_CandidateEntry, ...]

@dataclass(frozen=True, slots=True)
class StoredEvaluation:
    manifest: EvaluationManifest; state: Literal["open", "delivered"]
    delivered_at: datetime | None; runs: Mapping[int, _RunOutcome]   # artifact still set

class RecoveryStore(Protocol): …   # exactly the methods in contracts.md (record_run takes candidate_name)
```

`RecoverableEvaluation` is public. It goes in a new `src/screamingface/recovery.py` (the shape is
in `prd/recovery-notice.md` §3), and `ports.py` imports it.

**C2. Codec [impl].** New `src/screamingface/_recovery/codec.py`. It encodes and decodes the two
`v1` records exactly as in `erd.md` §2.2 and §2.5:
- Decimals as text. Times as UTC ISO-8601 with an offset. `Usage` as its six fields
  (`_report_primitives.py:100`), with `cost_usd` as text or null.
- Strict decode: check types, the patterns `^ev_[0-9a-f]{32}$` and `^[0-9a-f]{64}$`, the 2 MiB
  cap, and `schema`. Engine origin: `https`, or `http` on `localhost`/`127.0.0.1`/`::1` (the same
  rule as `_client_connections.py:66`; factor it into one shared function, do not copy it).
- Errors: `ExecutionError(code="recovery_record_invalid" | "recovery_record_unsupported")`.
- Tests: RS-3 (hypothesis round-trip), RS-4, RS-13.

**C3. Filesystem store [impl].** New `src/screamingface/_recovery/store.py`:
`FilesystemRecoveryStore(root: Path, *, now=…, pid_alive=…, hostname=…)`, with the seams for
tests.
- Layout, modes, and the state table: `erd.md` §2.1 and §2.4. Write every file with
  `write_atomic(path, …, private=True)` from A1. Create directories with `mkdir(mode=0o700)`.
- `remove`: rename to `.<id>.trash-<uuid>`, then `shutil.rmtree`; idempotent.
- `scan(now)`: list the directories; skip unknown schemas; prune delivered records older than 7
  days and empty crashed records; sweep `*.tmp` older than 1 hour; return the
  `RecoverableEvaluation` views.
- Map `OSError` to `RecoveryStoreUnavailable` on open and record.
- Tests: RS-1, RS-2, RS-5 … RS-12, RS-14 … RS-19.

**C4. Candidate slot [impl].** `src/screamingface/_evaluation/model.py`:
- Add `recovery_slot: tuple[str, int] | None` to `Candidate` (line 41), after `answer_seed`.
- `_compiled_candidate` (line 112) sets it to `None`.
- Replace the hand-listed field loop in `_with_answer_seed` (line 171) with one helper,
  `_restamped(candidate, **changes)`, that copies every field from `dataclasses.fields(Candidate)`.
  `_with_answer_seed` and a new `_with_recovery_slot(candidate, slot)` both call it.
- Tests: RE-1 (parametrized over the five kinds: `_candidate_from_url4(c.url4)` restamped with
  `name` and `answer_seed` equals `c` on the Report fields). If a kind fails, **stop and report**:
  the record must then store that projection, and that is a spec change.

**C5. Runner [main].** `src/screamingface/_evaluation/runner.py` and `_evaluation/url4.py`:
- Add the keyword `recovery: _RecoveryContext | None = None` to `evaluate_sync`,
  `evaluate_async`, `evaluate_url4_sync`, and `evaluate_url4_async`.
  `_RecoveryContext(store, engine_url)` is a small frozen dataclass in `_recovery/__init__.py`.
- After preflight, call `_open_recovery(...)`. It mints `ev_<uuid4 hex>`, calls
  `store.open_evaluation`, and returns the Candidates restamped with slots. On
  `RecoveryStoreUnavailable`, it logs one WARNING and returns the Candidates unchanged.
- After `report_from_outcomes` → `mark_delivered`. In the `except` branch: if the error is
  `ExecutionError` with `code == "candidates_failed"` and `partial_report is not None` →
  `mark_delivered`; if `partial_report is None` → `remove`; any other exception → no change.
  Store errors here log at WARNING and are never raised.
- Tests: RE-0a, RE-4, RE-6, RE-7, RE-9 … RE-12.

**C6. Transport hook [main].** `src/screamingface/_engine/transport.py`:
- Both transports take `recovery_store: RecoveryStore | None = None` in `__init__`.
- Inside `_run_reconnecting`, just before `return _materialize_sync(self._http, outcome)`
  (line 284): `self._record(candidate, _dataclass_replace(outcome, trace_id=trace.trace_id))`.
  Async (line 677): `await asyncio.to_thread(self._record, …)`.
- `_record` returns at once when `candidate.recovery_slot` is `None` or the store is `None`. It
  catches `RecoveryStoreUnavailable` and logs one WARNING per evaluation id. It logs the run id
  and the artifact id at DEBUG.
- Tests: RE-2 (MockTransport asserts the record file exists when `/artifacts/` is first hit),
  RE-3, RE-5, RE-0b, RE-13.

**C7. Client wiring [impl].** `src/screamingface/client.py` (`Client.__init__` line 44,
`AsyncClient.__init__` line 377): when `run_transport is None`, build
`FilesystemRecoveryStore(default_data_dir() / "runs")` (import `default_data_dir` lazily from
`_runtime/config.py:12`). Pass it to the transport, and pass
`_RecoveryContext(store, self._engine_url)` to the `evaluate_*` calls. When `run_transport` is
given, pass `None` (RE-D4).

**C8. Early decode [main], its own commit (RE-D6).** Decode each Candidate when it settles, and
drop its `result_body`:
- In `_run_candidates_sync` / `_async`, the per-Candidate `run()` returns `_Decoded(outcome_meta,
  result: CandidateResult)` instead of the raw `_RunOutcome`. `settle`, `raise_candidates_failed`,
  and `report_from_outcomes` accept the decoded form. A decode failure stays a per-Candidate
  failure, as `outcome.py:78` does today.
- Tests: RE-8, and all existing runner and report tests stay green.
- **Exit rule:** if this step needs edits to existing tests, or more than about 150 changed lines,
  stop. Move it to a follow-up PR, and tell you. It is `[proposed]`, not one of your answers.

**C9.** CHANGELOG (Added: "a recovery record for each Evaluation").

## PR D — recover, notice, CLI

**D1. Artifact redeemer [impl].** `src/screamingface/_engine/transport.py`: both transports
implement `ArtifactRedeemer` (`contracts.md`):
- `redeem(outcome)` → `_materialize_sync(self._http, outcome)` (async twin likewise).
- `redeem_to_file(outcome, staging_dir) -> Path`: a new `_fetch_artifact_to_file_sync` that
  copies `_fetch_artifact_once_sync` (line 1277) but writes each chunk to
  `staging_dir / f"{id}.{uuid}.part"` and hashes as it goes. It reuses the size cap and the
  `_verified_artifact_text` checks, split so that the check runs on (size, digest) without the
  bytes. The retry loop and the fresh mint are the same as `_materialize_sync`. It removes the
  part file on every failure.
- Map `404` from `/artifacts/` to a typed `_ArtifactGone` signal, so the service can name the age.
- Tests: RC-5, RC-12, RC-13, RC-16.

**D2. Recover service [main].** New `src/screamingface/_recovery/service.py`:

```python
def recover_sync(store, redeemer_for: Callable[[str], ArtifactRedeemer], evaluation_id: str,
                 *, to: Path | None) -> Report | Path
async def recover_async(...)  # twin
```

- `load` → for each `_CandidateEntry`: rebuild the Candidate (`_candidate_from_url4` +
  `_restamped(name=…, answer_seed=…)`). Build the `_Evaluation` with `_compiled_evaluation`
  (recipes origin), or take the url4 path through `report_from_url4_outcome` (url4 origin).
- In-memory mode: process the Candidates in order, one at a time: redeem → `_candidate_result` →
  drop the body. File mode: `redeem_to_file` into `<evaluation dir>/tmp/` → `json.load` →
  `_candidate_result` → yield to `_write_report_json` inside `write_atomic(to, …)` → unlink the
  part file. `started_at` / `completed_at` come from the run records (min / max).
- Missing run → a failure with the code `not_finished`. `_ArtifactGone` → `result_expired`, with
  the age from `completed_at`. Build the partial result the way `raise_candidates_failed` does
  (reuse it; give file mode `details["path"]`).
- State: all-gone → `remove`; owner alive → no state change; otherwise → `mark_delivered`
  (ans:Q13).
- A loopback origin with `httpx.ConnectError` → `local_stack_not_running` with the
  `screamingface up` hint (ans:Q11).
- Tests: RC-E2E-1 (write it first; it stays RED until D2 is done), RC-1 … RC-4, RC-6, RC-9 …
  RC-11, RC-14, RC-15, RC-17, RC-19 … RC-21.

**D3. Public API [impl].** `_default_client.py`: `recover(...)` overloads and `recoverable(...)`.
Both are pass-throughs (the OME-1227 invariant: never a narrower door). `client.py`:
`Client.recover`, `AsyncClient.recover`, `Client.recoverable`. If the record's `engine_url`
differs from `self.engine_url`, the method builds a temporary `Client(engine_url=…)` and closes it
(RC-H3, RC-7). Export `recover`, `recoverable`, and `RecoverableEvaluation` from `__init__.py`.

**D4. Notice [impl].** New `src/screamingface/_recovery/notice.py`: `announce_once(store)` with a
module-level once flag. `Client.__init__` and `AsyncClient.__init__` call it inside a
`try/except Exception` (DEBUG log). It does nothing when `SCREAMINGFACE_RECOVERY_NOTICE=0`. The
text is exactly `prd/recovery-notice.md` §3. Tests: RN-1 … RN-7, RN-9 … RN-11.

**D5. CLI [impl].** `src/screamingface/_runtime/cli.py` (subparsers at line 40): add
`recover` with `--list`, `--all`, `<evaluation_id>`, `--to`. It always uses file mode. Exit codes
0 / 2 / 1. Tests: RC-18, RN-8.

**D6. Layering test [impl].** `tests/test_recovery_layering.py` (ARCH-1): parse the imports with
`ast`. `_recovery/*` must not import `screamingface._engine`. `_engine/*` may import only
`screamingface._core.ports` from the recovery work.

**D7. Surface and docs.** Regenerate `tests/public_surface_snapshot.json`. Update the CHANGELOG
and the README section "If your notebook dies" (three lines: the notice, `sf.recover`, the CLI).

**D8. Manual benchmark (before merge).** Run RC-2 at full scale (11 × 200 MB synthetic artifacts,
local stack) on a 16 GB machine. Record the peak RSS of `screamingface recover --to` in the
ledger (`test-plan.md` §7).

## 2. Risks and stop points

| Risk | Signal | Action |
|---|---|---|
| RE-1 fails for a Candidate kind | the C4 test is red for that kind | stop; the spec must store that projection; ask you |
| C8 grows | more than about 150 lines, or existing tests need edits | move it to a follow-up PR |
| The byte identity breaks | RW-1 property failure | fix the writer; never change `to_dict` to match |
| The async record blocks the loop | the heartbeat test flakes | keep `asyncio.to_thread`; do not make it inline |
| The E5 runs API later needs a different shape | E5 picks up | `sf.recover` stays; E5 wraps `RecoveryStore` (ans:Q2, Q15) |

## 3. Done when

All four PRs are merged with green CI (squash, no `--admin`), and every spec test row is green.
The D8 benchmark is recorded. OME-1448 and the leaves are closed in Linear and in the mirrors.
The ledger outcome is filled in.
