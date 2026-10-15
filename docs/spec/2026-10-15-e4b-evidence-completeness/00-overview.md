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
- a link from each combine step that reads a judge to the judge's own operation record, shown in the
  SDK trace as `judge_operation_id` and `judge_model` (no wire change, ans:Q4);
- an SDK compile warning, `JudgeWriterWarning`, when the writer stage after a judge step uses the
  judge's model.

No Case answer changes. No new operator, no new failure code, no gateway change, no new schema id,
no combine spec change, and no url4 file change.

**Path prefixes.** `E/` = `apps/screamingface-engine/src/screamingface_engine/`,
`S/` = `packages/screamingface/src/screamingface/`, `ET/` = `apps/screamingface-engine/tests/unit/`,
`ST/` = `packages/screamingface/tests/`. Line numbers are on base `0f4b9e292`.

**Gap map** (from the epic OME-1290 gap analysis, 2026-10-15):

| Gap | Epic text | Part 2 work |
|---|---|---|
| C2 | "A missing signal: that member does not vote, and the report says why." | [member-exclusion](prd/member-exclusion.md) |
| D3 | "Missing signal excludes the member." (visible only as `null` today) | [member-exclusion](prd/member-exclusion.md) |
| E3 | "The report shows the score and the rank, including members that were dropped." | [rank-and-cut](prd/rank-and-cut.md) |
| E2 | "The writing model … is not allowed to be the thing that also computed the score." | [judge-model](prd/judge-model.md) (SDK view link), [judge-writer-warning](prd/judge-writer-warning.md) |

## 2. Subsystems and ownership

| Subsystem | Owns | Changed by |
|---|---|---|
| Engine combine core (`E/combine/`) | evidence models, endpoint, descriptor hooks | evidence-schema, member-exclusion, rank-and-cut |
| SDK evidence and answer (`S/answer.py`, `S/combine_evidence.py`, `S/_evaluation/combine_evidence.py`, `S/_case_views.py`, `S/report_trace.py`) | words, rows, decoder, case view, trace | evidence-schema, judge-model |
| SDK compile (`S/_evaluation/candidate.py`, `S/warnings.py`, `S/url4.py`) | the warning | judge-writer-warning |
| Contract data (`ET/data/combine_contract/`, `ST/data/schemas/`, `ST/public_surface_snapshot.json`) | v1 snapshots, evidence cases | evidence-schema, member-exclusion, rank-and-cut, judge-model, judge-writer-warning (owner-approved edits; no url4 file) |

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
| [judge-model](prd/judge-model.md) | existing | 4 / 3 / 4 | 12 |
| [judge-writer-warning](prd/judge-writer-warning.md) | planned | 2 / 1 / 6 | 11 |
| **Total** | | **17 / 12 / 29** | **68** |

## 5. Interview ledger

The prompt is the 2026-10-15 E4b gap analysis and its roadmap ("Part 2. Evidence completeness: add
a per-member drop reason (`no_signal` / `no_weight`), a `rank` field, the cut `k` and `order`, and
scorer and writer model ids with the same-model warning.").

| Id | Question | Answer | Note |
|---|---|---|---|
| Q1 | DB-4: The epic says the writing model "is not allowed to be the thing that also computed the score". What should the code enforce? | "Record ids + warn (Recommended)" | recommended (roadmap round, 2026-10-15) |
| Q2 | The combine step never sees the writer stage's model. Only the SDK sees the judge model and the writer at compile time. Where do the model ids go? | "Judge id + SDK warning (Recommended)" | recommended |
| Q3 | How should the evidence show a member that is left out because its signal or weight is missing? | "New status \"excluded\"" | **against the recommendation** ("New field, status kept") |
| Q4 | "judge_model in the spec costs 12 url4 fixture edits the manifest cannot approve (.url4 not accepted), an SDK decoder change, and old judge url4 rebuilds refused. What do we do?" | "No wire change, SDK link (Recommended)" | recommended; the re-ask of D1 (2026-10-15) with its real cost. It changes how Q2 is met: the judge id is shown by the SDK view, and the owner accepts that view as "the evidence" for the judge id. |

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
| P8 | The judge id is an SDK view, not a wire key (ans:Q4). The trace `reduce` entry gets `judge_operation_id` and `judge_model`: the one graph dependency of kind `"judge"` and its `accounting.request_model`. The combine spec, the engine evidence and every url4 file do not change, so an old judge url4 still rebuilds. | [judge-model](prd/judge-model.md) |
| P9 | "Reads a judge" has one definition with three cases (review M1): the `judge` reducer; `scores@1` with `source="judge"`; a signal read of `score:judge`. The view reads them from the evidence (J1–J3); the warning reads the reducer plan's `"judge"` model call, which E4a pairs with exactly these three cases. | [judge-model](prd/judge-model.md), [judge-writer-warning](prd/judge-writer-warning.md) |
| P10 | The warning reads adjacent stages only (a judge Fusion, then a direct model stage), compares `_canonical_model` forms on both sides (review M2), sends once per Pipeline object, is silenced on the url4 rebuild, and is public as `sf.JudgeWriterWarning`. | [judge-writer-warning](prd/judge-writer-warning.md) |
| P11 | New evidence keys are absent when not set (the `mean` precedent), so every evidence without a new value keeps its v1 bytes. | [evidence-schema](prd/evidence-schema.md) |
| P12 | Engine words: new `RecordStatus` and `ExcludeReason`; `MemberStatus` does not change. SDK words: `MemberStatus` and `AnswerStatus` add `"excluded"`, `AnswerReason` adds `no_signal` and `no_weight`. The `S/answer.py` docstring changes from "the SDK Literals are the engine Literals" to the mapping: SDK `MemberStatus` ↔ engine `RecordStatus`; SDK `AnswerReason` ↔ engine `AnswerReason` ∪ `ExcludeReason` (review m8). | [evidence-schema](prd/evidence-schema.md), [erd §7](erd.md) |
| P13 | The exclusion runs in one place: `_plan` computes `_Plan.excludes: _Exclusion \| None` from `spec.weights`, `reduce.reads_weights` and `reduce.signal_read` (not from the merged `_signal_read` result), and `_member_record` applies it inside `_evidence` (review m9). | [member-exclusion](prd/member-exclusion.md) §2.1 |
| P14 | The cut type has one name per side: `Cut` (ports.py, what the hook returns), `CutRecord` (evidence.py, the wire), `CombineCut` (SDK) (review m10). | [erd §5](erd.md) |

## 7. Open and deferred

| # | Item | Default |
|---|---|---|
| D1 | Display of the new values in the report UI | part 4 of E4b |
| D2 | A `cut` for `kept@1`, a rank for `best_holder@1` | not planned |
| D3 | A writer that is a Fusion or a nested Pipeline with the judge's model | not planned |

The earlier D1 (the url4 byte change of judge recipes) is closed by ans:Q4. Because the spec does
not change, old url4 still rebuilds, and the review finding MAJOR 6 (old judge url4 rebuilds
refused) no longer applies.

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
- **E4b part 4 (show signals).** Part 4 renders `"excluded"`, `rank`, `cut` and the judge link.

## 9. Build errata

None yet.
