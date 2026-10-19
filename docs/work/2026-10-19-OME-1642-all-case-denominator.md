---
ticket: OME-1642
stack: python (apps/screamingface-engine)
status: done
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

## Outcome

Status: done (code, review fixes, V7). Owner decisions applied: D1–D6 as recommended; required
`failure_policy` with owner-approved test edits; policy-aware updates of existing tests; gdpval-text
failed Case counts 0; renderer writes `failure_policy="TODO"`; rebase onto a87da68c1 added five
OME-1602 rows, all Group A (`withhold`).

Totals: 82 imported rows + medxpert → 66 `withhold` (65 + medxpert), 17 `coverage_declare`.
66 revisions move; the 17 `coverage_declare` revisions are byte-identical.

Commits (oldest last):
- `995323d3c` docs: describe both failure policies where the old graded-only rule was stated
- `b283cc27e` fix(screamingface-engine): score live progress over the Cases the failure policy counts
- `7e475de2f` test(screamingface-engine): move the withhold Benchmarks' revision literals (owner-approved)
- `6fe3790e8` test(screamingface-engine): pin the OME-1642 policy and revision tables on the rebased base
- `7400d42a8` docs: define both failure policies in the glossary and the SDK report
- `7a5dfd9e1` feat(screamingface-engine): give every withhold Benchmark a new revision
- `30c167b9b` feat(screamingface-engine): score withhold Benchmarks over every selected Case
- `497a54c6a` docs(screamingface-engine): apply the construction-only test rule to U2 call sites
- `045e3806f` feat(screamingface-engine): declare a failure policy on every Benchmark row
- `b6254f2da` docs(screamingface-engine): spec and plan for the all-Case score denominator

Gates: `run_gates.py screamingface-engine` and `screamingface` green without `--skip-append-only`
(32+4 existing test files approved in `.claude/test-change-approvals/OME-1642.json`); inspect lane
2359 passed. Design review (Opus): accept-with-fixes; all 13 findings applied (main one: the live
progress score used the old denominator).

V7 (2026-10-19, local kind stack built from this branch, gateway cache = copy of production):
every published FrontierScience and GDPval-text url4 replayed on the new revision. 27 replays,
0 mismatches against the OME-1642 attachment's expected all-Case scores; ~60,000 calls, all cache
hits, 0 misses, $0.

FrontierScience (`fb33b1e6a2cf0c12` → `826050de44778515`):

| Candidate | Published | All-Case (V7) | Coverage | Cache hits |
| --- | --- | --- | --- | --- |
| claude-opus-5.5 | 0.7396 | 0.6287 | 0.85 | 300 |
| claude-fable-5.1 | 0.7390 | 0.5958 | 0.8063 | 294 |
| member_synth_trio | 0.6969 | 0.6969 | 1.0 | 800 |
| sota_cheap_synth | 0.6855 | 0.6813 | 0.9938 | 797 |
| external_synth_trio | 0.6815 | 0.6730 | 0.9875 | 796 |
| member_synth_pair | 0.6730 | 0.6730 | 1.0 | 640 |
| gemini-3.8-flash | 0.6637 | 0.6637 | 1.0 | 320 |
| gpt-6-astra | 0.6586 | 0.6586 | 1.0 | 320 |
| panel_2026q3_opus55_synth | 0.6549 | 0.6508 | 0.9938 | 797 |
| sota_open_only | 0.6450 | 0.6450 | 1.0 | 800 |
| qwen3.8-2.4t-a95b | 0.6105 | 0.5952 | 0.975 | 316 |
| glm-5.3 | 0.5969 | 0.5894 | 0.9875 | 318 |
| deepseek-v4-pro-0813 | 0.5790 | 0.5790 | 1.0 | 320 |
| grok-4.7 | 0.5780 | 0.5744 | 0.9938 | 318 |

GDPval-text (`2e839377e3ee28d4` → `f6ea752427e71362`):

| Candidate | Published | All-Case (V7) | Coverage | Cache hits |
| --- | --- | --- | --- | --- |
| member_synth_trio | 0.8287 | 0.8205 | 0.9902 | 4823 |
| sota_cheap_synth | 0.8144 | 0.8064 | 0.9902 | 4823 |
| sota_open_only | 0.8142 | 0.7743 | 0.951 | 4599 |
| panel_2026q3_opus55_synth | 0.8082 | 0.7923 | 0.9804 | 4823 |
| member_synth_pair | 0.8036 | 0.7958 | 0.9902 | 4721 |
| claude-fable-5.1 | 0.7947 | 0.7870 | 0.9902 | 4519 |
| gemini-3.8-flash | 0.7854 | 0.7854 | 1.0 | 4549 |
| qwen3.8-2.4t-a95b | 0.7784 | 0.7784 | 1.0 | 4549 |
| glm-5.3 | 0.7769 | 0.7465 | 0.9608 | 4364 |
| deepseek-v4-pro-0813 | 0.7692 | 0.7692 | 1.0 | 4549 |
| gpt-6-astra | 0.7612 | 0.7612 | 1.0 | 4549 |
| claude-opus-5.5 | 0.7500 | 0.6838 | 0.9118 | 4174 |
| grok-4.7 | 0.1187 | 0.1187 | 1.0 | 4549 |

CI follow-up (PR #1469): the SDK e2e golden for gdpval-text pinned the old revision and the
graded-only score. Regenerated from a local replay of the committed snapshot (same setup as CI):
revision `f6ea752427e71362`, new expression_sha, final_score 0.8044 → 0.6435 (= 0.8044 × 20/25);
statuses, failure codes and coverage unchanged. The refresh tool refuses revision moves by design,
so the values were set from the replay, as 967ada253 did.

Deviations: the five OME-1602 rows were classified by the spec §5 criteria (not in the original
table); `failure-ladder-and-policy.png` is not re-exported (no draw.io CLI) — the `.drawio` source is
updated. Follow-ups: re-run published entries on the new revisions after deploy (D5); per-metric
rules for the whole-run rows and healthbench-worst30 (D3/D4); per-row rules for refusal-measuring
rows (D2).
