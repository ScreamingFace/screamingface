---
ticket: OME-1038
stack: repo
status: done
started: 2026-09-12
finished: 2026-09-14
---

# OME-1038 — Answer-seed design session: proposal for declaring per-run seeds

## Intent

A run cannot declare answer seeds, so a published score is one sample presented as the
truth — no variance, no exact replay. Phase 1 (done, this branch) delivered the design
spec; the owner approved the seed-per-run shape on 2026-09-12 ("just code it"), so
phase 2 implements it in `apps/screamingface-engine`: an optional per-run answer seed
that renders a `seed` URL4 param on every candidate call (mirroring the judge idiom)
and is named in the run's published record. A run declaring nothing renders
byte-identical expressions to today — zero replay fixtures invalidated.

## Planned changes

- `docs/spec/2026-09-12-answer-seeds-spec.md` — the design proposal (done).
- Run request schema: optional `answer_seed` field (exact file per recon).
- Candidate expression rendering: inject `("seed", str(answer_seed))` when declared,
  nothing when not (exact file per recon).
- Run record/report: `answer_seed` field naming the sitting (exact file per recon).
- Tests beside the existing schema / rendering / record tests.

## Test plan

- RED first: (1) run declaring `answer_seed=7` renders candidate calls carrying
  `seed=7` in the expression text; (2) run declaring nothing renders expression text
  byte-identical to the pre-change golden — INVARIANT: absence is the default, no
  default seed value exists; (3) the run record round-trips `answer_seed` (declared →
  named; undeclared → absent/None); (4) boundary: invalid seed (non-int / negative if
  schema forbids) rejected at the schema.

## Acceptance

- Spec in `docs/spec/` (done) + owner decision recorded (done — seed-per-run).
- Declared seed reaches every candidate call's params and the run record names it.
- Undeclared runs: rendered expression text byte-identical; existing tests and
  fixtures pass unmodified.
- No file under `benchmarks/spine/` changes (the spec's deletion test).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the port ripple: `runner/request_parameters.py`
  (`apply_answer_seed`), `job_env.py` (env pair + `WRITTEN_BY_APP`), `ports.py`,
  `adapters/inprocess.py`, `adapters/queue_runner.py`, `runner_queue.py`,
  `rest/routes.py` (`X-Answer-Seed`), `runner/main.py`, `runner/connector.py`;
  new `tests/unit/test_answer_seed_threading.py` (21 tests).
- **Commits:** 98e6fdb3 docs(spec) — the proposal; 343b8ef8 feat(screamingface-engine) — the seam.
- **Gates:** run_gates.py screamingface-engine ALL GREEN (ruff check/format, pyright,
  layering, pytest 2831 passed / cov ≥80). Append-only check waived ONCE with owner
  approval (2026-09-14) for 4 fake-signature widenings.
- **Review round (2026-09-15, owner-relayed):** two confirmed findings fixed. (1) The
  ambient seed reached benchmark-authored judge calls (HealthBench/GDPVal pin no seed) —
  grading identity varied per sitting; fixed by scoping the seed to the Candidate
  invocation (`candidate_scope.py` ContextVar, raised in `candidate_adapter.py`, read in
  the connector), pinned by the judge-never-seeded test. (2) A seed on a route whose
  gateway contract lacks `seed` (Anthropic) failed mid-run behind mocks; fixed SDK-side —
  the model-parameters preflight now validates `seed` for every candidate model when a
  seed is declared, refusing pre-spend. Seeded-egress tests reshaped through the
  candidate route (owner-approved waiver).
- **Deviations:** (1) `RunSummary.answer_seed` dropped — YAGNI; the seed already lives in
  the Job env and every request body; the record-side field belongs to the SDK sub-issue.
  (2) 4 prior test fakes widened to accept the new port kwarg (owner-approved; assertions
  untouched). (3) SDK exposure (`Client.evaluate(seed=...)`, report field) is a separate
  `py-screamingface` sub-issue per the cross-cutting rule — not in this unit.
