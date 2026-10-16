# PRD: Consistency value (the Engine computes the fraction)

**Source:** epic sources table, ans:Q4 ("value = matches / successful samples ... if all fail, the
value is missing ... The Case does not fail") · **Priority:** P0
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §4, §5, §6](../erd.md) · contracts: C3, C4, C7 · uses:
[consistency-record](consistency-record.md) · used by: [consistency-api](consistency-api.md),
[consistency-display](consistency-display.md)

## 1. Summary and user story

As a benchmark author who declares `signals={"cons": sf.Consistency(n=5)}`, I want the combine step
to compute, for each member, the fraction of its successful extra samples whose answer matches the
member's answer (after the same extract and normalize as the step), so that a rule (a weight, a
Pick, a Rank, a Filter, a gate) can read that number, and the evidence shows it with the count of
failed samples.

## 2. Background and constraints

- "Extract and normalize each answer the same way as E4a. The number is the fraction of those N
  that match this answer." [stated epic]
- "value = matches / successful samples; the count of failed samples is recorded; if all fail, the
  value is missing (the rule then excludes the member, as in part 2); the Case does not fail."
  [stated ans:Q4]
- The combine core is pure: no I/O, no clock, no `combine.operators` or `combine.builtins` import
  in a core module (E/combine/endpoint.py:11-14; `COMBINE_CORE_FORBIDDEN`,
  .claude/scripts/check_layering.py:109). [existing]
