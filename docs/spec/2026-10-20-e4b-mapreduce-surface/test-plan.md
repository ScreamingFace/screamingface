# Test plan: map → select → reduce surface

Spec: [00-overview.md](00-overview.md). TDD order in each unit: RED (the new tests fail for the
right reason), GREEN, REFACTOR. New test files only in units 1–6; units 2–6 import the private
package `screamingface._surface`. No live provider call; Engine runs
use a mocked gateway (`httpx.MockTransport`).

## Unit 1: Engine narrow step (narrow.md)

| # | Row | Test file |
|---|---|---|
| NR-1 | a spec with `narrow` parses; an empty list, 5 items, extra keys are refused (NR-S1) | `ET/test_combine_narrow_spec.py` |
| NR-2 | a pair not in `NARROW_RULES` is refused (NR-S2) | same |
| NR-3 | two signal reads in one narrow item are refused; one per item and one in the main step pass (NR-S3) | same |
| NR-4 | filter then mean: the mean reads only kept members; dropped members are `excluded`/`not_selected` | `ET/test_combine_narrow.py` |
| NR-5 | rank then vote: the vote reads the top k; the narrow record has `cut` and `ranks` | same |
| NR-6 | filter then rank then the selection envelope: `selected` holds the final live set | same |
| NR-7 | a narrow abstain: `no_votes` and `cut_not_met`; records up to the step; gate not run (NR-I5) | same |
| NR-8 | a narrow `no_signal`: the member is excluded with `no_signal` at that step (NR-I3) | same |
| NR-9 | a judge read by a narrow rank and by the main vote weights | same |
| NR-10 | an abstain-fallback gate after narrow gates the vote on the live set; `mean:` is over the live set | same |
| NR-10b | the judged set: a judge rank after a filter, and a judge pick (`scores@1` main step) after a filter, parse over every answered member and score the live ones (narrow §3.2) | same |
| NR-10c | member rows: a left-out member has `score: null`, no `rank`, and `signals` with every key read by any step (narrow §4.1) | same |
| NR-10d | the stage rules per item (NR-S2b) | `ET/test_combine_narrow_spec.py` |
| NR-11 | evidence invariants NR-I1..NR-I6 and AR-I3′ refuse bad records | `ET/test_combine_narrow_evidence.py` |
| NR-12 | a spec without `narrow` gives byte-identical evidence (existing contract cases unchanged) | existing contract tests (no edit) |
| NR-13 | the SDK decodes every case of `narrow_evidence_cases.json`; no key → `narrow is None` | `ST/test_narrow_evidence_words.py` |
| NR-14 | `sf.Answer(status="excluded", reason="not_selected")` is valid; other reasons stay | same |

Pinned: the spec and evidence v1 schema snapshots, `ST/public_surface_snapshot.json` (the
`sf.Answer.reason` values and `CombineNarrow`). The owner approves these three after unit 1.

## Unit 2: chain core (surface.md §2, §3, §8; lowering.md §2)

| # | Row | Test file |
|---|---|---|
| CH-1..CH-13 | each chain rule refuses with its message; `>>` is left to right | `ST/test_chain_rules.py` |
| NM-1 | `.name` of a closed block is the name of its lowered value (surface §2.1) | same |
| WJ-1 | the judge-writer warning reports the user's chain positions (lowering §2.4) | `ST/test_chain_warnings.py` |
| FA-1, FA-2 | `Fanout(prompt=)` rules; `signals=` with a bare `Synthesize` | `ST/test_fanout.py` |
| SY-1 | `Synthesize(prompt=)` rules | `ST/test_synthesize.py` |
| LO-1..LO-6 | lowering: pure, idempotent, single stage lowers to the stage, named keeps grouping, optional moves | `ST/test_lowering.py` |
| EX-1, EX-2 | `over=` strings (incl. pinned `name@v`), `"field:<path>"` and `sf.Extract` through `ReduceNode`; the normalize conflict | `ST/test_surface_extract.py` |
| LO-P1 | parity: S1–S4′ and every README Fusion example with a Model synthesizer compile to today's bytes | `ST/test_surface_parity.py` |

