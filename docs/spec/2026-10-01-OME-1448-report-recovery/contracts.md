# Contracts: OME-1448 recovery and export

One section for each connection. All shapes are `[proposed]` unless a tag says otherwise. Each
section names the tests that pin the contract.

## Ports (core) and adapters

```python
# screamingface/_core/ports.py  (core: ports only)
RecoverySlot = tuple[str, int]          # (evaluation_id, index)

class RecoveryStore(Protocol):
    def open_evaluation(self, manifest: EvaluationManifest) -> None: ...
    def record_run(self, slot: RecoverySlot, candidate_name: str, outcome: _RunOutcome) -> None: ...
    def mark_delivered(self, evaluation_id: str) -> None: ...
    def remove(self, evaluation_id: str) -> None: ...
    def load(self, evaluation_id: str) -> StoredEvaluation: ...
    def scan(self, *, now: datetime) -> tuple[RecoverableEvaluation, ...]: ...   # also prunes

class ArtifactRedeemer(Protocol):
    def redeem(self, outcome: _RunOutcome) -> _RunOutcome: ...                   # body in memory
    def redeem_to_file(self, outcome: _RunOutcome, staging: Path) -> Path: ...   # body on disk, verified
```

- `FilesystemRecoveryStore` (`screamingface/_recovery/store.py`) implements `RecoveryStore`.
- `Url4CloudTransport` / `AsyncUrl4CloudTransport` implement `ArtifactRedeemer` by delegating to
  `_materialize_*` `[existing packages/screamingface/src/screamingface/_engine/transport.py:1299]`
  and a new `_fetch_artifact_to_file_*` that applies the same size and sha256 checks
  `[existing packages/screamingface/src/screamingface/_engine/transport.py:1237]`.
- `SyncRunTransport` / `AsyncRunTransport` do not change (17 fakes depend on them).
  `[existing packages/screamingface/src/screamingface/_core/ports.py:103]`

## K1 — runner → RecoveryStore.open_evaluation (data, in-process)

- **Shape:** `EvaluationManifest` = the EVALUATION_RECORD fields (`erd.md` §2.2) without `state`.
- **When:** after preflight (`runner.py:98`) and before the first `transport.run`. Then each
  Candidate gets `recovery_slot` (same pattern as `_with_answer_seed`, `model.py:171`).
- **Policies:** one call per Evaluation. Synchronous. No retry.
- **Failure:** `RecoveryStoreUnavailable` → the runner logs one WARNING, clears every slot to
  `None`, and continues. The Evaluation never fails here.
- **Tests:** RS-7, RE-4, RE-12.

## K2 — transport → RecoveryStore.record_run (data, in-process)

- **Shape:** `(slot, candidate.name, _RunOutcome)` with `artifact` still set, or with the inline
  `result_body`. The hook stamps `trace_id` itself, because `run()` adds it only after
  `_run_reconnecting` returns (`transport.py:193`).
- **When:** inside `_run_reconnecting`, after `_run_connected` returns a succeeded outcome, and
  before `_materialize_*` (`transport.py:284`, `:677`). Only when `candidate.recovery_slot` is
  set and the store is set.
- **Policies:** called once per run. One writer per file (one index per thread). Atomic replace.
  The async transport writes through `asyncio.to_thread`, so `fsync` never blocks the event loop
  or the WebSocket heartbeats. `[proposed]`
- **Failure:** any `OSError` → one WARNING per Evaluation, and the run continues to
  materialize. Never raised to the caller.
- **Ordering guarantee:** the record exists before the first `GET /artifacts/{id}`.
- **Tests:** RE-2, RE-3, RE-5, RS-2.

## K3 — runner → RecoveryStore.mark_delivered / remove (data, in-process)

- **When:** `mark_delivered` after `report_from_outcomes` returns, and in the
  `raise_candidates_failed` path when a partial Report exists. `remove` when no Candidate
  succeeded (RE-D3). Nothing on abort.
- **Policies:** idempotent.
- **Failure:** logged at WARNING. Never raised. The Report is returned anyway.
- **Tests:** RE-6, RE-7, RE-9, RE-10, RS-10.

## K4 — Client construction → RecoveryStore.scan → stdout (data + output)

- **When:** the first `Client` / `AsyncClient` construction in the process, unless
  `SCREAMINGFACE_RECOVERY_NOTICE=0`.
