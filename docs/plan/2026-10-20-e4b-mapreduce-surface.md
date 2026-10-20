# Plan: E4b surface — map → select → reduce

Spec: [docs/spec/2026-10-20-e4b-mapreduce-surface/](../spec/2026-10-20-e4b-mapreduce-surface/00-overview.md).
Ledger: [docs/work/2026-10-20-e4b-mapreduce-surface.md](../work/2026-10-20-e4b-mapreduce-surface.md).

## 1. Approach

- Base: branch `OME-1653-e4b-display-gate-sums-consistency` (PR #1461) at `e4d44281c`. Worktree
  `.claude/worktrees/e4b-consistency`. All commits go on this branch (A1). No restack of #1409 or
  #1460.
- Each unit: a full unit spec (files, signatures, data shapes, exemplar, edge cases, what not to do,
  verification), then RED, then GREEN, then a design review with the PRD as the rubric, then one
  fix round. A structural finding means a re-spec, not a second fix round.
- Units 2–6 build the new surface in the private package `S/_surface/`. Only new test files import
  it, so no existing test and no public surface snapshot changes. Unit 1 changes three pinned
  files (the spec and evidence v1 schema snapshots and the public surface snapshot); the owner
  approves them after unit 1. Unit 7 is the swap; the owner approves its pinned edits in one list
  (migration MG-3). No agent writes `.claude/test-change-approvals/`.
- No live provider call, no paid test, no eval run. Engine gates run one at a time with
  `timeout 1200` (the 10-17 gate hang). Commit messages end with `Refs: OME-1653`, with no
  `Co-Authored-By` trailer.
- No push and no PR edit until the owner says so. At the end, the PR #1461 body and the OME-1653
  title and description get the new scope (owner confirms the text).

## 2. Units

| # | Unit | Rows | Main files | Stacks | Pinned |
|---|---|---|---|---|---|
| 0 | spec + plan | — | this plan, the spec, the ledger | repo | none |
| 1 | engine-narrow | NR-1..14, NR-10b..d | `E/combine/spec.py` (`NarrowSpec`, `NARROW_RULES`, stage rules, `CombineSpec.narrow`), `E/combine/endpoint.py` (`_NarrowPlan`, `_narrowed`, per-step signal rule, the places of narrow §5), `E/combine/ports.py` (`not_selected`, `CombineInput.judged`), `E/combine/operators/judge.py` (`scores@1` over `judged`), `E/combine/evidence.py` (`NarrowRecord`, `CombineEvidence.narrow`, NR-I*, AR-I3′), `S/combine_evidence.py` + `S/_evaluation/combine_evidence.py` (`CombineNarrow`), `S/answer.py`; new tests + `narrow_evidence_cases.json` | screamingface-engine, screamingface, repo | spec + evidence v1 schema snapshots; public surface snapshot |
| 2 | chain-core | CH, NM, WJ, FA, SY, LO, EX, LO-P1 | new `S/_surface/` (`chain.py`, `fanout.py`, `synthesize.py`, `steps.py` with `Vote`/`Median`/`Mean`, `refs.py` extractor strings, `lowering.py`), `S/_evaluation/candidate.py` (entry: `lower()` before the compile; the judge-writer walk on the chain) | screamingface, repo | none |
| 3 | steps | JU, RA, FI, RE, AR, SI-2, NR-C1, LO-P2 | `S/_surface/` (`judge.py` `Judge`/`JudgePick`, `steps.py` `Rank`/`Filter`/`Concat`/`ArgMax`/`ArgMin`/`First`/`Merge`, `refs.py` signal strings and `field`) | screamingface, repo | none |
| 4 | gate | GA, GA-P, SI-1 | `S/_surface/gate.py`, `S/_surface/refs.py` (`.chosen()`, `.mean()`, `agreement()`) | screamingface, repo | none |
| 5 | narrow-compile | NC-1..5 | `S/reducer.py` (`_ReducerPlan.narrow`), `S/_evaluation/combine_spec.py` (narrow §5 SDK places), `S/_evaluation/reducer_signals.py` (one judge call), `S/fusion.py` (checks on every step), `S/_surface/chain.py` (drop `CH-12`); fixtures + `ET/test_combine_narrow_run.py` | screamingface-engine, screamingface, repo | none |
| 6 | rebuild-display | RB, DS | `S/_surface/rebuild.py` (url4 → chain), `repr` of the `_surface` steps, `S/_ui/cards.py` + `S/_ui/combine_view.py` (new card builders and narrow chips, used by `_surface` values; the old cards stay until the swap) | screamingface, repo | none |
| 7 | swap + migration | TM-1, LO-P3, MSG-1, MG | `S/__init__.py` exports; rename to `Node` classes (O7); `S/judge.py` `@2`; `S/url4.py` `to_python()` → `_surface.rebuild`; message rewording (O13); codemod; ~125 SDK test files; 4 Engine `test_sdk_*` files; goldens and Engine url4 fixtures; delete `sf.Fusion`, `sf.Pick`, `sf.Reduce`, `Recipe.then`, old params, `S/_evaluation/fusion_recipe.py`; report and card labels | screamingface-engine, screamingface, repo | the approval list (owner) |
| 8 | docs | DC | README, CHANGELOG, 10 notebooks + `18_map_select_reduce.ipynb`, the public-docs pages | screamingface, repo | README-test files if edited |

Unit 1 runs in parallel with units 2–4 (other files). Units 2 → 3 → 4 → 5 → 6 → 7 → 8 are
sequential (shared files: `S/chain.py`, `S/_evaluation/lowering.py`, the surface snapshot).

## 3. Models and review

- Unit specs and design reviews: Opus. RED and GREEN: Opus for units 1, 2, 5, 6 and 7 (new
  structure or a wide swap); Haiku implementer for units 3 and 4 (full unit spec, an exemplar), with
  the escalation rule (no commit → Opus).
- Unit 7: a mechanic runs the codemod; an Opus implementer does the MG-2 hand cases; a design
  review checks that no test lost its assertion.
- A final `/code-review` of the whole new range before the owner review.

## 4. Gates

- Per unit: `python3 .claude/scripts/run_gates.py --stack <stack> --base e4d44281c` for each stack
  in the table. The append-only check passes in units 2–6 with no approval, in unit 1 after the
  owner approves its three pinned files, and in unit 7 after the owner approves the list.
- Tip: all three stacks, then `repo`.

## 5. Risks

| Risk | Answer |
|---|---|
| The parity claim is wrong for a recipe | The parity test covers every golden and README recipe; a byte change outside §4 of the overview stops the unit. |
| The internal rename (`Judge` → `_JudgeReducer`) breaks the url4 rebuild | Unit 3 keeps `_from_spec` on the internal classes; the round-trip test in unit 6. |
| Unit 7 hides a lost assertion | Design review of the test diff; the codemod keeps every `assert` line. |
| The narrow step breaks part 2 invariants | NR-11 tests each invariant; the existing evidence cases run with no edit (NR-12). |
| The stack PR #1461 becomes too large to review | The new range is its own commit group with its own ledger; the PR body gets a section for it. |
