---
ticket: OME-1013
stack: screamingface
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1013 — Assemble local Client diagnostic receipts

> This `done` status records the completed receipt-capture iteration, not closure of the parent
> Linear issue. The authoritative ticket mirror remains `in_progress` until the full PR lands.

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
  candidate executions; valid trace ids are retained when observed, but private Event stream
  topics are not published as `run_id`.
- Normal receipts contain no prompts, responses, URL4, notebook source, raw logs, secrets,
  environment dumps, source lines, locals, or absolute paths.
- Capture is bounded, local-only and fail-open; normal Python exception behavior is unchanged.

## Outcome

- **Actual files:** the approved spec/plan/task/ledger; public immutable receipt and lookup API;
  private allow-listed capture, bounded store, and Evaluation context modules; sync/async Recipe
  and URL4-replay workflow integration; shared fail-open observer plumbing; safe early candidate
  identity and relative-route breadcrumbs; concise exception handoff; changelog and public-surface
  snapshot; behavior suites plus a focused shared fixture module; and the owner-approved prior-test
  amendments below.
- **Commits:** `edbe0f68 feat(screamingface): add local diagnostic receipts` plus the final
  `fix(screamingface): complete diagnostic evidence contract` review pass.
- **Gates:** `run_gates.py screamingface --skip-append-only` ALL GATES GREEN — Ruff lint and
  formatting, Pyright (0 errors), the complete pytest suite with ≥95% coverage, deterministic
  notebook validation, wheel/sdist build, and distribution validation. Final focused diagnostic,
  progress and capture suites: 94 passed.
- **Deviations:** `--skip-append-only` was used only for the four owner-approved contract updates
  documented below. Notebook extras were installed in this worktree's private `.venv` to run the
  declared Pyright and notebook gates. No dependency or lockfile changed.
- **Review:** the merged `OME-1004` wire contract remains an adapter concern: its singular
  correlation/candidate shape does not narrow this receipt's multi-execution evidence. `OME-1014`
  owns projection, Turnstile/widget communication, retry semantics, 64 KiB shaping, and disk
  fallback. `OME-967` remains the source of complete trace correlation and is not a blocker. The
  final review removed arbitrary typed server messages, guarded diagnostic-note attachment,
  retained safe caller identity before preparation, restricted operation breadcrumbs to bounded
  relative URL4 routes, and extracted observer fan-out from the runner.

## Owner-approved prior-test amendments

The append-only gate correctly stopped on four intentional contract updates. The owner explicitly
approved the first two on 2026-08-26 and the final two on 2026-08-27 before the gate was resumed
with `--skip-append-only`:

- `tests/public_surface_snapshot.json` records the new public `sf.diagnostics` module and
  `DiagnosticReceipt` value. The accompanying changelog entry makes the API change explicit.
- `tests/test_draco_vertical_slice.py` permits the transport's optional event observer even when
  user progress/callbacks are off. Local diagnostics need that private observer to retain
  observable `run_id`/`trace_id` evidence; the transport port already permits `None | callable`.
- `tests/test_diagnostic_capture.py` replaces the earlier assertion that retained arbitrary
  peer-supplied WebSocket close-reason text. Owner approval on 2026-08-27 removed that unsafe field
  and retained only the numeric close code.
- `tests/test_evaluation_diagnostics.py` uses one fixture-module alias instead of thirteen repeated
  imports. Owner approval on 2026-08-27 covered this mechanical, assertion-preserving reduction from
  478 to 442 lines so the file satisfies the stack's ≤450-line rule.

No behavior assertion was deleted or skipped, and the complete package suite remained green after
the approved contract correction.