- **Shape (output):** one line; text in `prd/recovery-notice.md` §3.
- **Policies:** filesystem only. ≤ 50 ms for 200 records. Prunes as specified in RS-D6 and RS-D7.
- **Failure:** any exception → DEBUG log, no output, construction continues.
- **Tests:** RN-1 to RN-7, RN-10, RN-11.

## K5 — recover service → RecoveryStore.load / remove (data, in-process)

- **Shape:** `StoredEvaluation(manifest, runs: Mapping[int, StoredRun])`, validated.
- **Failure:** `recovery_not_found`, `recovery_record_invalid`, `recovery_record_unsupported`,
  all raised before any network call.
- **Tests:** RS-4, RS-11 to RS-13, RC-21.

## K6 — recover → Engine `POST /token` (sync HTTP, existing)

- **Shape:** `{"token": "<text>"}` `[existing packages/screamingface/src/screamingface/_engine/transport.py:858]`.
- **Policies:** one fresh mint per artifact fetch, inside the retry loop
  `[existing packages/screamingface/src/screamingface/_engine/transport.py:1299]`. The Client is
  the one for `manifest.engine_url` (RC-H3).
- **Failure:**
  - connection refused on a loopback origin → `local_stack_not_running`, with a hint
    (`[stated ans:Q11]`);
  - Access 401/403 → the existing auth error; the record stays;
  - other network errors → `EngineUnavailableError`; the record stays.
- **Tests:** RC-8, RC-16, RC-17.

## K7 — recover → Engine `GET /artifacts/{id}` (sync HTTP, existing)

- **Request:** `URL4-Capability: <fresh token>`.
  `[existing apps/screamingface-engine/src/screamingface_engine/rest/artifacts.py:97]` The Engine
  accepts any valid capability token.
- **Response:** `200 application/octet-stream` with the exact bytes, or `404` problem+json
  "Unknown artifact".
- **Policies:** retries `(0.0, 0.2, 0.8)` s on `httpx.HTTPError`
  `[existing packages/screamingface/src/screamingface/_engine/transport.py:1265]`. Never buffer
  past `size_bytes`. Verify size and sha256 before decode. File mode streams the bytes to
  `<evaluation dir>/tmp/<sha256>.<uuid>.part`, verifies them, and then `json.load`s from the file.
- **Failure:** `404` → `result_expired` for that Candidate (message: age from `completed_at` and
  the local 48 h rule); mismatch → `result_integrity_mismatch` (permanent); `ENOSPC` →
  `recovery_disk_full`. The staging file is removed on every exit.
- **Tests:** RC-1, RC-2, RC-4, RC-5, RC-9, RC-12, RC-13.

## K8 — export and recover-to-file → streaming writer → filesystem (data)

- **Shape:** the `report.v1` bytes, identical to `to_json()` (`prd/report-json-writer.md`).
- **Policies:** write to a temporary sibling, `fsync`, `os.replace`. Resolve symlinks first. Keep
  the old file's mode, or use `0o666 & ~umask` for a new file.
- **Failure:** any exception → remove the temporary file, keep the old target, and raise.
- **Tests:** RW-1 to RW-6, EX-1 to EX-6, RC-6.

## K9 — `screamingface up` → Engine settings and run env (configuration)

- **Shape:** `EngineSettings(artifacts_dir=D)` and `run_env["URL4_CLOUD_ARTIFACTS_DIR"] = D`,
  where `D = <data_dir>/artifacts`, unless the env var is already set.
- **Invariant:** the two values are equal (OME-929).
- **Tests:** LA-0 to LA-2, LA-4.

## K10 — CLI → recover service (in-process)

- **Shape:** `screamingface recover --list [--all]`; `screamingface recover <id> [--to PATH]`.
  Exit codes 0 / 2 / 1 (`prd/recover-evaluation.md` §3).
- **Policies:** the CLI always uses recover-to-file. It prints the path, and for a partial
  result it also prints the failed Candidates.
- **Tests:** RC-18, RN-8.

## K11 — dependency rules (layering)

- `_core/ports.py` imports no adapter. `[stated prompt]` (CLAUDE.md: the core defines ports)
- `_recovery/` imports `_core`, `_evaluation`, and `report`. It never imports `_engine`. It reaches
  the Engine only through `ArtifactRedeemer`.
- `_engine/transport.py` imports only the `RecoveryStore` port, never `_recovery/store.py`.
- `Client` (composition root) wires `FilesystemRecoveryStore` into the transport and the runner.
- **Enforcement:** a unit test parses the imports of every module in `_recovery/` and `_engine/`
  with `ast`, and fails on a forbidden edge. Test ID `ARCH-1` (in `test-plan.md`).
