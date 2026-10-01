# E4a — Combine answers without a synthesizer, deterministically (OME-1289)

**Status:** draft spec, waiting for review · **Branch:** `e4a-deterministic-combine` ·
**Ledger:** [docs/work/2026-09-30-e4a-deterministic-combine.md](../../work/2026-09-30-e4a-deterministic-combine.md)

## 1. Summary

Today every `Fusion` ends in a model that writes a new answer. E4a adds a **reducer** for the Fusion
synthesizer slot. A reducer is a set of pure rules: extract a value from each member text,
normalize it, reduce the values (count, weighted sum, median, field rules, join), and select a
member or build a value. The SDK compiles a reducer into one url4 call to the engine's **combine
endpoint** (`/ensemble/combine/v1`) and puts the rules in the call as data. The endpoint looks up
each operator by `name@version` in a registry and runs it in-process. It returns the chosen
member's original text (or a built object or selection), and it records a typed
`CombineEvidence` that reaches the SDK Report through the existing per-operation channel. url4
itself does not change. A judge is a model call followed by a deterministic copy. `samples()`
makes N seeded members of one seed-capable model.

## 2. Subsystems and ownership

| Subsystem | Landing | PRDs |
|---|---|---|
| Operator framework (combine endpoint, registry, spec, evidence recorder, catalog REST) | `apps/screamingface-engine` | operator-framework, answer-operators, combine-evidence (engine half) |
| Reducer API and compile (Fusion slot, reducer classes, samples, evidence decode) | `packages/screamingface` | reducer-slot, samples, combine-evidence (SDK half), the flow PRDs (SDK half) |
| url4 | `packages/url4` | no change |
| Studio, scoreboard, aigateway | — | out of scope (ans:Q5, ans:Q6, ans:Q13) |

Under the cross-cutting rule, implementation needs one sub-issue for each landing:
`app/screamingface-engine` and `pkg/screamingface`.

## 3. Reading order

1. [erd.md](erd.md) — the records.
2. Component PRDs: [operator-framework](prd/operator-framework.md) →
   [answer-operators](prd/answer-operators.md) → [reducer-slot](prd/reducer-slot.md) →
   [combine-evidence](prd/combine-evidence.md).
3. Flow PRDs, in build order: [majority-vote-and-median](prd/majority-vote-and-median.md) →
   [samples](prd/samples.md) → [weighted-vote](prd/weighted-vote.md) →
   [judge-pick](prd/judge-pick.md) → [pick-and-merge](prd/pick-and-merge.md) →
   [rank-keep-k](prd/rank-keep-k.md) → [concatenate](prd/concatenate.md).
4. [contracts.md](contracts.md), then [test-plan.md](test-plan.md).

## 4. PRD index

| PRD | Kind | Priority | Scenarios (happy / error / derived) | TDD cases |
|---|---|---|---|---|
| operator-framework | component | P1 | 5 / 3 / 9 | 17 |
| answer-operators | component | P1 | 4 / 4 / 9 | 18 |
| reducer-slot | component | P1 | 4 / 3 / 5 | 14 |
| combine-evidence | component | P1 | 3 / 2 / 7 | 14 |
| majority-vote-and-median | flow | P1 | 4 / 3 / 8 | 14 |
| samples | flow | P1 | 3 / 3 / 5 | 10 |
| weighted-vote | flow | P1 | 3 / 3 / 5 | 9 |
| judge-pick | flow | P1 | 3 / 3 / 7 | 10 |
| pick-and-merge | flow | P1 | 4 / 3 / 8 | 15 |
| rank-keep-k | flow | P1 | 3 / 3 / 4 | 9 |
| concatenate | flow | P1 | 2 / 3 / 3 | 7 |

## 5. Interview ledger

| Id | Question | Answer | Note |
|---|---|---|---|
| Q1 | Which behaviors go into P1? | Framework + vote/median; weighted vote + judge; pick/merge, rank-k, concat | samples() was not picked here; Q11 added it |
| Q2 | How does an author write a deterministic join? | Fusion synthesizer slot | |
| Q3 | Where do operator plugins live? | Engine module + catalog (`GET /v1/operators`) | |
| Q4 | What does the median return? | The recipe declares it (`nearest` or `value`) | |
| Q5 | Studio? | Out of scope | |
| Q6 | Where does the evidence appear? | SDK Report only | |
| Q7 | Do existing graders move to the plugins? | No, later | |
| Q8 | How do free-text answers group? | Exact after normalize | |
| Q9 | No usable votes? | Fail the case | |
| Q10 | Judge member order? | Author order, documented | |
| Q11 | Identical members while samples() is P2? | "add samples as well" (free text) | samples() moved to P1; guard form not chosen, so the default is a warning (see §6) |
| Q12 | Model-written merge field in P1? | In P1 | differs from the recommendation (P2) |
| Q13 | samples() on providers that reject `seed`? | Seed-capable models only | differs from the recommendation (gateway sample key) |

## 6. Global assumptions and deferred items

**Assumptions** (`[proposed]`; each is pinned in a PRD):
- The spec travels in the url4 `intent` as canonical JSON. The only param is `binding`.
- Caps: 256 members, 1 MiB read for each output, a 64 MiB context, an 8 MiB output, a 64 KiB spec,
  and a JSON depth of 64.
- New failure codes: `combine_spec_invalid`, `combine_operator_unknown`, `combine_no_votes`,
  `combine_input_too_large`. A judge reply that cannot be parsed uses the existing code
  `judge_reply_invalid`.
- The combine output's `finish_reason` is `stop`. The members' own finish reasons stay visible on
  their operations.

**Deferred** (each with my recommended default):

| # | Item | Source | Default |
|---|---|---|---|
| D1 | Duplicate-member guard: warn or reject | ans:Q11 did not pick a form | Warn with `DuplicateMembersWarning` |
| D2 | Grader parity on imported boards (Inspect `match` vs `numeric@1`) | parked by the user | Each board later declares its matching extract rule. `Vote(extract="benchmark")` uses it by default |
| D3 | Moving engine graders to the plugins | ans:Q7 | A later unit, with new benchmark revisions |
| D4 | A gateway sample key for providers without `seed` | ans:Q13 | Revisit if Claude-model sampling is needed |

## 7. What changes for related epics

- **E4b** reads `CombineEvidence.agreement` and reuses the extract and normalize operators.
- **E4c** can put a reducer Fusion inside a branch. The router does not vote.
- **E4d** calls the same reducer once per round.
- **E4e** registers user operators in the same registry, through a sandbox.
- **E10e** reuses `samples()` for pass@k, and it will share a code extractor operator.
