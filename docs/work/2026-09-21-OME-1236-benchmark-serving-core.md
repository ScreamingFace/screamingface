---
ticket: OME-1236
stack: screamingface-engine
status: done
started: 2026-09-21
finished: 2026-09-21
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

- **Actual files:** `spine/serving.py` + `spine/__init__.py` + `test_spine_serving.py`
  (PR #1003); `contracteval/{runtime,definition}.py` + migration goldens (PR #1004);
  `medxpert/{runtime,definition}.py` + migration goldens (PR #1005). Stack sits on
  PR #1002 (`OME-1246`, undeclared contracteval failure codes — found because the
  pre-push gate replays the full suite and main was red).
- **Commits:** per PR branch — core `6fda91e4` + test hardening `15fd6720`;
  contracteval `af7d9eb8` + note fix `f3c74b5b`; medxpert `e97de4e8` + review
  hardening + this close-docs commit.
- **Gates:** engine pre-push gate green (full suite); 23 spine contract tests;
  migration goldens replayed against pre-migration code on both sides (review);
  review verdict: stack mergeable, zero code blockers.
- **Deviations:**
  - The decode ladder was NOT extracted: `check` (and each board's payload
    decode) stayed board-owned — the two donors' checks are genuinely different
    exams, and the spine deliberately does not average over them. The plan's
    "seven functions + decode ladder" landed as "six shared + check envelope
    helper (`candidate_record`)".
  - contracteval kept `runtime.py` thin wrappers (`_cases`, `preflight`) to
    preserve prior tests' seams, and `case_evaluation.py` was never touched
    (its binder/decoder are exam-specific validation, not plumbing).
  - medxpert behavioral delta (declared in PR #1005): the cases route now runs
    the memoized preflight before first serve.
  - Review-driven hardening: booklet Content-Type pinned, operations-bearing
    record order pinned, medxpert's definition-error preflight class pinned
    (mutation-verified).
