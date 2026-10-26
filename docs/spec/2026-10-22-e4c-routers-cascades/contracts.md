# Contracts: E4c connections

One section per connection. Path prefixes and the interview ledger: [00-overview](00-overview.md).
Each contract names the PRD tests that pin it (TDD row numbers of the PRD §7). All endpoints below
run inside one Case on the Engine's url4 node; "timeout" and "retry" follow the url4 subtree they
sit in unless stated.

## C1 — Gate compile → url4 expression, SDK → url4, data (expression bytes)

- Shape: one nested named inner expression per Gate (the corrective pattern
  [existing `S/_evaluation/corrective.py:193-200`]):
  ```
  [keywords_N  = /ensemble/select/v1/keywords($input)!'<keywords specs>'   # once, top of the Gate tree]
  [selector_N  = LabelModel call ;optional, binding=selector_N             # lowest scope that reads it]
  [synthesis_N = panel decision call (combine; phase=decide for a lazy E4b fallback)]
  gate_N_after     = /ensemble/branch/v1/after(r1:0.0:$synthesis_N, r2:0.0:$<gate input>, r3:0.0:$<selector/keywords>…)!'after'
  gate_N_decide    = /ensemble/branch/v1/decide(<C2 context with "after": "$gate_N_after">) gate=gate_N !'decide'
  gate_N_open_then = /ensemble/branch/v1/open($gate_N_decide)!'then'
  gate_N_then      = iterate(ref(gate_N_open_then), body=<then body>, intent=$<then ref>, on_error="fail")
  gate_N_open_else = /ensemble/branch/v1/open($gate_N_decide)!'otherwise'
  gate_N_else      = iterate(ref(gate_N_open_else), body=<otherwise body>, …)
  gate_N           = /ensemble/branch/v1/join({decision:$gate_N_decide, then:$gate_N_then, otherwise:$gate_N_else}) binding=gate_N !'join'
  gate_N_block     = ( …the sources above… )!'$gate_N'          # the one named inner expression
  ```
- AFTER is pure: it never parses its context and returns `""`. It exists only to give DECIDE url4
  dependency edges to the decision call, the Gate input and the selectors DECIDE reads; its slots
  are instrumental (weight `0.0`), so they keep the edge and pack no answer bytes [existing
  `U/dag/nodes/_shared.py:231`, `U/dag/fetch.py:143`]. Every ancestor call is upstream of these or
  precedes the enclosing OPEN. The renderer asserts that each AFTER reference resolves to a binding
  in scope ([branch-core](prd/branch-core.md) D10, BC-38).
- GATE_SPEC `terminal` names each recipe body's terminal binding; JOIN copies that operation's
  recorded result ([branch-core](prd/branch-core.md) D12).
- Bodies are inline: a recipe body's sources sit in the iterate body text (no `MEMBER_ROUTE`), so
  their calls reach the Case recorder ([branch-core](prd/branch-core.md) D1). Every call inside a
  body, and every call under `sf.Budgeted`, carries `binding=<name>` first (D3). A body references
  only bindings that run unconditionally in an enclosing scope: the Gate input, the tree's KEYWORDS
  source, hoisted LabelModel selectors, the panel members and the decision call (D5, compile-time
  check). A step body that is the decision call's own reducer has no iterate: JOIN reads the
  decision call output and result (D12). A word body has no sources.
- Skip-Gate member (Q16): the member's DECIDE sits before the panel; the slot holds OPEN, the
  iterate and JOIN; under `quorum="all"` the slot is required, under a numeric quorum it is
  `;optional` and the panel carries url4 `quorum=0`; an unselected member's JOIN returns `""`
  ([skip-members](prd/skip-members.md), branch-core D8).
- Cascade gated stage: members `;optional`, stage panel url4 `quorum=0`
  ([cascade](prd/cascade.md) CA-6).
- A Fanout with a skip-Gate member always takes the panel compile path, also under
  `quorum="all"` (where a plain Fanout with no optional member compiles flat, [existing
  `S/_evaluation/candidate.py:361-376`]) ([skip-members](prd/skip-members.md)) [proposed — review 3 F8].
- Policies: deterministic bytes (same recipe → same expression); one candidate-wide counter per
  binding kind; depth ≤ 8; no grammar change [stated ans:Q1].
- Failure: the SDK refuses an invalid recipe before any run (gate GT-11…16, cascade CA-12…18,
  selectors SL-13…15, budget BU-9…15).
- Contract tests: branch-core #10, #17, #17a, #25, #35; gate #6, #9, #19, #32; cascade #8;
  lazy-fallback #17, #18; skip-members #3, #5, #5a, #5b.

## C2 — DECIDE, url4 node → Engine endpoint `/ensemble/branch/v1/decide`, sync, pure

