# PRD: Consistency rebuild and replay (url4 → Python, url4 → Candidate)

**Source:** the brief ("url4 rebuild (to_python) round-trips a recipe with sf.Consistency and drops
the injected sample calls"); ans:Q3 ("Explicit and reproducible") · **Priority:** P1
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §2, §7](../erd.md) · contracts: C5 · uses: [consistency-api](consistency-api.md)

## 1. Summary and user story

As a researcher who gets a url4 of a consistency recipe (from a report, a leaderboard row or a
colleague), I want `sf.Url4(text).to_python()` to give back `signals={"cons":
sf.Consistency(n=3, temperature=1.0)}` with the members as I wrote them, and a replay of the url4 to
show the same operations as the compile, so that I can read, edit and run the method again. A
hand-edited url4 (a changed seed, a missing sample) must fail with the existing "cannot rebuild"
errors, never rebuild as something else.

## 2. Background and constraints

- The replay validates the topology against the executable calls: every named call must be a
  topology binding, with the same context dependencies (S/url4.py:411-432). [existing]
- A url4 with an `optional`/`required` slot or a `quorum` param is recompiled from the rebuilt
  Recipe and compared byte for byte (`_has_executable_fusion_policy`, S/url4.py:462-470;
  `_require_recompiles`, :435-459). Each sample slot is optional, so every consistency url4 takes
  this check. [existing]; [implied]
- The recompile uses only the operators that the url4 pins (`_OperatorCatalog.from_pinned(
  _combine_operator_pairs(calls))`); `spec_operator_pairs` reads only the four spec steps
  (S/_evaluation/combine_spec.py:189-197). [existing]
- The replay builds the operations from the topology walk (`_candidate_from_topology`,
  S/_evaluation/url4.py:261-300) and lists the seeded calls for the fixed-seed warning (:239-245).
  [existing]

### 2.1 Current behavior

- `_decode_synthesizer` (S/_evaluation/topology.py:485-498) accepts a reducer node with the keys
  `binding`, `kind`, `name` and the optional `signals`. A `samples` key is refused.
- `_require_call_kind` (S/url4.py:486-500) refuses the binding param on a call that is not a signal
  call.
- `declared_from_spec` (S/signal_sources.py:193-209) knows `verbalized`, `logprob`, `entropy`.

**Delta.**

1. `S/_evaluation/topology.py`: `_decode_synthesizer` accepts the key sets with and without
   `signals` and with and without `samples`; new `_decode_samples(value, ...)`: a non-empty list;
   each item exactly `{"member", "sources"}`; `member` is `member_1`, `member_2`, ... in order;
   `sources` a non-empty list of exact model nodes with `kind == "model"`, `role == "sample"`,
   `named` a bool, `binding` matching `model_\d+`; all `sources` lists of one length; no binding
   twice. Any break: `ValueError(_REDUCER_INVALID)`. The walker (`_TopologyWalker._visit_reducer`)
   visits each sample node with the Fusion's `(context, operations)` (the member rule) BEFORE the
   signals, and the reducer gets context dependencies `(*fusion_context, *sample_bindings,
   *signal_bindings)` and operation dependencies `(*member_bindings, *signal_bindings,
   *sample_bindings)` (erd §7). `_visit_reducer` takes the `operations` tuple as a new argument
   (the corrective-loop call passes its own).
2. `S/url4.py` `_require_call_kind`: a node with `role == "sample"` needs the binding param first
   (`_binding_first`), like a signal role.
3. `S/signal_sources.py`: `Consistency._from_spec(entry)`: the keys are exactly `source`, `n`,
   `temperature`, `match`; `n` an int (not a bool); `temperature` a float or an int (not a bool);
   `match` a mapping with exactly `extract` and `normalize`; else `ValueError(_CANNOT_REBUILD)`.
   It returns `Consistency(n, temperature=temperature)`; the recompile proves the `match`.
   `_SOURCES` adds `"consistency": Consistency`. `_python()` is `sf.Consistency(n=3,
   temperature=1.0)`.
4. `S/_evaluation/combine_spec.py` `spec_operator_pairs`: after the step pairs, the `extract` and
   `normalize` pairs of each `signals` entry that has a `match` (in name order), so the recompile
   catalog and the replay operator check (`_require_known_operators`) hold the match operators.
5. `S/_evaluation/url4.py` `_replayed_url4`: the `seeded` tuple leaves out an operation whose kind
   is `sample` (P18).

## 3. Scenarios and acceptance criteria

F1, F2: the recipes of [consistency-api](consistency-api.md) §3. F3: F1's members with
`signals={"cons": sf.Consistency(n=1)}` and `synthesizer=sf.Vote(judge=sf.Judge("prov/judge",
returns="scores", rubric="Score each answer from 0 to 10."))` (a judge-weighted vote: one signal
call `judge_1`).

### 3.1 Happy path

- **CB-1** Given the F1 url4, then `sf.Url4(url4).to_python()` holds
  `signals={'cons': sf.Consistency(n=3, temperature=1.0)},` and the three members as
  `sf.Model('prov/alpha')` (no `seed`, `temperature` or `binding` param anywhere in the text),
  and `exec` of the text gives a `candidate` that compiles to the F1 url4 byte for byte. The same
  for F2 (`sf.Consistency(n=2, temperature=0.7)`, `sf.Median()`). [stated brief]; [stated ans:Q3]
