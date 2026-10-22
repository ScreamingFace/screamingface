# PRD: Guards — a rule that can replace the router's choice

**Source:** epic OME-1291 behavior 4 ("A guard can override the selector"), ans:Q9, ans:Q12,
ans:Q15, ans:Q18 · **Priority:** P1 (PR-2, with [selectors](selectors.md) and
[skip-members](skip-members.md))
**Lifecycle:** planned (new Gate words in use, one new failure code)
**Owner:** unassigned
Paths: [erd §2, §3, §6](../erd.md) · contracts: C4, C7, C10 · components:
[branch-core](branch-core.md) (DECIDE/OPEN/JOIN, words), [selectors](selectors.md) (Keywords,
LabelModel, one evaluation per Case) · display: [report](report.md)

## 1. Summary and user story

As a researcher with a router recipe, I want an ordered list of rules that run before the router
and can replace its choice — refuse the Case with an error and call no model, or force a stronger
branch — so that jailbreak-shaped or out-of-policy questions never reach the weak branch, and the
report says which rule fired.

A guard is not a new construct. It is an ordinary outer `sf.Gate` whose condition reads a
selector label and whose `then` is the guard action [stated ans:Q9, ans:Q12]:

```python
jail = sf.Keywords([("jailbreak", r"(?i)ignore (all|any|previous) instructions")])
clf = sf.LabelModel("openrouter/openai/gpt-4o-mini", labels=["safe", "unsafe", "medical"])
topic = sf.Keywords([("math", r"(?i)\b(integral|derivative|prove)\b")])

router = sf.Gate(when=sf.label(topic) == "math", then=math_panel, otherwise=general)

candidate = sf.Gate(                          # guard 1: regex, fail closed
    when=sf.label(jail) == "jailbreak", then="fail_closed",
    otherwise=sf.Gate(                        # guard 2: classifier, fail closed
        when=sf.label(clf) == "unsafe", then="fail_closed",
        otherwise=sf.Gate(                    # guard 3: classifier, floor
            when=sf.label(clf) == "medical", then=medical_specialists,
            otherwise=router)))
```

The guard order is the nesting order: the outermost Gate is the first guard.

## 2. Background and constraints

- "A guard is a rule that runs beside the selector and can replace its choice. It is not a
  prompt." [stated epic]
- "Guards are an ordered list in the recipe." [stated epic]
- "Each guard has a condition the platform can evaluate (a regex or a classifier label on the
  input, a category flag) and an action: `fail_closed` (return an error, call no model) or
  `floor` (force a named stronger branch even if the selector said otherwise)." [stated epic]
- "If a guard fires, the report says which guard, and the selector's original label is still
  recorded." [stated epic]
- "Guards cannot call arbitrary code." [stated epic]
- Open question of the epic: "`fail_closed` versus abstain. Abstain is a scored decline.
  Fail-closed is an error. They must not share a status code." [stated epic] This PRD closes it:
  §3.1 GU-6.
- Only `sf.Gate`, no router class; N-way and guards are nested binary Gates. [stated ans:Q9,
  ans:Q12]
- Guard conditions in v1: a regex on the question and a classifier label. No length guard, no
  category flag. [stated ans:Q15]
- "A fired guard stops everything after it: no model call. A Keywords label (no model) is still
  computed and recorded; a model selector's label shows 'not run'." [stated ans:Q18]
- Router robustness work ("How robust are router-LLMs?") is evidence of the failure mode, not a
  spec: "Build the guard because the failure mode is in the paper, and say the paper is evidence,
  not a spec." [stated epic]
- SagaLLM is "a partial fit … Ship the override. Do not ship a database." [stated epic]

### 2.1 Current behavior

- The declared failure vocabulary is one closed set, `DECLARED_FAILURE_CODES`
  (`E/benchmarks/contract.py:58-100`), with the comment "additions are deliberate — the
  conformance test pins this exact set, and the SDK keeps its own copy" (`:55-57`) [existing].
- The SDK copy is `S/_report_primitives.py:22-126`; `ST/unit/test_failure_code_conformance.py:56`
  `test_the_sdk_copy_matches_the_engine_copy` parses the Engine contract and compares the two
  sets [existing].
