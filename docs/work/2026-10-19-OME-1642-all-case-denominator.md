---
ticket: OME-1642
stack: python (apps/screamingface-engine)
status: planned
started: 2026-10-19
finished:
---

## Intent

Mean-score Benchmarks count failed Cases as 0 and keep them in the denominator, through the
declared `withhold` failure policy. Spec: `docs/spec/2026-10-19-OME-1642-all-case-denominator.md`.

## Investigation (2026-10-19)

- Local kind stack (`~/sf-kind`, origin/main `cbce4b202`) seeded with a copy of the production
  aigateway request cache (622,779 rows, exported with `CacheSnapshotExporter`).
- Replay of the published claude-opus-5.5 FrontierScience url4 (revision `fb33b1e6a2cf0c12`):
  300 cache hits, 0 misses, $0. Score 0.7396 = production; 0 Case differences from the
  OME-1642 export. 24 failed Cases, all `content_filter` → `provider_refusal`; the inspect
  scorer graded them (20 × `0.0 empty_completion`, 4 × `I`) and the Engine dropped the grades.
  All-Case mean 0.6287.
- Replay notes: a raw url4 replay needs `GET /v1/model-parameters?model=<m>` first (dynamic
  admission); the SDK once raised `Span end cannot precede start` on a run the Engine finished.

## Planned changes

Owner approved D1–D6 as recommended (2026-10-19). Units U1–U6 in
`docs/plan/2026-10-19-OME-1642-all-case-denominator.md`: declare the policy per row (66
`withhold` = 65 imported rows + medxpert, 17 `coverage_declare`; 82 imported rows after the
rebase), the reduction, the revision pin, copy, owner-approved test
literal updates, verification.

## Test plan

Spec §8, V1–V7.

## Acceptance

Spec §6 values reproduced by the V7 replay; Group D–G revisions byte-identical.

## Outcome (fill at the end — required before COMMIT)
