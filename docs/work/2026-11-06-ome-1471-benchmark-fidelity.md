---
ticket: OME-1471
stack: screamingface-engine
status: in_progress
started: 2026-11-06
finished:
---

# ome-1471-benchmark-fidelity — Fidelity Records, check script, audit agent, IFEval calibration

## Intent

OME-1471 gives every Benchmark a fidelity record: a reviewed markdown file saying whether our
exam is comparable to the paper's, backed by evidence and a fingerprint of the references the
verdict rests on. One PR (owner, 2026-11-06) ships the design (spec + plan + glossary), the record
format, the check script a dev runs to list which records are missing or stale, the audit agent,
the reviewer line, and the IFEval calibration record with its planted-deviation evidence. Unblocked 2026-11-06:
OME-1455 (Benchmark Provenance fields, incl. the pinned `harness_url`) is Done.

## Planned changes

- `docs/spec/2026-11-06-OME-1471-benchmark-fidelity.md` — record format, fingerprint rule,
  verdict/severity vocabulary, check-script contract, agent contract.
- `docs/plan/2026-11-06-OME-1471-benchmark-fidelity.md` — the three-PR carve, step by step.
- `docs/benchmarks-fidelity/README.md` — index: verdict table + how to read a record.
- `docs/benchmarks-fidelity/TEMPLATE.md` — record skeleton (front matter + dimension table).
- `apps/screamingface-engine/scripts/fidelity_check.py` + `tests/unit/test_fidelity_check.py` +
  `tests/unit/inspect/test_fidelity_check_catalogue.py` + a `fidelity-check` justfile recipe.
- `.claude/agents/sf-benchmark-fidelity.md` — the audit agent.
- `.claude/agents/sf-code-review.md` — one Lane 2 line; one line in each Engine onboarding doc.
- `docs/benchmarks-fidelity/ifeval.md` — the calibration record.
- `CONTEXT.md` — Fidelity Record, Fidelity Verdict.
- `docs/tasks/2026-10-05-OME-1471-benchmark-fidelity.md` — mirror.

## Test plan

- Check script: fresh record → `fresh`; record with an old Benchmark Revision → `stale` with
  both values; Benchmark with no record → `no record`; record whose `parity_test:` path does
  not exist → flagged; imported Benchmark whose inspect_evals version moved → `stale`;
  malformed front matter → clear error naming the file; no network call (no socket use).
- Invariant protected: a verdict is never shown as current when any fingerprint value it
  rested on has changed.

## Acceptance

- `run_gates.py screamingface-engine` and `run_gates.py repo` green.
- Check script against the real catalogue: `ifeval` fresh, the other 93 `no record`, offline.
- IFEval record: seven dimensions with evidence, declared deviation bound 2/541, verdict
  comparable-to-paper. Planted run: exactly one undeclared score-changing deviation.
- Spec + plan reviewed on the PR; ticket Scope patched to the one-PR delivery.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
