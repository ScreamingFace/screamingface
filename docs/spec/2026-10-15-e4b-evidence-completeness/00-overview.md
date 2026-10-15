# E4b part 2: evidence completeness — overview

**Status:** draft, waiting for review (2026-10-15). **Epic:** E4b (OME-1290). Leaf filed at PR-open.
**Base:** branch `OME-1601-e4b-combine-extensions` (E4b part 1, PR #1409) at `0f4b9e292`. Part 2
needs part 1's evidence (`mean`, `output_missing`, the selection envelope).

## 1. Summary

The combine evidence of E4a and E4b part 1 already shows each member's value, signal, weight and
score. It does not say why a member was left out, it does not show the rank or the cut of a top-k
step, and it does not name the judge model. Epic OME-1290 asks for all three (gaps C2, D3, E3 and
E2 of the 2026-10-15 gap analysis). This part adds:

- a member status `"excluded"` with the reason `no_signal` or `no_weight`, for a member that a
  rule left out because it had no signal or no usable weight;
- a `rank` on each scored member of a `top_k@1` step, and a `cut` (`k`, `order`) on its evidence;
- the judge model (`judge_model`) on the spec and the evidence of every step that reads a judge;
- an SDK compile warning, `JudgeWriterWarning`, when the writer stage after a judge step uses the
  judge's model.

No Case answer changes. No new operator, no new failure code, no gateway change, and no new schema
id.

**Path prefixes.** `E/` = `apps/screamingface-engine/src/screamingface_engine/`,
`S/` = `packages/screamingface/src/screamingface/`, `ET/` = `apps/screamingface-engine/tests/unit/`,
`ST/` = `packages/screamingface/tests/`. Line numbers are on base `0f4b9e292`.

**Gap map** (from the epic OME-1290 gap analysis, 2026-10-15):

| Gap | Epic text | Part 2 work |
|---|---|---|
| C2 | "A missing signal: that member does not vote, and the report says why." | [member-exclusion](prd/member-exclusion.md) |
| D3 | "Missing signal excludes the member." (visible only as `null` today) | [member-exclusion](prd/member-exclusion.md) |
| E3 | "The report shows the score and the rank, including members that were dropped." | [rank-and-cut](prd/rank-and-cut.md) |
| E2 | "The writing model … is not allowed to be the thing that also computed the score." | [judge-model](prd/judge-model.md), [judge-writer-warning](prd/judge-writer-warning.md) |

## 2. Subsystems and ownership

| Subsystem | Owns | Changed by |
|---|---|---|
| Engine combine core (`E/combine/`) | evidence models, endpoint, descriptor hooks, spec | evidence-schema, member-exclusion, rank-and-cut, judge-model |
| SDK evidence and answer (`S/answer.py`, `S/combine_evidence.py`, `S/_evaluation/combine_evidence.py`, `S/_case_views.py`) | words, rows, decoder, case view | evidence-schema |
| SDK compile (`S/_evaluation/combine_spec.py`, `S/_evaluation/candidate.py`, `S/warnings.py`) | spec bytes, the warning | judge-model, judge-writer-warning |
| Contract data (`ET/data/combine_contract/`, `ST/data/schemas/`, `ST/public_surface_snapshot.json`) | v1 snapshots, url4 fixtures, evidence cases | all PRDs (owner-approved edits) |

## 3. Reading order

1. [erd.md](erd.md)
2. [prd/evidence-schema.md](prd/evidence-schema.md) (component, used by all)
3. [prd/member-exclusion.md](prd/member-exclusion.md) (P0)
4. [prd/rank-and-cut.md](prd/rank-and-cut.md), [prd/judge-model.md](prd/judge-model.md) (P1)
5. [prd/judge-writer-warning.md](prd/judge-writer-warning.md) (P2)
6. [contracts.md](contracts.md), [test-plan.md](test-plan.md)

## 4. PRD index

| PRD | Lifecycle | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|---|
| [evidence-schema](prd/evidence-schema.md) | existing | 4 / 3 / 6 | 14 |
| [member-exclusion](prd/member-exclusion.md) | existing | 4 / 3 / 8 | 18 |
| [rank-and-cut](prd/rank-and-cut.md) | existing | 3 / 2 / 5 | 13 |
| [judge-model](prd/judge-model.md) | existing | 3 / 3 / 4 | 12 |
| [judge-writer-warning](prd/judge-writer-warning.md) | planned | 2 / 1 / 6 | 11 |
| **Total** | | **16 / 12 / 29** | **68** |

## 5. Interview ledger

The prompt is the 2026-10-15 E4b gap analysis and its roadmap ("Part 2. Evidence completeness: add
a per-member drop reason (`no_signal` / `no_weight`), a `rank` field, the cut `k` and `order`, and
scorer and writer model ids with the same-model warning.").

| Id | Question | Answer | Note |
|---|---|---|---|
| Q1 | DB-4: The epic says the writing model "is not allowed to be the thing that also computed the score". What should the code enforce? | "Record ids + warn (Recommended)" | recommended (roadmap round, 2026-10-15) |
| Q2 | The combine step never sees the writer stage's model. Only the SDK sees the judge model and the writer at compile time. Where do the model ids go? | "Judge id + SDK warning (Recommended)" | recommended |
| Q3 | How should the evidence show a member that is left out because its signal or weight is missing? | "New status \"excluded\"" | **against the recommendation** ("New field, status kept") |

## 6. Global decisions [proposed]

| # | Decision | Where |
|---|---|---|
| P1 | The endpoint computes the exclusion from the plan and the answers, before the reduce step, so an abstain still shows it. The operators do not report it (the brief's proposal), because a step that abstains raises and returns no `Reduction`. | [member-exclusion](prd/member-exclusion.md) §2.1 |
| P2 | `"excluded"` exists only in the evidence record and the SDK view. The core `Answer` keeps `"answered" \| "fail"` (I-A3), so no operator and no Case answer changes. | [erd §2](erd.md) AR-I5 |
| P3 | `dropped`, the quorum and the coverage count only failures. An excluded member is not dropped. | [erd §3](erd.md) |
| P4 | The exclusion follows the decision table X1–X6. A failure wins over an exclusion. Authored weights and ops that ignore weights never exclude. | [erd §6](erd.md) |
| P5 | A Filter member with no signal is excluded, and it keeps its mark 0 (`score: 0`), because the operator does not change. | [member-exclusion](prd/member-exclusion.md) EX-4 |
| P6 | The rank is ordinal (1..n over the scored members, author order on ties), only for `top_k@1`, from one ordering function shared with the cut. | [rank-and-cut](prd/rank-and-cut.md) |
| P7 | `cut` is written only for `top_k@1`, with the default order `"max"` filled in, also on an abstain. | [rank-and-cut](prd/rank-and-cut.md) |
| P8 | `judge_model` is a top-level optional key of the evidence, not a field of `JudgeReadingRecord` (the brief's proposal), because Rank, Filter and Vote by judge have no judge reading record. The SDK writes it in the spec from the `"judge"` model call. | [judge-model](prd/judge-model.md) |
| P9 | `judge_model` is display data: checked (non-empty, ≤ 256 characters, no control character), never logged, never routed. A judge spec without it still runs. | [judge-model](prd/judge-model.md), [erd §4](erd.md) |
| P10 | The warning reads adjacent stages only (a judge Fusion, then a direct model stage), once per Pipeline object, silenced on the url4 rebuild, public as `sf.JudgeWriterWarning`. | [judge-writer-warning](prd/judge-writer-warning.md) |
| P11 | New keys are absent when not set (the `mean` precedent), so every evidence and spec without a new value keeps its v1 bytes. | [evidence-schema](prd/evidence-schema.md) |
| P12 | Engine words: new `RecordStatus` and `ExcludeReason`; `MemberStatus` does not change. SDK words: `MemberStatus` and `AnswerStatus` add `"excluded"`, `AnswerReason` adds `no_signal` and `no_weight`. | [evidence-schema](prd/evidence-schema.md) |

## 7. Open and deferred

| # | Item | Default |
|---|---|---|
| D1 | Emerged after the decision round: `judge_model` in the spec changes the compiled url4 of every judge recipe (7 contract fixtures and the SDK byte tests of judge specs need owner-approved edits). | accept, as answered in ans:Q2 ([judge-model](prd/judge-model.md) §6) |
| D2 | Display of the new values in the report UI | part 4 of E4b |
| D3 | A `cut` for `kept@1`, a rank for `best_holder@1` | not planned |
| D4 | A writer that is a Fusion or a nested Pipeline with the judge's model | not planned |

Scope notes:

- **N1** Q3 makes `"excluded"` a value of the public `sf.Answer.status`. User code that switches on
  the status sees a third value. `answer.v1` changes its words (not its field set).
- **N2** An SDK from before part 2 cannot read an evidence with an excluded row or a new key. The
  engine and the SDK ship together.

## 8. What changes for related work

- **E4b part 1 (OME-1601, PR #1409).** Part 2 is based on it. If PR #1409 changes before merge,
  rebase this branch onto its new tip.
- **E4b part 3 (signal sources).** A member with no value for a declared signal gets
  `"excluded"` / `no_signal` from the same rule (X2). Whichever part merges second rebases the
  shared files: `E/combine/evidence.py`, `E/combine/endpoint.py`, the evidence schema snapshot and
  `evidence_cases.json`.
- **E4b part 4 (show signals).** Part 4 renders `"excluded"`, `rank`, `cut` and `judge_model`.

## 9. Build errata

None yet.
