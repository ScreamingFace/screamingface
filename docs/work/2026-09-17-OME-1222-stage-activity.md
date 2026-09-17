---
ticket: OME-1222
stack: screamingface-engine
status: done
started: 2026-09-17
finished: 2026-09-17
---

# OME-1222 — Benchmark stage activity

## Intent
Expose work between model calls through the existing ephemeral activity stream. Owner requested a draft Engine PR; the approved OME-887 stage vocabulary and OME-1161 plugin provide the contract and infrastructure.

## Planned changes
- Benchmark-owned optional observation port and typed handler wrapper; explicit stage declarations in shipped runtime installers and candidate adapter.
- Small generic access/guard extension to observations; activity implements the benchmark port, retaining run policy and heartbeat ownership.
- New regression tests and spec/plan/task artifacts. No Client or URL4 changes.

## Test plan
RED tests for stage lifecycle, sync/async shape, failure isolation, cancellation, off/nested runs, node attachment, concurrent attribution and installer coverage. Existing Engine suite remains unchanged.

## Acceptance
All six stage kinds have explicit owners, optional observers cannot change execution, private payloads stay out of attributes, and full Engine gates pass. Open a draft against main; no deployment or paid provider calls.

## Outcome
- **Actual files:** benchmark stage port; explicit wrappers in five built-in runtime families, imported single-shot runtime and candidate adapter; activity adapter; 12 generic observation access/guard lines; three new test modules; spec/plan/task artifacts.
- **Commits:** recorded by this PR's feature commit (Refs: OME-1222).
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main` — ALL GATES GREEN (append-only, Ruff check/format, Pyright, layering, full pytest/coverage). Coverage report rounds to 94%. 33 new parametrized regression cases.
- **RED evidence:** missing stage module; eight missing-registration/node-log regressions; both sync/async cleanup-interruption cases failed before their fixes. Healthy full/off one-case runs pass on all seven built-in boards with byte-equivalent decoded full results and identical provider requests.
- **Review:** independent Standards and Spec reviews clear after fixing multi-observer cleanup and adding successful-board parity. Existing tests unchanged.
- **Wisdom:** explicit owner declarations avoid route inference; the optional domain port keeps plugin imports out of core. No payload data crosses the port, no new dependency or storage, no scoring changes. Existing fault guard and timer cleanup are reused.
- **Deviations:** minimal generic registry access/guard required because merged ports cover only model calls; execution core remains benchmark/activity-agnostic. New scope unwinding handles cancellation across multiple observers. Imported adapter installation tested without optional scorer packages; not a production-load or widget test.
- **Delivery:** draft PR against main; implementation complete, ticket remains In Progress while draft, then In Review when marked ready.

Owner correction, 17 September: draft PRs remain In Progress in Linear; corrected the issue and task mirror.