- `ENGINE_ERROR_CODES` (`E/error_text.py:63-80`) is the closed set of codes the Engine reserves to
  itself; a boundary may echo their messages, and no upstream code may be one of them. It is
  pinned by `ET/test_terminal_error_detail.py:336-351` (`ALLOWLISTED_CODES`,
  `test_the_allowlist_is_exactly_this_set`) [existing].
- Helper pattern: `logprobs_unsupported()` (`E/benchmarks/failure_classes.py:75-83`) returns a
  permanent `ResolutionError` with fixed Engine text; an import-time self-check refuses a helper
  that mints an undeclared code (`:86-95`) [existing].
- Exact-set pins: `ET/test_failure_classes.py:88`
  `test_the_declared_vocabulary_is_exactly_the_agreed_set`; `ET/test_e4b_catalog_pins.py:16-25`
  asserts `len(DECLARED_FAILURE_CODES) == 66` [existing].
- The activity failure sets `_FAILURE` (`E/activity/contract.py:39-53`,
  `S/_ui/activity_record.py:25-37`) list model-call failures only [existing].
- Failure policies: `FailurePolicy = withhold | coverage_declare` (`E/benchmarks/definition.py:45`).
  Under `withhold` the scorer gets every selected Case; under `coverage_declare` only the
  gradeable ones (`E/benchmarks/aggregation.py:88-101`) [existing].
- An abstained Case is `scored`, output `""`, score 0.0 (`S/case_result.py:695-707`) [existing].
  A Case counts as a refusal only for refusal text or a `provider_refusal` failure
  (`S/case_result.py:517-524`) [existing].
- `sf.Gate` today: `then=` takes only `sf.Vote`; `otherwise=` takes `"abstain"`, `sf.JudgePick`
  or `sf.Synthesize`; `when=` takes only a `GateCondition` (`S/_surface/gate.py:54-71`, `:86-109`)
  [existing]. There is no guard, no `fail_closed` word and no selector [existing].
- Delta: this PRD adds the `fail_closed` word on `sf.Gate` (with [gate](gate.md)), the
  `fail_closed` failure code on both vocabularies, the guard patterns over
  [selectors](selectors.md), and the recording rule for a fired guard.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **GU-1 Regex guard fails closed with zero model calls.** Given the candidate above and a Case
  whose input matches the `jailbreak` pattern, When the Case runs, Then the outermost Gate takes
  `then="fail_closed"`, no model is called (not `clf`, not the router branches), and the Case is
  `failed` with code `fail_closed`. [stated epic; stated ans:Q15, ans:Q18]
- **GU-2 Classifier guard fails closed after one selector call.** Given a Case that the regex
  guard does not match and that `clf` labels `unsafe`, When the Case runs, Then exactly one model
  call runs (the `clf` call), guard 2 takes `fail_closed`, and the router makes zero calls.
  [stated ans:Q15]
- **GU-3 One classifier, many guards, one call.** Given guards 2 and 3 both read `clf`, When the
  Case reaches guard 2, Then `clf` runs once and guard 3 reads the same label; the two decision
  records hold the same SELECTOR_RECORD (erd SR-I4). [stated ans:Q12]
- **GU-4 Floor forces the stronger branch.** Given a Case that `clf` labels `medical` and `topic`
  labels `math`, When the Case runs, Then guard 3 takes `then=medical_specialists`, the router
  (`math_panel` and `general`) makes zero calls, and the router's would-be label `math` is in the
  record (GU-5). [stated epic]
- **GU-5 The original label is still recorded (within Q18).** Given a Gate that takes a word or
  a floor branch, When DECIDE writes its record, Then `selectors` holds the selectors its own
  condition reads plus every selector that a Gate inside its not-run body reads: a Keywords
  selector as `status: computed` with its labels, a LabelModel selector as `status: not_run`.
  [stated epic; stated ans:Q18]
- **GU-6 `fail_closed` and abstain never share a status.** Given one Case that fails closed and
  one that abstains, Then the first is `status: failed` with code `fail_closed`, the second is
  `status: scored`, score 0.0, `abstained: true`, no failure code. Under `withhold` both are in the
  score denominator (the failed Case through the scorer's failure handling, the abstained Case as
  a 0); under `coverage_declare` the failed Case is outside the scored set and lowers coverage,
  and the abstained Case is still a scored 0. [stated epic]