- Request: intent `decide`; param `gate=gate_N`; context (canonical JSON):
  ```json
  {"spec": <gate-spec.v1>,
   "after": "$gate_N_after",
   "inputs": {"keywords": "$keywords_N",
              "selectors": {"sel_2": "<LabelModel reply text, or the literal $selector_N when the call failed>"},
              "panel": {"binding": "synthesis_N", "phase": "decide" | null} | null}}
  ```
  `after` resolves to `""` (AFTER); `keywords` resolves to the KEYWORDS response, which also holds
  the Case input `summary` (C7).
  The Keywords results cover every Keywords selector of the Gate tree, so a fired guard still
  records the router's Keywords labels ([branch-core](prd/branch-core.md) D6). The budget cap is NOT
  in the context: the Engine binds it once per Attempt from the candidate's typed budget annotation
  (C6) in a ContextVar set before the expression runs, so every task inherits it (a value set
  inside a running task would stay invisible to its siblings); DECIDE folds the recorded charges of every call whose fingerprint is in
  `spec.ancestors` (`current_operation_calls()`; E4a charge rule [existing
  `E/budget.py:185-206`]); pending and combine records charge nothing (D7). A panel gate's DECIDE
  reads the decision call's E4b gate record from `current_operation_calls()` by the decision call's
  fingerprint: `combine.gate` for a complete call, `OperationCall.gate_record` for a pending
  outcome (D11), and maps it by the panel branch rule (D4). Nothing is kept in request scope.
- Response: one `gate-decision.v1` record ([erd §3](erd.md)) with `result` unset, also published
  under the JOIN fingerprint (C5).
- Policies: pure given its inputs + recorded accounting; no model call; context ≤ 1 MiB (the
  references sit in AFTER, never in DECIDE); closed key sets; idempotent (same inputs → same bytes);
  DECIDE never reads the Case input.
- Failure (callee): malformed context, schema id, cmp/observe pair, unknown selector id, budget read
  with no Budget → permanent `benchmark_contract_error`, message names the field, never echoes
  input. Failure (caller): url4 fails the Gate; the Case fails.
- Contract tests: branch-core #4, #9, #10, #24, #31, #32, #37; selectors #6–#8; budget #4–#10,
  #14; cascade #4, #5, #6; guards #8–#11.

## C2b — AFTER, url4 node → Engine endpoint `/ensemble/branch/v1/after`, sync, pure

- Request: intent `after`; context: instrumental slots (`rK:0.0:$x`) that reference the decision
  call `$synthesis_N`, the Gate input and the selectors DECIDE reads. url4 leaves weight-0.0 slots
  out of the packed context, so the request carries no answer bytes. Response: `""`. It never
  parses or keeps its context.
- Policies: pure; one per Gate; every reference resolves to a binding in scope (renderer check)
  [proposed — review 3 F5].
- Failure: an ancestor that failed has already failed its scope; AFTER adds no failure mode.
- Contract tests: branch-core #10, #17a, #32.

## C3 — OPEN, url4 node → Engine endpoint `/ensemble/branch/v1/open`, sync, pure

- Request: intent `then` | `otherwise`; context: the DECIDE record.
- Response: `[{}]` iff `record.branch` equals the intent, else `[]` (the corrective `continue` gate
  shape [existing `E/world/corrective.py:137-143`]).
- Policies: pure; one-item cap.
- Failure: a non-record context or an unknown intent → permanent `benchmark_contract_error`.
- Contract tests: branch-core #3, #12; lazy-fallback #6, #7.

## C4 — JOIN, url4 node → Engine endpoint `/ensemble/branch/v1/join`, sync, pure

- Request: intent `join`; exactly one param, the string `binding=gate_N`; context `{decision,
  then, otherwise}`. url4 hands JOIN the iterate results already joined into text [existing
  `U/dag/nodes/_shared.py:51-65`], so JOIN decides from `decision.branch`, never from the slot
  texts (D12).
- Response: plain text — the taken branch's text verbatim, with `decision.result` copied from
  that branch's `terminal` operation (a terminal model call gives `answered`; a terminal combine
  call or inner JOIN gives its own result, so a nested abstain reaches the root); for a step slot
  and for no branch (band hit, no voters with a step or the word `abstain` as `otherwise`), the
  decision call's output with its combine result copied (answered, or abstain with its reason;
  D12); a raise of `fail_closed` for no voters with the word `fail_closed` as `otherwise`; `""`
  with `result = {"status":"abstain","reason":"gate_not_met" | "budget_refused"}` for a word or a
  refusal; a raise of the permanent failure `fail_closed` (helper `fail_closed(gate_id)` in
  `E/benchmarks/failure_classes.py`); or `""` with `result` null for a skip-Gate member not
  selected. No envelope crosses JOIN; a refusal inside a body propagates before JOIN as in a
  Pipeline stage ([branch-core](prd/branch-core.md) D2).
