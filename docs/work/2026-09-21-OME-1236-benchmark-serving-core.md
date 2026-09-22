---
ticket: OME-1236
stack: screamingface-engine
status: in_progress
started: 2026-09-21
finished:
---

# OME-1236 — Extract the shared benchmark serving core; migrate contracteval + medxpert

## Intent

Every hand-built deterministic board re-types ~600–700 lines of serving plumbing
(routes, memoized bundle preflight, case serving, reply decode) that carries no
benchmark content — contracteval and medxpert share the same seven `runtime.py`
functions name-for-name. Extract that layer into `benchmarks/spine/` so a new
board declares only its dataset, prompt, grading, and scoring, and the
"hand-wired slot never invoked" bug class (PR #865 finding) is deleted
structurally.

## Planned changes

Three stacked PRs:

1. **PR 1 — serving core** (`OME-1236-benchmark-core`):
   - new `apps/screamingface-engine/src/screamingface_engine/benchmarks/spine/serving.py`
     (name may adjust to spine conventions) — the seven shared functions
     (`install / preflight / _cases / _check / _aggregate / _case_count / _read`)
     generalized over a board declaration + the decode ladder.
   - contract tests under `apps/screamingface-engine/tests/`.
2. **PR 2 — contracteval on the core** (`OME-1236-migrate-contracteval`):
   - delete `contracteval/runtime.py` + `case_evaluation.py` plumbing; declaration
     replaces them; `definition.py` route-building half moves onto the core.
   - golden replay test: `compute_revision` + route protocol byte-identical.
3. **PR 3 — medxpert on the core** (`OME-1236-migrate-medxpert`):
   - same shape; proves per-board deviations (`_cot_prompt`, `_reasoning_text`)
     stay expressible.

## Test plan

- RED first per PR. Core contract tests: a toy board declaration is served
  (routes built, preflight memoized + actually invoked, cases served sealed,
  replies decoded, scores aggregated); error paths (bad bundle → preflight
  failure, undecodable reply → failure vocabulary row).
- Migration PRs: golden replay — revision + protocol bytes identical before/after
  (INVARIANT: an expression addressed to a current revision resolves to
  byte-identical protocol).
- Sealed-envelope invariant: cases served without answers; gold read only after
  candidate reply.
- Per user instruction: only related unit tests run locally; full gates ride CI
  on the draft PRs.

## Acceptance

- New board surface ~300–400 lines; contracteval + medxpert plumbing deleted,
  boards keep byte-identical protocol.
- Unmigrated boards (ifeval, gdpval, healthbench, draco, ensemble) untouched.
- Three draft PRs open, stacked, each ≤ ~700 LoC.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
