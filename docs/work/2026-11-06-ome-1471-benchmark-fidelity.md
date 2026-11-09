---
ticket: OME-1471
stack: screamingface-engine
status: done
started: 2026-11-06
finished: 2026-11-09
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

- Records live under the Engine's `docs/` (owner, 2026-11-09), not repo-root `docs/`.

- `docs/spec/2026-11-06-OME-1471-benchmark-fidelity.md` — record format, fingerprint rule,
  verdict/severity vocabulary, check-script contract, agent contract.
- `docs/plan/2026-11-06-OME-1471-benchmark-fidelity.md` — the three-PR carve, step by step.
- `apps/screamingface-engine/docs/benchmarks-fidelity/README.md` — index: verdict table + how to read a record.
- `apps/screamingface-engine/docs/benchmarks-fidelity/TEMPLATE.md` — record skeleton (front matter + dimension table).
- `apps/screamingface-engine/scripts/fidelity_check.py` + `tests/unit/test_fidelity_check.py` +
  `tests/unit/inspect/test_fidelity_check_catalogue.py` + a `fidelity-check` justfile recipe.
- `.claude/agents/sf-benchmark-fidelity.md` — the audit agent.
- `.claude/agents/sf-code-review.md` — one Lane 2 line; one line in each Engine onboarding doc.
- `apps/screamingface-engine/docs/benchmarks-fidelity/ifeval.md` — the calibration record.
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

- **Actual files:** as planned, plus `tests/unit/inspect/test_fidelity_check_catalogue.py` (the with-extra pin to the fingerprint golden) and the `fidelity-check` justfile recipe. Records live under `apps/screamingface-engine/docs/benchmarks-fidelity/` (owner, 2026-11-09, spec §1 S6).
- **Commits:** d87c26f01 spec + plan + glossary · 00f57020c mirror link · 3227278d5 records under the Engine's docs · 8fee5948d pinned reference links · 3679db897 check script + tests + template + README · 064d3964f agent + Lane 2 + onboarding lines · 523f89e93 IFEval record · (this commit) ledger + mirror.
- **Gates:** pre-push `run_gates.py screamingface-engine` green on every push (ruff, format, pyright, layering, pytest with coverage); `run_gates.py repo` green. Relevant tests: `tests/unit/test_fidelity_check.py` 19 passed; `tests/unit/inspect/test_fidelity_check_catalogue.py` + `test_benchmark_fingerprints.py` 97 passed with the extra; `just engine fidelity-check` → 1 fresh (ifeval), 93 no record, exit 0.
- **Evidence from the audits:** real IFEval audit → `comparable-to-paper`, bound 2/541, all seven dimensions with evidence; blind planted run (CommaChecker accepting one comma in a scratch copy) → exactly one undeclared score-changing deviation naming CommaChecker, bound 66/541, verdict `not-comparable`, no key in the agent's environment (report in the PR #1700 body).
- **Deviations:** six from the ticket, listed in spec §1 (S1 fingerprint = computed fingerprint + harness_url; S2 live table from the script; S3 one PR; S4 origin vocabulary; S5 IFEval's declared deviation; S6 records under the Engine's docs). Owner call pending: the published IFEval checker is non-deterministic on langdetect rows (record's Upstream notes); not a deviation, surfaced for a possible Named Deviation.
- **Owner-verify:** review the record's evidence; merge; move OME-1471 to Done by hand (no automation here).