- Policies: pure; both slots non-empty → `benchmark_contract_error` (GD-I1); the completed record
  is published with `record_gate_call` (C5).
- Failure: body failures propagate through `on_error="fail"` before JOIN runs; DECIDE's record
  stays (branch-core BC-10).
- Contract tests: branch-core #5, #6, #6a, #6b, #11, #15, #18, #19, #20, #23; guards #6, #8;
  cascade #10, #11, #11a; skip-members #4.

## C5 — Operation attribution: Engine → Case result, data

- Shape: `OperationOutput.decision: GateDecision | None` [existing
  `E/benchmarks/contract.py:356-378`], left out of the wire when absent (the `combine` rule).
  `OperationCall` gains `decision`, `pending` and `gate_record`; `record_gate_call` beside
  `record_combine_call` [existing `E/operation_calls.py:193-217`]. DECIDE and JOIN publish under the
  JOIN fingerprint (JOIN route, `binding=gate_N`); the last-call rule keeps JOIN's record when JOIN
  ran ([branch-core](prd/branch-core.md) D3).
- Attribution walks Gate blocks (`gate_N_block`) and the iterate bodies inside them
  (`f"({body})!{intent}"` or `f"({body})"`, the text MapNode builds [existing
  `U/dag/nodes/iteration.py:100`]) recursively; other inner expressions (`loop_candidate`) stay
  opaque; a gated binding with no recorded call emits no operation; the pattern widens to `gate` and
  `selector` in `E/benchmarks/operation_outputs.py:52`, `S/_operation_bindings.py:5-15` (with
  `OPERATION_REFERENCE`, `TOPOLOGY_BINDING` + `gate_\d+_block`, and the url4 decode patterns
  `S/url4.py:74-76`) and the Engine-only `ET/data/combine_contract/binding_names.json` that the SDK
  conformance test reads (PIN); the combine call's own `binding=synthesis_N` check is unchanged.
  `final_operation_abstained` follows the root `$name` through Gate blocks and accepts a terminal
  JOIN whose decision result is `abstain`.
- Policies: one decision per Gate per Case; an unselected body leaves no operation output; a pending
  combine record gives output `""` and no evidence.
- Contract tests: branch-core #2, #7, #8, #11, #14, #26, #27, #30, #31; report #3, #5.

## C6 — url4 wire forms: rebuild, combine route params, budget annotation, data

- `Url4(...).to_python()` rebuilds a Gate tree from the C1 shape and must recompile to the same
  bytes (RB-1 [existing `S/_surface/rebuild.py:99-114`]); `_PROVED_SPEC_KEYS` [existing
  `S/url4.py:92`] gains `gate` [proposed — [gate](prd/gate.md)].
- Combine route params: `{binding}` or `{binding, phase: "decide"}`; `phase=decide` with a
  fallback key in the context → `combine_spec_invalid`; without `phase`, behavior is today's
  [proposed — [lazy-fallback](prd/lazy-fallback.md)].
- Typed budget annotation on the candidate source only: `<name>:0.0:usd=<n>:tokens=<n>:<expr>` plus
  `;budget_mode=advisory`; a budget on any inner source or an unknown key → the Engine refuses the
  candidate with the permanent `benchmark_definition_error` [proposed — [budget](prd/budget.md)
  BU-15]. url4 Part E §24 conformance is a question for the url4 owner (overview §7).
- Contract tests: gate #22–#24; lazy-fallback #4, #14, #15, #19, #20; budget #12, #13, #17.

## C7 — Selectors: KEYWORDS endpoint and LabelModel call

- KEYWORDS: `/ensemble/select/v1/keywords`, one source per Gate tree that reads any selector (also
  a tree with only a LabelModel); intent = the canonical `keywords.v1` specs of the tree (possibly
  none); context `$input`; response `{"summary": {"chars": n, "sha256": "<16 hex>"}, "sel_<n>":
  {"labels": [...], "matched": [...]}, ...}`; pure; RE2; head window 65,536 chars; patterns
  pre-checked by `check_regex` (≤ 256 chars) [proposed — [selectors](prd/selectors.md),
  [branch-core](prd/branch-core.md) D6].
- LabelModel: one model call `selector_N` with the `label-template@1` prompt and the user message
  `{"input": …}`; `;optional`; a failed call leaves `$selector_N` unbound, so DECIDE receives the
  literal text and records `status: "failed"`, `parse_error: null` (the default branch runs);
  default `max_tokens` 16 (one label) / 64 (multi); reply cap 64 KiB; parsed by DECIDE with
  `parse_selector_reply` (`E/combine/ports.py`, beside `parse_label`) [proposed]. `sel_<n>` is the
  spec id; `selector_N` is the call binding.