- The replies of the samples reach the combine call through the url4 context (`samples`, erd §4),
  never through the member reader. So the reader's fingerprint index
  (E/world/combine.py:97-100, "a call that matches zero or several recorded calls makes the
  member's numbers unknown") is not used and not changed. [proposed] P9

### 2.1 Current behavior

- `_plan` (E/combine/endpoint.py:683-707) resolves the four steps, and `_declared` (:710-728) makes
  a `_Declared` (text source) or a `_ReplyDeclared` (logprob, entropy) for each declared name.
- `_signal_values` (:292-309) computes one column per recorded key; `_column` (:339-351) picks the
  source. A declared value is a finite float or None (EV-I1).
- `_stages` and `_extract_then_normalize` (:827-856) read one text: the read cap
  (`MAX_OUTPUT_READ_BYTES`, E/combine/ports.py:93), then extract, then normalize.
- `_evidence` (:914-983) writes `declared=_declared_record(spec)` (:985-991).

**Delta.**

1. New pure module `E/combine/consistency.py` (imports: the standard library only; the layering
   gate checks it, C7). The rows parse is NOT here: `parse_context` gives the texts already parsed
   (consistency-record, `_panel_rows`):

   ```python
   @dataclass(frozen=True, slots=True)
   class SampleCount:
       matched: int | None
       succeeded: int
       failed: int

       @property
       def value(self) -> float | None:
           return None if self.matched is None else self.matched / self.succeeded

   def count_samples(
       member_value: str | None, texts: Sequence[str], n: int, read: Callable[[str], str | None]
   ) -> SampleCount:
       """succeeded = len(texts); failed = n - succeeded; matched = the count of texts whose
       read(...) is not None and equals member_value; matched is None when member_value is None
       or succeeded == 0."""
   ```

2. `E/combine/endpoint.py`:
   - new `_SampleDeclared(name, n, extract: _Step[Extractor], normalize: _Step[Normalizer] |
     None)`. `_declared` builds it for a `ConsistencySource`: the match steps go through
     `_resolve(registry, step, stage)` and `_bind` (the same checks as a spec step: an unknown id
     is `combine_operator_unknown`; a wrong stage or bad args is `combine_spec_invalid`).
   - `_Plan.declared` holds `_Declared | _ReplyDeclared | _SampleDeclared`.
   - `_combine` passes `samples_n=` (the declared `n`, or None when `declares_consistency(spec)`
     is None) to `parse_context`, then computes the counts once, before the signal values:
     `counts = _sample_counts(plan, spec, context)` → `Mapping[str, SampleCount] | None` (member
     order; None when the spec declares no consistency). It reads `context.samples[m]` (the texts,
     already parsed). The match value of a text is `_extract_then_normalize` with the match steps
     after the read cap (`_stages` logic): None unless the status is `voted`.
   - pinned signatures: `_signal_values(plan, spec, context, accounting, counts: Mapping[str,
     SampleCount] | None)` and `_column(key, item, spec, context, looked, counts)`, with `item:
     _Declared | _ReplyDeclared | _SampleDeclared | None`. `_column` gets the first branch
     `if isinstance(item, _SampleDeclared): return {m: counts[m].value for m in spec.members}`
     (`counts` is not None when such an item exists). The `_signal_values` early return (no member
     answered) keeps its all-None column, which is the same values (CS-I5 holds, because then every
     `matched` is None).
   - `recorded` carries the counts: new `_Recorded(Mapping[str, Mapping[str, float | None]])`, a
     read-only mapping over the signal values (every read `recorded[member]` stays as it is) with
     one more attribute `samples: Mapping[str, SampleCount] | None`. `_combine` builds
     `recorded = _Recorded(_signal_values(...), counts)`. The `recorded:` annotations of the exit
     functions become `_Recorded`; NO call site changes and no exit gets a new keyword. WHY:
     `recorded=` already goes through every exit (answer, abstain, gate, fallback), and part 6
     changes the same file in parallel, so one carrier keeps the rebase small.
   - `_evidence` writes `consistency={name: [SampleCountRecord(m, c.matched, c.succeeded,
     c.failed) for m, c in recorded.samples.items()]}` when `recorded.samples` is not None, else
     None, so every exit writes the record.
   - The endpoint module docstring INVARIANT gets one sentence: "A consistency value reads the
     `samples` context of the members' extra calls; the samples never vote (E4b part 7)."
3. The one combine log line does not change. [proposed] P21

## 3. Scenarios and acceptance criteria

Fixture V (hand-computed). Spec: `builtin_vote_spec(3)` (last_number@1, numeric@1, mode@1,
first_holder@1) plus `"signals": {"cons": {"source": "consistency", "n": 4, "temperature": 1.0,
"match": {"extract": {"op": "last_number@1", "args": {}}, "normalize": {"op": "numeric@1",
"args": {}}}}}`. Context: `outputs` member_1 `"so 12"`, member_2 `"it is 12"`, member_3
`"maybe 7"`; `samples` (rows by j): member_1 {1: `"12"`, 2: `"12"`, 3: `"7"`, 4: `"twelve"`},
member_2 {1: `"12"`, 3: `"x 12"`}, member_3 {} (`"[]"`).

| Member | Match value | succeeded | failed | matched | value |
|---|---|---|---|---|---|
| member_1 | `"12"` | 4 | 0 | 2 (`"7"` differs; `"twelve"` has no number) | 0.5 |
| member_2 | `"12"` | 2 | 2 | 2 | 1.0 |
| member_3 | `"7"` | 0 | 4 | None | None |

Fixture W (hand-computed, the default match). Spec: `argmax_spec(3, "cons", "max")`
(ET/combine_signal_support.py:18-27: pick, no extract, `by_signal@1`, `best_holder@1`) plus
`"signals": {"cons": {"source": "consistency", "n": 3, "temperature": 1.0, "match": {"extract":
{"op": "last_line@1", "args": {}}, "normalize": {"op": "text@1", "args": {}}}}}`. Context:
`outputs` member_1 `"B"`, member_2 `"C"`, member_3 `"A"`; `samples`: member_1 {1: `"A"`, 2: `"B"`,
3: `"b"`}, member_2 {1: `"A"`, 2: `"A"`, 3: `"c d"`}, member_3 {1: `"a"`, 2: `"A."`, 3: `"A"`}.

| Member | Match value | matched | value |
|---|---|---|---|
| member_1 | `"b"` | 2 | 0.6666666666666666 |
| member_2 | `"c"` | 0 | 0.0 |
| member_3 | `"a"` | 3 (`"A."` loses one trailing period, `text@1`) | 1.0 |

### 3.1 Happy path

- **CV-1** Given fixture V, then the result is `member_1` with the output `"so 12"`, the tally is
  `[{"value": "12", "score": 2.0, "holders": ["member_1", "member_2"]}, {"value": "7", "score":
  1.0, "holders": ["member_3"]}]`, `agreement == 0.6666666666666666`, `members[i].signals` are
  `{"cons": 0.5}`, `{"cons": 1.0}`, `{"cons": None}`, and `consistency == {"cons":
  [{"member_id": "member_1", "matched": 2, "succeeded": 4, "failed": 0}, {"member_id":
  "member_2", "matched": 2, "succeeded": 2, "failed": 2}, {"member_id": "member_3", "matched":
  None, "succeeded": 0, "failed": 4}]}`. [stated ans:Q4]
- **CV-2** Given fixture W, then `chosen == ["member_3"]`, the output is `"A"`, `signal ==
  {"key": "cons", "order": "max"}`, and the values are 0.6666666666666666, 0.0, 1.0. [stated epic]
- **CV-3** Given fixture V, then `declared["cons"]` is the spec entry as written (with `match`).
  [existing part 3 P11]
- **CV-4** Given fixture W with member_3 samples `[]`, then member_3 has `matched None, succeeded 0,
  failed 3`, value None, the row is `excluded` with reason `no_signal`, `chosen ==
  ["member_1"]`, and the output is `"B"`. "If all fail, the value is missing (the rule then
  excludes the member)." [stated ans:Q4]; [existing part 2 X2]