- **CB-2** Given the F1 url4 linked as an Evaluation url4 (the `_fb_linked` shape of
  `ST/test_gate_api.py:596-603`), then `_candidate_from_url4(linked).operations ==
  compiled.operations` (ids, kinds `sample`, labels `"alpha sample"`, `depends_on`), in order.
  [proposed] P7
- **CB-3** Given F3, then the topology bindings give `synthesis_1` the context dependencies
  `("model_1", "model_2", "model_3", "model_4", "model_5", "model_6", "judge_1")` and the
  operation dependencies `("model_1", "model_2", "model_3", "judge_1", "model_4", "model_5",
  "model_6")`, and the F3 url4 round-trips through `to_python` (CB-1 rule). [proposed] erd §7

### 3.2 Error paths

Each hand edit below starts from the F1 url4 and must fail `to_python` (and the replay) with a
`ValueError` whose message EQUALS the listed text (`str(exc) == text`). If the first run after
GREEN shows another of the four C5 texts for a row, the build corrects that one expected text once,
before the unit commit, and records it in the ledger and in overview §10 (build errata). No other
change to these rows is allowed.

- **CB-E1** The binding param removed from `model_4`: "URL4 Candidate Recipe topology does not
  match its model calls".
- **CB-E2** The seed of `model_5` changed to `1`: "URL4 Candidate does not match its Recipe
  metadata".
- **CB-E3** The slot `sample_3` and its call `model_6` removed from `panel_1` (the topology still
  lists `model_6`): "URL4 Candidate Recipe topology does not match its model calls".
- **CB-E4** The topology role of `model_4` changed to `"model"`: "URL4 Candidate has invalid
  Reducer topology metadata".
- **CB-E5** The spec entry `n` changed from 3 to 4 (calls unchanged): "URL4 Candidate does not
  match its Recipe metadata".
- **CB-E6** The spec entry with an extra key `"flags": 1` in `match`: "URL4 Candidate has a
  signals declaration this SDK version cannot rebuild".

### 3.3 Derived scenarios (risk-ordered)

- **CB-D1** (H×M) [existing] Every url4 without consistency rebuilds as before: for the five fixed
  fixtures of [consistency-api](consistency-api.md) TDD row 1, `exec(to_python(url4))` compiles
  to the same url4.
- **CB-D2** (H×M) [proposed] P18 Given the linked F1 url4, then the replay's `seeded` tuple is
  `()`, so a replay with a run seed gives no `FixedSeedSittingWarning` for the samples.
- **CB-D3** (M×M) [proposed] Given the F1 spec, then `spec_operator_pairs(spec) ==
  (("reduce", "by_signal@1"), ("select", "best_holder@1"), ("extract", "last_line@1"),
  ("normalize", "text@1"))`; and a replay against an Engine catalog without `text@1` fails
  before any spend with the existing pin error (`_require_known_operators`).
- **CB-D4** (M×M) [proposed] `Consistency._from_spec(c._entry(M)) == c` for
  `c = sf.Consistency(n=3)` and M the F1 match (the INVARIANT of S/signal_sources.py).
  `_from_spec` refuses an entry without `n`, with `n: true`, with `temperature: "1"`, with
  `match: []`, with `match` without `normalize`, and the `_spec()` dict (it has no `match`).
- **CB-D5** (M×L) [implied] A topology `samples` key on a reducer node of a url4 whose spec declares
  no consistency fails the recompile ("URL4 Candidate does not match its Recipe metadata").

## 4. Non-functional requirements

- The rebuild does no I/O (the recompile uses the pinned catalog). [existing]

## 5. Out of scope

- A rebuild of a corrective loop with consistency (refused at compile, overview D2).

## 6. Open questions

None.

## 7. TDD plan

New test file: `ST/test_consistency_rebuild.py`. It reads the F1 and F2 fixtures of unit 4 through
the builders of `ST/test_consistency_contract_fixtures.py`.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `url4_without_consistency_rebuilds_as_before` (the five fixed fixtures) | unit | CB-D1 | H×M | passes today |
| 2 | `to_python_rebuilds_sf_consistency_and_drops_the_sample_calls` (F1, F2) | unit | CB-1 | H×H | decoder, walker, `_require_call_kind`, `_from_spec`, operator pairs |
| 3 | `replay_recovers_the_compiled_operations` | unit | CB-2 | H×M | walker order |
| 4 | `a_judge_signal_and_samples_keep_both_dependency_orders` (F3) | unit | CB-3 | H×M | walker |
| 5 | `hand_edited_consistency_url4_cannot_rebuild` (parametrized CB-E1..E6) | unit | CB-E1–E6 | H×M | — |
| 6 | `replay_lists_no_sample_as_a_fixed_seed_call` | unit | CB-D2 | M×M | `_replayed_url4` |
| 7 | `the_match_operators_are_pinned_operators` | unit | CB-D3 | M×M | `spec_operator_pairs` |
| 8 | `consistency_from_spec_refuses_foreign_entries` | unit | CB-D4 | M×L | `_from_spec` |
| 9 | `a_samples_key_without_a_declaration_does_not_rebuild` | unit | CB-D5 | M×L | — |

Pinned edits of this PRD: none.