- **GU-7 No guard fires.** Given a benign Case (no regex match, `clf` = `safe`), When it runs,
  Then every guard takes `otherwise`, the router runs as if unguarded, and each guard's record
  shows `passed: false`, `wanted: otherwise`, `not_run: [{"branch": "then", "reason":
  "not_selected", "model_calls": {"min": 0, "max": 0}}]` for a word `then` (a recipe `then`
  counts its own min and max). [implied; stated ans:Q22]

### 3.2 Error paths

- **GU-8 A guard cannot run Python.** Given `sf.Gate(when=lambda q: "ignore" in q, …)` or a
  `then=`/`otherwise=` that is a Python callable, When the Gate is built, Then it raises
  `TypeError("sf.Gate when= takes a condition such as sf.label(sel) == 'x'; a guard cannot run
  Python code")` before any run. [stated epic]
- **GU-9 A regex the Engine cannot run is refused before spend.** Given a Keywords guard pattern
  that RE2 does not support (a backreference, a lookaround), When the selector is built, Then the
  SDK pre-spend check refuses it with a message that does not contain the pattern
  (`S/_regex_rule.py:1-10` rules). [proposed — reuses `S/_regex_rule.py:1-10`]
- **GU-10 Unparsed classifier reply.** Given `clf` returns text with no declared label, Then
  `sf.label(clf)` is null, `sf.label(clf) == "unsafe"` is false, and the guard does NOT fire; the
  record shows `parse: unparsed` (or `unrecognized` with `raw`). An author who wants a guard that
  fails closed on an unparsed reply writes `when=sf.label(clf) != "safe"`, which holds for every
  other label and for null. [stated epic: "Parse failure uses `default` and is visible";
  proposed `!=`]
- **GU-11 A failing classifier call.** Given the `clf` model call fails permanently (refusal,
  token cap), When guard 2 reads it, Then the selector record is `status: "failed"` and its label
  is null ([selectors](selectors.md) SL-12, overview P7): a guard written with `==` does not fire
  and the Case goes on to the router; a guard written with `!=` (`sf.label(clf) != "safe"`) fires
  and fails closed. The Case never fails with the call's own code. [proposed — P7]

### 3.3 Derived scenarios (risk-ordered)

| # | Title | Tag | I×L | G/W/T |
|---|---|---|---|---|
| GU-12 | Jailbreak-shaped acceptance set | [proposed — epic evidence: router robustness paper] | H×M | Given the fixture `jailbreak_inputs.json` (8 jailbreak-shaped inputs, 8 benign controls of similar length and topic), When the regex guard runs on each, Then it fires on all 8 jailbreak-shaped inputs, on none of the benign ones, and every fired Case shows zero model calls. |
| GU-13 | A floor refused by the budget never falls to the weak branch | [implied — erd BV-I1, budget BU-4] | H×M | Given guard 3 wants `then=medical_specialists` and the budget refuses it, When DECIDE runs, Then the Case abstains with `budget_refused`; the router (`otherwise`, a recipe, not a no-call branch) does not run. |
| GU-14 | `fail_closed` is not a refusal | [proposed — P13; stated epic "Fail-closed is an error"] | H×M | Given a fail-closed Case, Then `represents_refusal` is false and refusal-rate scoring does not count it as a model refusal (`S/case_result.py:517-524`); the candidate earns no refusal credit. An author who wants a scored refusal sends the Case to a branch that refuses. Revisit when a safety leaderboard asks for guard credit. |
| GU-15 | `fail_closed` is never retried | [implied] | H×M | Given a fail-closed Case, Then the failure is permanent, no fresh retry runs, and a rerun of the same Case fails closed again. |
| GU-16 | Message never echoes the input | [proposed — gap §security] | H×M | Given any fired guard, Then the `fail_closed` message is fixed Engine text plus the gate id (`"a guard refused the Case: sf.Gate gate_<n> took fail_closed"`); it never contains the input, a pattern or a label `raw`. |
| GU-17 | `fail_closed` in a skip-Gate member is refused | [proposed — skip-members scope] | M×L | Given `sf.Fanout([sf.Gate(when=…, then="fail_closed")])`, When it is built, Then it raises: a skip-Gate member takes a member recipe in `then=`, never a word. |
| GU-18 | `fail_closed` on a panel gate | [implied — Gate words are general, ans:Q6] | M×L | Given `sf.Fanout(ms) >> sf.Gate(when=sf.agreement() >= 0.5, then=sf.Vote(), otherwise="fail_closed")`, When agreement is low, Then the Case fails closed; the panel calls already ran (the no-call rule covers only calls after DECIDE). |
| GU-19 | Guard on a later Pipeline stage | [implied — ans:Q10] | M×L | Given `prep >> sf.Gate(when=sf.label(jail) == "jailbreak", then="fail_closed", otherwise=answerer)`, Then `jail` reads the Case input (Case-level value), not `prep`'s output, and `prep` has already run. |
| GU-20 | Report names the fired guard | [stated epic] | M×M | Given a fired guard, Then the report export has the guard's decision record with `branch: then`, the word result `fail_closed`, and the Case failure code; the Case pane shows "guard fired" for that Gate ([report](report.md) owns the display). |
| GU-21 | Activity sets stay model-call only | [proposed] | L×M | Given the vocabulary change, Then `_FAILURE` in `E/activity/contract.py` and `S/_ui/activity_record.py` does not gain `fail_closed`: no model call fails with it. |