## Unit 3: steps (surface.md §4–§6, §9; lowering.md §4)

| # | Row | Test file |
|---|---|---|
| JU-1, JU-2 | judge readers and refusals | `ST/test_judge_step.py` |
| RA-1, FI-1, RE-1 | `Rank(by=, order=)`, `Filter(over=)`, field keys as number signals | `ST/test_narrow_steps.py` |
| AR-1 | `ArgMax`/`ArgMin`/`First`/`JudgePick` compile to the plans of lowering §2.2 | `ST/test_reduce_steps.py` |
| SI-2 | `sf.field` has only `==`; `First` keeps today's `equals` rules (JSON text with no normalize) | same |
| NR-C1 | a narrow step before `Merge`, `JudgePick` or a model-fallback `Gate` is refused | `ST/test_narrow_steps.py` |
| LO-P2 | parity before the swap: S9 same; S10, S10′, S11, S11′ equal today's `@1` judge forms; S5 and S7 equal today's `by_signal` forms | `ST/test_surface_parity.py` (append) |

## Unit 4: gate (surface.md §7)

| # | Row | Test file |
|---|---|---|
| GA-1..GA-5 | each gate rule and message | `ST/test_gate_surface.py` |
| GA-P | the part 5 and 6 gate recipes in the new form compile to today's bytes | same |
| SI-1 | `.chosen()`/`.mean()` on an E4a key raise | same |

## Unit 5: narrow compile (narrow.md §5; lowering.md §2.2)

| # | Row | Test file |
|---|---|---|
| NC-1 | `Fanout >> Filter >> Mean` writes `narrow` after `select`; no narrow step → no key | `ST/test_narrow_compile.py` |
| NC-2 | two narrow steps before `Synthesize`: the last is the main selection, the first is `narrow` | same |
| NC-3 | the judge call is planned once with two readers | same |
| NC-4 | `CH-12` is gone; the url4 fixtures `narrow_filter_mean_candidate.url4` and `narrow_rank_vote_candidate.url4` match | `ST/test_narrow_contract_fixtures.py` |
| NC-5 | an Engine run of each fixture through the mocked gateway gives the evidence of `narrow_evidence_cases.json` | `ET/test_combine_narrow_run.py` |

## Unit 6: rebuild and display (rebuild-display.md)

| # | Row | Test file |
|---|---|---|
| RB-1 | every parity row round-trips: compile → url4 → `to_python()` → `exec` → same bytes | `ST/test_surface_rebuild.py` |
| RB-2 | `@1` scores url4 refused | same |
| RB-3 | `repr` uses `>>`; named/optional Pipeline uses the explicit form | same |
| DS-1 | block card and chain card goldens | `ST/test_surface_cards.py` |
| DS-2 | Combine section: narrow chips, left-out cell text, summary counts | `ST/test_narrow_display.py` |

## Unit 7: migration (migration.md §2, §3)

- TM-1 `judge-template@2` full bytes (outputs and panel forms); label stays `@1`; `@1` scores and
  `@3` refused on recovery (`ST/test_judge_template_v2.py`).
- LO-P3 after the swap: S5, S7, S10, S10′, S11, S11′ equal their new goldens; every other parity row
  is unchanged.
- MSG-1 no raised message names a deleted API (`ST/test_surface_messages.py`).
- MG-1 the codemod output for each rewrite rule (a small table test, deleted with the codemod).
- MG-4 after the move, the full SDK suite passes; the `rg` check of migration §5 finds nothing.
- The owner approves the list of edited, deleted and replaced pinned files.

## Unit 8: docs (migration.md §4)

- `ST/test_combine_recipes_readme.py` runs the new "Combine recipes" block (13 cases).
- `ST/test_fusion_doc_goldens.py` (renamed `test_doc_goldens.py`) passes on the moved README.
- `scripts/check_notebooks.py` passes on all example notebooks, including the new
  `18_map_select_reduce.ipynb`.
