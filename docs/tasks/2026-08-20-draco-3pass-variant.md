---
id: none
linear_url: none — owner decision, no Linear issue for this unit
status: in_progress
type: feature
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-08-20
closed:
---

# Add the `draco-3pass` DRACO board (3 judge passes, cache-seeded replay)

The `draco-cache-seed` archive covers grading rounds 1–3 only, so canonical DRACO's
fifth-pass re-run still pays ~116,270 judge calls. This unit adds a second DRACO board
that runs exactly the three archived passes, so re-running the archived candidates is
served fully from the shared response cache.

Locked decisions (owner-approved 2026-08-20, spec `docs/spec/2026-08-20-draco-3pass-variant.md`):

1. Benchmark id `draco-3pass`, title "DRACO 3-Pass", `JUDGE_PASSES=3`.
2. Mirror the HealthBench board factory: new `draco/exam.py` (Routes / DracoExam /
   revision fingerprint / protocol builder / `draco_benchmark` factory);
   `draco/definition.py` becomes the boards module.
3. Canonical `draco` revision FROZEN at `66a463248586b277` — byte-identical behavior.
4. Variant reads the SAME `assets/draco/` dataset; own revision `b8c8afd8f9dddca0`.
5. No Linear ticket (owner decision).