## 4. Non-functional requirements

- Cost: a fired regex guard costs 0 model calls and 0 USD; a fired classifier guard costs exactly
  its one selector call [stated epic; stated ans:Q18].
- Latency: a regex guard adds one pure DECIDE (< 5 ms CPU p99, [branch-core](branch-core.md) §4)
  [proposed].
- Security: guard conditions are data only (no callables, GU-8); patterns are RE2, linear time
  [existing `S/_regex_rule.py:1-5`]; the failure message is fixed text (GU-16); the classifier
  reply is untrusted input, parsed only to a declared label (GU-10) [proposed].
- Observability: each fired guard is visible in the decision record, the Case failure code, and
  the run summary `fail_closed` count ([report](report.md)) [stated epic].
- Vocabulary release order: the Engine and SDK lists change in one PR; the SDK release ships
  first (OME-1233) [proposed — the OME-1233 release rule].

## 5. Out of scope

- A length guard and a category-flag guard [stated ans:Q15].
- A guard that reads a model's answer and runs a compensating action with saved state (SagaLLM's
  transaction state) [stated epic: "Do not ship a database"]. The partial fit that v1 can express:
  a panel gate over a validator's declared signal, `prep_validator >> sf.Gate(when=sf.signal("valid")
  .chosen() >= 1, then=sf.First(), otherwise=compensation)`, where `compensation` answers the
  Gate's input (the block's input, [branch-core](branch-core.md) BC-5, overview P1). A compensation
  that must read the failed stage's own output is not expressible, because a recipe branch never
  receives the panel answers of a panel gate (BC-5).
- A trained classifier file or a hosted classifier [stated epic: "Training the router" is out].
- Running the model selector before a fired guard to record its label [stated ans:Q18].

## 6. Open questions

None. The refusal-credit question is decided as P13 (overview §6) and specified in GU-14.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: vocabulary first (the code must exist before a test can raise it), then the guard runs
risk-first, then the boundaries. The vocabulary rows (#3–#7, #29) are built in PR-1 (plan unit 1),
because the Gate word `"fail_closed"` exists from PR-1; row #14 needs the budget and is built in
PR-3 (plan unit 13). RED first, always; a test that passes at once proves nothing.
PIN rows are owner-approved edits of pinned files (the exact-set tests); list any other exact-set
pin that RED finds and add its PIN row then.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `abstained_case_is_scored_zero_and_failed_case_has_a_code` | unit | [existing `S/case_result.py:695-707`] | H×M | passes today |
| 2 | CHAR `refusal_is_only_refusal_text_or_provider_refusal` | unit | [existing `S/case_result.py:517-524`] | H×M | passes today |
| 3 | PIN `ET/test_failure_classes.py` `test_the_declared_vocabulary_is_exactly_the_agreed_set` gains `fail_closed` | unit | GU-6 | H×H | add `"fail_closed"` to `DECLARED_FAILURE_CODES` (`E/benchmarks/contract.py:58`) |
| 4 | PIN `ET/test_e4b_catalog_pins.py` count 66 → 67 (`fail_closed`, PR-1; E4c's second code `quorum_not_met` takes it to 68 in PR-2, [skip-members](skip-members.md) #2a) | unit | GU-6 | H×H | — |
| 5 | PIN `ET/test_terminal_error_detail.py` `ALLOWLISTED_CODES` gains `fail_closed` | unit | GU-16 | H×H | add to `ENGINE_ERROR_CODES` (`E/error_text.py:63-80`): Engine-authored, an upstream may not send it |
| 6 | `fail_closed_helper_is_permanent_with_fixed_text_and_declared` | unit | GU-15, GU-16 | H×H | `fail_closed(gate_id)` in `E/benchmarks/failure_classes.py`; import-time self-check line beside `:94` |
| 7 | `sdk_copy_declares_fail_closed_as_permanent` (conformance passes; SDK `Failure(code="fail_closed")` is accepted) | unit | GU-6 | H×H | `S/_report_primitives.py:22` + WHY comment |
| 8 | `regex_guard_fails_closed_with_zero_model_calls` (Engine world, fake gateway counts calls) | integration | GU-1 | H×H | word `fail_closed` → JOIN raises the helper |
| 9 | `fired_guard_skips_the_inner_label_model_and_records_it_not_run` | integration | GU-5, Q18 | H×H | DECIDE lists not-run-body selectors; LabelModel call placed inside the guard's `otherwise` scope |
| 10 | `fired_guard_records_inner_keywords_labels_as_computed` | integration | GU-5 | H×H | the tree's one KEYWORDS source feeds DECIDE ([branch-core](branch-core.md) D6); DECIDE never reads the Case input |
| 11 | `classifier_guard_fails_closed_after_exactly_one_call` | integration | GU-2 | H×H | — |
| 12 | `fail_closed_and_abstain_split_under_both_failure_policies` (withhold vs coverage_declare score + coverage) | integration | GU-6 | H×H | no code change expected; pins the policy outcome |
| 13 | `jailbreak_fixture_fires_on_all_shaped_and_no_benign_input` | integration | GU-12 | H×M | fixture `ET/data/gate_contract/jailbreak_inputs.json` |
| 14 | `budget_refused_floor_abstains_and_never_runs_the_router` | integration | GU-13 | H×M | refused recipe branch + recipe alternative → abstain `budget_refused` |
| 15 | `one_classifier_read_by_two_guards_runs_once` | integration | GU-3 | H×M | selector sharing ([selectors](selectors.md)) |
| 16 | `floor_guard_runs_the_stronger_branch_and_zero_router_calls` | integration | GU-4 | H×M | — |
| 17 | `fail_closed_case_is_not_a_refusal` | unit | GU-14 | H×M | no change in `represents_refusal` |
| 18 | `fail_closed_message_names_the_gate_and_never_the_input` (property: random inputs never appear in the message) | unit | GU-16 | H×M | fixed text + gate id |
| 19 | `gate_refuses_python_callables_with_the_guard_message` (parametrized: `when=`, `then=`, `otherwise=`) | unit | GU-8 | H×M | type checks in `S/_surface/gate.py` |
| 20 | `unparsed_classifier_reply_does_not_fire_an_eq_guard` | integration | GU-10 | H×M | null label compares false |
| 21 | `ne_guard_fires_on_an_unparsed_classifier_reply` | integration | GU-10 | H×M | `cmp: "ne"` for `label:` (erd §1 change) |
| 22 | `failed_classifier_call_skips_eq_guards_and_fires_ne_guards` | integration | GU-11 | M×M | `;optional` selector call; null label (P7) |
| 23 | `keywords_guard_refuses_a_non_re2_pattern_before_spend` | unit | GU-9 | M×M | reuse `S/_regex_rule.py` check |
| 24 | `benign_case_passes_every_guard_and_runs_the_router` | integration | GU-7 | M×M | — |
| 25 | `report_export_names_the_fired_guard` | integration | GU-20 | M×M | `OperationOutput.decision` + Case failure code |
| 26 | `fail_closed_in_a_skip_gate_member_is_refused` | unit | GU-17 | M×L | skip-Gate `then=` must be a recipe |
| 27 | `panel_gate_otherwise_fail_closed_fails_after_the_panel` | integration | GU-18 | M×L | — |
| 28 | `guard_on_a_later_stage_reads_the_case_input` | integration | GU-19 | M×L | Case-level selector input |
| 29 | `activity_failure_sets_do_not_gain_fail_closed` | unit | GU-21 | L×M | no change |
