---
ticket: OME-1013
stack: screamingface
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1013 — Assemble local Client diagnostic receipts

## Intent

Give early ScreamingFace users a concrete, privacy-safe artifact when an Evaluation raises or is
interrupted. The Client captures only facts it already holds, preserves the original Python
exception, keeps receipts in bounded memory, and exports only after an explicit user action. The
future report-intake mapping remains a separate adapter and is not designed into the Client core.

## Planned changes

- `docs/spec/2026-08-26-OME-1013-client-diagnostics.md`
- `docs/plan/2026-08-26-OME-1013-client-diagnostics.md`
- `packages/screamingface/src/screamingface/diagnostic.py`
- `packages/screamingface/src/screamingface/diagnostics.py`
- `packages/screamingface/src/screamingface/_diagnostics/`
- `packages/screamingface/src/screamingface/_evaluation/runner.py`
- `packages/screamingface/src/screamingface/__init__.py`
- focused new tests under `packages/screamingface/tests/`

## Test plan

- RED: immutable receipt serialization/export, stable bytes, and strict schema boundaries.
- RED: count-and-byte-bounded store, distinct failure identities, lookup and eviction.
- RED: allow-listed exception/environment/config capture and explicit forbidden-data assertions.
- RED: synchronous and asynchronous Evaluation failure capture with original exception identity and
  cause chain preserved.
- RED: `KeyboardInterrupt` receipt followed by the same interrupt; `SystemExit` and
  `GeneratorExit` bypass; `asyncio.CancelledError` produces a distinct cancelled receipt.
- RED: partial `Report` outcomes create no diagnostic receipt.
- RED: diagnostic capture failures never replace the operation's original exception.

## Acceptance

- `sf.diagnostics.last()` and `sf.diagnostics.get(ref)` return immutable local receipts.
- Receipts support `to_dict()`, `to_json()`, and explicit `.export()` using the Report convention.
- One top-level failed Evaluation produces one unique receipt containing separate observable
  candidate executions; each retains the existing public Event `run_id` when observed.
- Normal receipts contain no prompts, responses, URL4, notebook source, raw logs, secrets,
  environment dumps, source lines, locals, or absolute paths.
- Capture is bounded, local-only and fail-open; normal Python exception behavior is unchanged.

## Outcome

- **Actual files:** the approved spec/plan/task/ledger; public immutable receipt and lookup API;
  private allow-listed capture, bounded store, and Evaluation context modules; sync/async Recipe
  and URL4-replay workflow integration; concise exception handoff; changelog and public-surface
  snapshot; three new behavior suites plus a focused shared fixture module; the one approved
  transport-fixture contract amendment below.
- **Commits:** `feat(screamingface): add local diagnostic receipts` (this unit).
- **Gates:** `run_gates.py screamingface --skip-append-only` ALL GATES GREEN — Ruff lint and
  formatting, Pyright (0 errors), the complete pytest suite with ≥95% coverage, deterministic
  notebook validation, wheel/sdist build, and distribution validation. Final focused diagnostic
  suite: 29 passed.
- **Deviations:** `--skip-append-only` was used only for the two owner-approved contract updates
  documented below. Notebook extras were installed in this worktree's private `.venv` to run the
  declared Pyright and notebook gates. No dependency or lockfile changed.
- **Review:** the merged `OME-1004` wire contract remains an adapter concern: its singular
  correlation/candidate shape does not narrow this receipt's multi-execution evidence. `OME-1014`
  owns projection, Turnstile/widget communication, retry semantics, 64 KiB shaping, and disk
  fallback. `OME-967` remains the source of complete trace correlation and is not a blocker.

## Owner-approved prior-test amendments

On 2026-08-26 the append-only gate correctly stopped on two intentional contract updates. The
owner explicitly approved both before the gate was resumed with `--skip-append-only`:

- `tests/public_surface_snapshot.json` records the new public `sf.diagnostics` module and
  `DiagnosticReceipt` value. The accompanying changelog entry makes the API change explicit.
- `tests/test_draco_vertical_slice.py` permits the transport's optional event observer even when
  user progress/callbacks are off. Local diagnostics need that private observer to retain
  observable `run_id`/`trace_id` evidence; the transport port already permits `None | callable`.

No assertion was deleted or skipped, and the complete package suite remained green before the
official gate run.