- **CV-5** Given fixture V with a weighted vote (`reduce` `weighted_mode@1`, `select`
  `max_weight_holder@1`, `weights: {"signal": "cons"}`), then member_3 is `excluded` with
  `no_weight`, the weights are 0.5 and 1.0, the tally is `[{"value": "12", "score": 1.5,
  "holders": ["member_1", "member_2"]}]`, `chosen == ["member_2"]`, the output is `"it is 12"`.
  [implied]

### 3.2 Error paths

- **CV-E1** (the endpoint wiring; the full list of map and row shapes is consistency-record
  CR-E2) Given fixture V's spec, then each of these contexts is `combine_spec_invalid` through the
  combine call, and the message holds no member or sample text: no `samples` key ("combine
  context samples are present exactly when the spec declares consistency"); member_1 rows with a
  row `"sample_5"` ("combine context samples do not match the sample slots": the endpoint passes
  `samples_n=4`). Given fixture V's context and a spec WITHOUT the declaration, then
  `combine_spec_invalid` ("combine context samples are present exactly when the spec declares
  consistency"). [proposed] CX-I1, CX-I2
- **CV-E2** Given fixture V with `match.extract.op` `"nope@1"`, then `combine_operator_unknown`;
  with `match.extract.op` `"numeric@1"` (a normalize operator), then `combine_spec_invalid`; with
  `match.extract` `{"op": "regex@1", "args": {}}` (a missing pattern), then
  `combine_spec_invalid`. [existing registry rules, E/combine/registry.py:59-68]

### 3.3 Derived scenarios (risk-ordered)

- **CV-D1** (H×H) [stated ans:Q4] A failed sample never fails the step: fixture V member_3 (every
  sample failed) answers the Case with the member_1 text. (The url4 side is
  [consistency-api](consistency-api.md) CA-6.)
- **CV-D2** (H×M) [proposed] P12 The samples never vote: given fixture V with four rows (j = 1..4)
  of text `"7"` for every member, the tally is the CV-1 tally, the result is member_1, the values
  are 0.0, 0.0, 1.0, and every record has `succeeded` 4 and `failed` 0.
- **CV-D3** (H×M) [proposed] P10 A sample with nothing extracted is a successful sample that does
  not match (fixture V member_1 sample 4: succeeded 4, matched 2). A sample text over 1 MiB is the
  same (a sample `"1" * (1024 * 1024 + 1)` counts as succeeded and not matched).
- **CV-D4** (H×M) [proposed] A member that a quorum panel left out (the context `panel` has no
  member_2 row) has `matched None`, its own `succeeded` and `failed` counts (from its samples), and
  value None.
- **CV-D5** (M×M) [implied] A step with no voter still writes the counts: fixture V with an empty
  quorum panel (`"panel": "[]"`) abstains with `no_votes`, and `consistency` holds the three
  records with `matched None` and the CV-1 `succeeded` and `failed`.
- **CV-D6** (M×M) [implied] The part 5 gate reads the value: fixture V with `"gate": {"observe":
  "chosen:cons", "cmp": ">=", "threshold": 0.6, "otherwise": "abstain"}` gives `gate.observed ==
  0.5`, `passed == False`, `branch == "fallback"`, and the result abstains with `gate_not_met`.
- **CV-D7** (M×L) [proposed] A member whose own text has no match value (member_1 `"so twelve"` in
  fixture V) has `matched None` and value None, and its counts stay 4 and 0.
- **CV-D8** (M×M) [proposed] The counts do not depend on the order of the rows text: fixture V
  member_1 rows written in the order j = 4, 3, 2, 1 give the same record.

## 4. Non-functional requirements

- Work: one extract and one normalize per sample, n at most 32, members at most 256: at most 8192
  stage runs per step, each on at most 1 MiB. [proposed]
- The samples context is inside the 64 MiB context cap (E/combine/endpoint.py:116). Over the cap,
  the step fails with `combine_input_too_large` (a size limit, not a sample failure; overview N4).
  [existing]

## 5. Out of scope

- The url4 sample calls and panels (consistency-api). The display (consistency-display).

## 6. Open questions

None.

## 7. TDD plan

New test files: `ET/test_combine_consistency.py` (rows 1–12), `ET/test_combine_consistency_contract.py`
(row 13), `ST/test_consistency_evidence_contract.py` (row 14). New data file:
`ET/data/combine_contract/consistency_evidence_cases.json` (three scenarios). The 37-case
`evidence_cases.json` and its count pins do NOT change (overview P20).

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `a_spec_without_consistency_writes_no_consistency_key` (the scenario builders of the 37 names of list L37, imported from `test_combine_evidence_contract_fixture.SCENARIOS` by name; each evidence has no `consistency` key) | unit | CR-5 | H×M | passes today |
| 2 | `fixture_v_records_the_values_and_the_counts` | unit | CV-1, CV-3 | H×H | `consistency.py`, `_SampleDeclared`, `_sample_counts`, `_Recorded`, `_evidence` |
| 3 | `fixture_w_picks_the_most_consistent_member_with_the_default_match` | unit | CV-2 | H×H | `_column` branch |
| 4 | `every_failed_sample_gives_a_missing_value_and_the_rule_excludes_the_member` | unit | CV-4 | H×H | — |
| 5 | `a_weighted_vote_reads_consistency_as_the_weight` | unit | CV-5 | M×M | — |
| 6 | `bad_samples_contexts_are_spec_invalid_without_echo` (parametrized, CV-E1 list) | unit | CV-E1 | H×M | `parse_context(samples_n=)` wiring in `_combine` |
| 7 | `bad_match_operators_use_the_step_codes` | unit | CV-E2 | M×M | `_declared` resolve and bind |
| 8 | `the_samples_never_vote` | unit | CV-D2 | H×M | — |
| 9 | `an_unreadable_sample_counts_as_succeeded_and_not_matched` (nothing extracted; over 1 MiB) | unit | CV-D3 | H×M | read cap |
| 10 | `a_left_out_member_keeps_its_sample_counts` and `no_voters_still_record_the_counts` | unit | CV-D4, CV-D5 | M×M | `_abstain` gets the counts inside `recorded` |
| 11 | `a_gate_reads_the_chosen_members_consistency` | unit | CV-D6 | M×M | `_gated` gets the counts inside `recorded` |
| 12 | `a_member_with_no_match_value_has_no_value` and `the_row_order_does_not_change_the_counts` | unit | CV-D7, CV-D8 | M×L | — |
| 13 | `the_engine_consistency_evidence_is_the_fixture_byte_for_byte` (scenarios `consistency_vote` = fixture V, `consistency_pick_default_match` = fixture W, `consistency_no_votes` = CV-D5; a `write_fixture()` that runs when the file runs as a script; a missing file FAILS, as in `ET/test_combine_evidence_contract_fixture.py`) | contract | CV-1, CV-2, CV-D5 | H×M | new data file |
| 14 | `sdk_decodes_the_consistency_contract_cases` (reads the new file under `@requires_engine_app`; the exact name set of the three scenarios; each wire decodes and `to_dict() == wire`) | contract | C4 | H×M | — |

The import rule of `E/combine/consistency.py` (C7) is checked by the layering gate
(`COMBINE_CORE_FORBIDDEN`, .claude/scripts/check_layering.py:103-109), not by a test row: the
earlier parts have no import test for a combine module.

Pinned edits of this PRD: none. The new files are not in the append-only check. If the gate names
another file, the unit stops and the ledger records it.