- Accounting: operation kind `selector` → stage `synthesis` [existing `S/accounting.py:44-52`
  extended]; budget stage `selector` [existing `E/budget.py:25` extended] [proposed].
- Failure: a model reply is untrusted data; it can only select a declared label or none; never
  executed or echoed beyond the 64-char `raw` token.
- Contract tests: selectors #3–#8, #14, #17, #22; branch-core #33; guards #9, #11, #15;
  skip-members #11, #15.

## C8 — SDK decode and report export: Case result → SDK report, data

- Shape: `CaseOperation.decision`, strict decoder `decode_gate_decision`
  (`S/_evaluation/gate_decision.py`), mirror of C5; report.v1 export gains `operations[].decision`
  additively; the reserved `budget` trace kind gets `event: "refusal"` rows (no new trace kind)
  [proposed — [report](prd/report.md), [budget](prd/budget.md)].
- Policies: unknown key, missing key, wrong schema id or broken invariant → `ExecutionError` naming
  the field path; an older SDK refuses `decision` → the SDK release ships first (OME-1233).
- Contract tests: report #3, #4, #5, #8, #32; budget #27.

## C9 — Offline Engine contract fixtures: Engine tests ↔ SDK tests, data

- `ET/data/gate_contract/decision_cases.json`: one decision record per scenario (both packages read
  it; the SDK report tests build Cases from it) [proposed].
- `ET/data/gate_contract/*.url4`: one compiled expression per recipe (`d1_keyword_router` …
  `d10_adaptive_sampling`, [docs](prd/docs.md)); the README blocks compile to these bytes; the
  Engine runs them on the fake gateway [proposed].
- Policies: offline only; no network, no paid test; fixtures change only with an owner-approved
  manifest (`.claude/test-change-approvals/`, url4 fixtures under `tests/` included since
  `29fbcc286`) [existing `.claude/scripts/approved_test_changes.py:57`].
- Contract tests: branch-core #21; docs #3, #4, #16; report #3.

## C10 — Failure and abstain vocabulary: Engine ↔ SDK, data

- `fail_closed`: permanent; in `DECLARED_FAILURE_CODES` [existing `E/benchmarks/contract.py:58`]
  and `ENGINE_ERROR_CODES` [existing `E/error_text.py:63-80`]; SDK mirror `S/_report_primitives.py`;
  not in the activity `_FAILURE` sets (no model call fails with it) [proposed —
  [guards](prd/guards.md)]. Built in PR-1 (plan unit 1).
- `quorum_not_met`: permanent, engine-authored; in `DECLARED_FAILURE_CODES`, `ENGINE_ERROR_CODES`
  and the SDK mirror; raised by the combine call for a numeric quorum over the selected skip-Gate
  members (a `CombineError` code must be declared, [existing `E/combine/ports.py:111-116`]).
  Built in PR-2 (plan unit 11) [proposed — review 3 F4]. With it the declared count goes 66 → 67
  (PR-1, `fail_closed`) → 68 (PR-2).
- `budget_refused`: abstain reason, `E/combine/ports.py:56` and `S/answer.py:29`.
- Policies: one PR changes both lists; the SDK ships first (OME-1233); the exact-set pins change
  only with owner approval (`ET/test_failure_classes.py`, `ET/test_e4b_catalog_pins.py`,
  `ET/test_terminal_error_detail.py`).
- Contract tests: guards #3–#7, #29; skip-members #2a, #2b; budget #6.

## C11 — Skip members: combine context `selection` and evidence `skipped`, url4 → combine, data

- Context key `selection`: `$gate_N_decide` for each skip-Gate member (DECIDE sits outside the
  slot); the combine call excludes every member whose decision says not selected (its row is the
  empty JOIN text); evidence key `skipped` (member ids, last key, only when not empty); NR-I4
  widened. Under `quorum="all"` the slots are required: a selected member that fails fails the url4
  panel with its own code before the combine runs (ans:Q23) [existing `U/dag/nodes/guard.py:96-140`].
  Under a numeric quorum the slots are `;optional`, the url4 panel quorum is 0, and the combine call
  checks the floor over the selected members → `quorum_not_met` [proposed —
  [skip-members](prd/skip-members.md)].
- Contract tests: skip-members #6–#10, #20, #21.

## C12 — Dependency: Engine branch runtime → combine library

- Rule: `E/world/branch.py` (DECIDE/OPEN/JOIN/KEYWORDS) may import `E/combine/gate.py` (pure
  `observed_number`, `passes`) and `E/combine/ports.py`; `E/combine/` never imports `E/world/`
  [proposed]. Enforced by the existing layering check (`.claude/scripts/check_layering.py`, an
  Engine gate step) plus one arch test that imports `E/combine/*` with `E/world` blocked.
- Contract tests: branch-core #39; the layering gate.
