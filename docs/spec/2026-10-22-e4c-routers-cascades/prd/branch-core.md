# PRD: Branch core — the gated-iterate runtime (component)

**Source:** epic OME-1291 ("a branch that is not selected makes zero model calls, and the report
says it was not selected and why"), ans:Q1, ans:Q6, ans:Q22 · **Priority:** P0 (every flow uses it)
**Lifecycle:** planned (new Engine endpoints, new SDK renderer, extended attribution), on top of the
existing corrective runtime pattern · **Owner:** unassigned
Paths: [erd §1, §3, §4, §6](../erd.md) · contracts: C1–C5, C9, C12 · used by: [gate](gate.md),
[lazy-fallback](lazy-fallback.md), [cascade](cascade.md), [selectors](selectors.md),
[skip-members](skip-members.md), [guards](guards.md), [budget](budget.md), [report](report.md)

## 1. Flows served and user story

Every E4c flow compiles a decision to the same url4 shape and runs it through the same Engine
endpoints. This PRD owns that shape, the endpoints, the attribution of the operations inside gated
bodies, the decision record lifecycle and the "zero calls when not selected" guarantee. The flow
PRDs own the public surface and the conditions. Flows served: [gate](gate.md),
[lazy-fallback](lazy-fallback.md), [cascade](cascade.md), [skip-members](skip-members.md),
[guards](guards.md), [budget](budget.md); [report](report.md) reads its records.

As a researcher whose recipe chooses which models run, I want a branch that the recipe did not
choose to cost nothing and to leave a record that says why, so that my saving is real and every
skip is auditable in the report.

## 2. Background and constraints

- "This epic adds three constructs. They share one rule: a branch that is not selected makes zero
  model calls, and the report says it was not selected and why." [stated epic]
- Mechanism: the CorrectiveLoop shape — an Engine endpoint returns a 0-or-1-item collection and
  `iterate(ref(gate), body=…)` runs nothing on an empty collection; no url4 grammar change.
  [stated ans:Q1]
- `sf.Gate` is the one branch construct; `then=`/`otherwise=` may be whole recipes. [stated ans:Q6]
- url4 Spec B §5.3.9: "If the collection reference resolves to an empty collection … No elements
  are evaluated." [existing spec-B.md §5.3.9]
- "Calls avoided" is a min–max range over the paths through a skipped body. [stated ans:Q22]

### 2.1 Current behavior (the pattern this PRD reuses)

- The url4 executor gathers every dependency of a node before the node resolves
  [existing `U/dag/executor.py:168-184`]. Only nodes that spawn work in `resolve` can withhold it:
  `MapNode` spawns one body per element and returns `[]` for an empty collection
  [existing `U/dag/nodes/iteration.py:57-112`]. The body is a template; MapNode builds
  `f"({body})!{intent}"` once and spawns it per row [existing `U/dag/nodes/iteration.py:100`].
- Every `$name` that a body or its intent mentions becomes a `bind:` dependency of the MapNode when
  the enclosing group declares that name, and dependencies run even for an empty collection
  [existing `U/dag/_lowering.py:331-346`].
- The corrective runtime registers pure endpoints once per world
  [existing `E/world/corrective.py:74-88`]: `_gate` returns `[]` or `[{…}]` [existing
  `E/world/corrective.py:124-163`]; `_answer` collapses `{selected, next}` [existing
  `E/world/corrective.py:207-227`]; `_RecipeInvocation` evaluates a nested Recipe with
  `isolated=True` [existing `E/world/corrective.py:104-110`], and `capture_operation_calls(
  isolated=True)` starts a fresh recorder chain, so the parent never sees those calls
  [existing `E/operation_calls.py:88-98`].
- Attribution scans only root sources and the children of `panel_N` sources; any other nested
  binding stays opaque [existing `E/benchmarks/operation_outputs.py:176-209`]. It matches recorded
  calls to bindings by fingerprint (path, sorted params); one claimant takes the last call, several
  claimants give null when any is optional [existing `E/benchmarks/operation_outputs.py:15-26`].
  `final_operation_abstained` reads only a root intent that is exactly `$name` and only combine
  evidence [existing `E/benchmarks/operation_outputs.py:94-123`].
- Combine steps publish to the recorders through `record_combine_call` [existing
  `E/operation_calls.py:193-217`]. The `binding` param names a call for attribution and the Engine
  never forwards it [existing `S/_operation_bindings.py:20-22`].
- The SDK renderer nests a gated construct in one named inner expression, because "gated
  iterations may not sit bare in the outer intent-bearing group" [existing
  `S/_evaluation/corrective.py:193-200`], and compiles a nested Recipe with `_capture_recipe`
  [existing `S/_evaluation/candidate.py:294`].
- No E4c endpoint, record or renderer exists [existing `S/`, `E/` (no `gate-decision` match)].

### 2.2 Design (delta)

- **D1 Inline bodies.** A recipe body is compiled with `_capture_recipe` and its sources are placed
  directly in the iterate body. It does NOT go through `MEMBER_ROUTE`. The spawned body runs in the
  Case's context, so its calls reach the Case recorder chain like any other call. [proposed —
  review finding 2]
- **D2 JOIN returns plain text.** An iterate slot holds `[]` or one text (the body's result). JOIN
  returns that text, or the decision call's output for a step slot, or the abstain answer `""`, or
  raises. A refusal inside a body raises `provider_refusal` in the body and propagates through
  `on_error="fail"` exactly as a refusal in a Pipeline stage does. No envelope crosses JOIN.
  [proposed — review finding 7]
- **D3 Attribution of gated bodies.**
  - JOIN carries exactly one param, the string `binding=gate_N`, and publishes its completed
    record through a new `record_gate_call(path, params, output, decision)` beside
    `record_combine_call`; `OperationCall` gains `decision: GateDecision | None = None`. DECIDE
    carries the param `gate=gate_N` (D11) and publishes its record (result unset) under the JOIN
    fingerprint (JOIN route, `binding=gate_N`), so the last-call rule keeps JOIN's record when JOIN
    ran and DECIDE's record when a body failed before JOIN. [proposed]
  - `_operation_bindings` walks recursively, but only into Gate constructs: root sources, `panel_N`
    children (today), every Gate block (a named inner expression `gate_N_block` whose intent is
    `$gate_N`), and every source whose value is an `Iteration` inside a Gate block, whose body is
    parsed as `f"({body})!{intent}"` (or `f"({body})"` when the iterate has no intent), the text
    MapNode builds [existing `U/dag/nodes/iteration.py:100`]. Gate bodies never use `$item`, so the
    template parses unchanged; a body that does not parse stays opaque (today's rule). Any other
    named inner expression, for example the corrective `loop_candidate`, stays opaque as today.
    [proposed — review 2 F12]
  - Every call inside a gated body, and every call of a candidate under `sf.Budgeted`, carries
    `binding=<its name>` first, so each fingerprint has one claimant and is attributed. The
    attribution pattern widens to `gate` and `selector` (PIN). [proposed]
  - A binding inside a gated body with no recorded call emits no `OperationOutput` (absent = not
    run; the report reads the topology). [proposed]
  - `final_operation_abstained` follows the root `$name` through Gate block expressions whose
    intent is exactly `$x` to the outermost JOIN, and marks the Case abstained when that
    operation's `combine.result.status` or `decision.result.status` is `abstain`. JOIN copies the
    result of the branch that ran (D12, `terminal`), so an abstain deep inside nested bodies
    reaches the root JOIN. [proposed — review 3 F1]
  - Combine calls inside bodies (the lazy-fallback call #2, a cascade stage's decision call) are
    attributed by the same walk with their `binding=synthesis_N` param. [implied]
  - A pending combine outcome (lazy-fallback `phase=decide`) is published with `pending=True`
    (`OperationCall.pending`); attribution gives it output `""` and no evidence, and the accounting
    index and the budget fold skip it. [proposed — review finding 13]
- **D4 Panel branch rule.** DECIDE maps the decision call's E4b gate record branch
  [proposed — review findings 6 and review 2 F3; stated ans:Q17, ans:Q24, ans:Q25]:

  | Gate record branch | `otherwise` kind | `wanted` | `branch` | Result (JOIN, D12) |
  |---|---|---|---|---|
  | `majority` | any | `then` | `then` | the `then` body's text; the `then` terminal's result copied (for a step slot, the decision call's result) |
  | `fallback` | any | `otherwise` | `otherwise` | the `otherwise` body's text and its terminal's result copied, or the word |
  | `band` | any | null | null | abstain `in_band`, copied; no body runs, also when `then` is a recipe (ans:Q25) |
  | null (no voters: the combine abstained before the gate) | recipe | `otherwise` | `otherwise` | the next stage answers (escalation, ans:Q17; "no member answered", ans:Q24) |
  | null | step, or the word `abstain` | null | null | abstain with the decision call's reason (`no_votes`, `cut_not_met`, `output_missing`), copied; no body runs, also when `then` is a recipe (ans:Q25) |
  | null | the word `fail_closed` | null | null | JOIN raises `fail_closed`; the Case fails with code `fail_closed` (a gated last stage whose members all failed, [cascade](cascade.md) CA-30) [proposed — review 3 F7] |

  A budget refusal of `otherwise` whose fallback is a `then` step slot keeps the decision call's
  result: when that result is an abstain, the Gate abstains with the same reason; it never returns
  `""` marked `answered`. A partial member failure is not a null branch: the decision call reduces
  over the members that answered and the gate compares as usual (ans:Q24). The decision call
  writes combine `gate.otherwise` = `judge` or `writer` for an E4b `JudgePick` / `Synthesize`
  fallback ([lazy-fallback](lazy-fallback.md)), and `abstain` for every other `otherwise` (a recipe,
  another step, a word). So on an escalation its evidence reads `abstain` / `gate_not_met` with
  gate branch `fallback`; the report labels that Combine section "escalated" from the decision
  record. A step `otherwise` that is not the decision reducer compiles to its own combine call
  inside the `otherwise` body. [proposed — review finding 6]
- **D5 Body-reference invariant.** Every `$name` in a body or its intent becomes an eager
  dependency of the iterate [existing `U/dag/_lowering.py:331-346`]. So a body may reference only
  bindings that run unconditionally in an enclosing scope: the Gate input, the tree's KEYWORDS
  source, hoisted LabelModel selectors (placed at the lowest common scope, [selectors](selectors.md)
  SL-18), the panel members and the decision call. A model source whose only readers are inside one
  body is defined inside that body. The renderer checks each body's references and raises a
  compile-time error when a body references an outer model source that no unconditional reader
  needs. [proposed — review 2 F4]
- **D6 Keywords eagerly, LabelModel lazily.** One KEYWORDS source at the top of every Gate tree
  that reads a selector evaluates every Keywords selector the tree reads (pure, no model) and also
  returns `summary: {"chars": n, "sha256": "<16 hex>"}` of the Case input, so every SELECTOR_RECORD
  (Keywords and LabelModel) gets its input summary (erd §2) even when the tree has no Keywords
  selector. DECIDE receives these results and never reads the Case input. A LabelModel call stays
  at the lowest scope that holds every Gate that reads it ([selectors](selectors.md), ans:Q18).
  [proposed — review finding 12; review 2 F11]
- **D7 Ancestors are fingerprints.** GATE_SPEC `ancestors` lists the fingerprints (path, params)
  of the calls upstream of DECIDE. DECIDE folds the charges of every recorded call
  (`current_operation_calls()`, [existing `E/operation_calls.py:233-237`]) whose fingerprint is in
  that list; pending and combine records charge nothing. [proposed — review finding 2]
- **D8 Skip-Gate members.** A member Gate's DECIDE sits outside the member slot (before the
  panel); the slot holds OPEN, the iterate and JOIN; the combine reads `$gate_N_decide` in its
  `selection` context. Under `quorum="all"` the slot is required (as a plain member today); under a
  numeric quorum it is `;optional` and the panel carries url4 `quorum=0`. An unselected member's
  JOIN returns `""` (its record keeps `result` null) and the combine excludes that member through
  `selection`; nothing is raised. A selected member that fails under `quorum="all"` fails its
  required slot with its own code (ans:Q23) [existing `U/dag/nodes/guard.py:96-140`]
  ([skip-members](skip-members.md)). [proposed — review 2 F5]
- **D9 Calls avoided as a range.** NOT_RUN_ENTRY `model_calls` is `{"min": a, "max": b}`: the
  shortest and the longest path through the skipped body (nested Gates counted per path).
  [stated ans:Q22]
- **D10 DECIDE orders after what it reads.** url4 orders work only through dependency edges, and
  siblings start together [existing `U/dag/executor.py:168-184`]. Each Gate has one pure AFTER
  source `gate_N_after = /ensemble/branch/v1/after(r1:0.0:$a, r2:0.0:$b, …)!'after'` whose slots are
  instrumental (weight `0.0`): they keep the dependency edge but are left out of the packed
  context, so AFTER's request carries zero answer bytes [existing `U/dag/nodes/_shared.py:231`,
  `U/dag/fetch.py:143`; verified by the review 3 offline probe]. AFTER references only the decision
  call (panel gates), the Gate input, and the hoisted LabelModel selectors and the KEYWORDS source
  that DECIDE reads. It does not list every ancestor: every ancestor call is upstream of these
  (dataflow), or precedes the enclosing OPEN, because a gated body starts only after its OPEN
  resolved. The renderer asserts that every AFTER reference resolves to a binding in scope, because
  url4 leaves an unknown `$name` verbatim with no edge and no error (a member inside a `member_i`
  slot expression is not visible to its outer siblings, `S/_evaluation/candidate.py:378-397`).
  AFTER never parses its context and returns `""`; DECIDE's context holds
  `"after": "$gate_N_after"`, which resolves to `""`, so DECIDE runs after all of them and its own
  context stays under the 1 MiB cap. [proposed — review 3 F5] A field-path projection (`$x.f` → `""`) is not used, because
  a strict field mode raises `malformed_source` on a missing field [existing
  `U/dag/nodes/_shared.py:103-104`, `U/dag/semantics/ensemble.py:85-114`]. Selector and KEYWORDS
  results are referenced in DECIDE's `inputs` directly. [proposed — review 2 F1]
- **D11 Gate id and the pending record.** DECIDE carries the param `gate=gate_N`, so it can
  publish under the JOIN fingerprint. It reads the decision call's gate record from
  `current_operation_calls()` by the decision call's fingerprint (combine route, `binding=
  synthesis_N` and `phase=decide` when present): `combine.gate` for a complete call, the new
  `OperationCall.gate_record` for a pending outcome. Nothing is kept in request scope (a
  ContextVar set inside the combine task is not visible to its sibling) [existing
  `E/request_scope.py:145`]. [proposed — review 2 F6]
- **D12 JOIN copies the result of the branch that ran.** GATE_SPEC carries `terminal: {"then":
  <binding> | null, "otherwise": <binding> | null}`: the terminal binding of each recipe body (its
  last source: a model call, a combine call such as a stage Vote or lazy-fallback call #2, or an
  inner Gate's `gate_M`), null for a word body. A step slot's terminal is the decision call. JOIN
  reads that operation's recorded `combine.result` or `decision.result` from
  `current_operation_calls()` by fingerprint and copies its status and reason into
  `decision.result`; a terminal model call (no combine, no decision) gives `answered`. For a null
  panel branch it copies the decision call's result (`decision.panel.operation_id`). This works
  recursively: an inner JOIN publishes its record before the outer JOIN runs, because the outer
  iterate resolves only after the body did. JOIN's text is the slot text or the decision call's
  output (`""` for an abstain). JOIN decides from `decision.branch`, never from the slot texts:
  url4 joins an iterate result into text before JOIN reads it [existing
  `U/dag/nodes/_shared.py:51-65`]. [proposed — review 2 F3, F13; review 3 F1, F6]

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **BC-1 Not selected = zero calls.** Given a Gate whose condition holds, When the Case runs,
  Then the `otherwise` body makes zero model calls and zero endpoint calls inside its iterate,
  and the decision record lists `{"branch": "otherwise", "reason": "not_selected", "model_calls":
  {"min": …, "max": …}}`. [stated epic; stated ans:Q1; stated ans:Q22]
- **BC-2 DECIDE writes one record.** Given a Gate spec and its inputs, When DECIDE runs, Then it
  returns one `gate-decision.v1` record with `when`, `observed`, `passed`, `wanted`, `branch`,
  `selectors`, `not_run`, `budget` (null without a Budget) and `result` still unset, and publishes
  it under the JOIN fingerprint (D3). [proposed]
- **BC-3 OPEN is a pure 0/1 gate.** Given a decision record, When OPEN runs with intent `then`,
  Then it returns `[{}]` iff `branch == "then"`, else `[]`; the same for `otherwise`. [stated ans:Q1]
- **BC-4 JOIN returns the taken branch's text and its result.** Given a record with `branch ==
  "then"` and a `then` slot that holds the body's text, When JOIN runs, Then its output is that
  text byte for byte and `decision.result` is the `then` terminal's recorded result (`answered`
  for a terminal model call; the combine or inner decision result otherwise, D12); JOIN reads
  `decision.branch` to know which slot ran (D2, D12). [proposed — review 3 F1]
- **BC-5 Recipe bodies answer the Gate's input.** Given a recipe body, When it runs, Then its
  input is the input of the Gate: the Case input when the Gate is the root, the first Pipeline
  stage or in the first block; the previous stage's answer when the Gate is a later Pipeline stage
  (Pipeline semantics). It is never the panel answers of a panel gate, and the stages of a Cascade
  all answer the Cascade's input ([cascade](cascade.md)). [stated epic: "Each stage's prompt input
  is the original user question"; implied]
- **BC-6 Nesting.** Given a Gate in a branch body of another Gate, When the outer branch runs,
  Then the inner Gate runs its own DECIDE/OPEN/JOIN; when the outer branch does not run, the inner
  Gate makes zero calls and writes no record. [stated ans:Q10; stated ans:Q12]
- **BC-7 Record attached to the Case.** Given a finished Case, When the Engine attributes
  operations, Then the JOIN operation `op_gate_N` (binding `gate_N`) carries `decision` (the
  completed record, or DECIDE's record when JOIN did not run) and no other operation carries it.
  [proposed]
- **BC-23 Operations inside bodies are attributed.** Given a Gate whose taken body holds a model
  call and a combine call, When the Engine attributes operations, Then both appear with their own
  `op_` ids, outputs and evidence; the bodies' bindings are found inside named inner expressions
  and parsed iterate bodies (D3). [proposed — review finding 1]
- **BC-24 Body calls reach the Case recorder.** Given two nested internal Gates where the outer
  Gate's `otherwise` body (a model call) runs and holds the inner Gate, When the inner DECIDE runs,
  Then the outer body's call is in `current_operation_calls()`, the list the budget fold reads
  (D1, D7). The spend assertion itself is in [budget](budget.md). [proposed — review finding 2]
- **BC-31 DECIDE runs after its ancestors.** Given a panel gate whose decision call and two
  ancestor calls reply late (the fake gateway delays them), When the Case runs, Then DECIDE starts
  only after all three resolved, reads the decision call's gate record and folds both ancestors
  (D10). [proposed — review 2 F1]
- **BC-32 An E4b abstain still marks the Case.** Given an E4b gated vote with a lazy judge
  fallback at the candidate root, When the vote abstains (`no_votes`, `in_band`, `cut_not_met`),
  Then the root names `gate_N`, JOIN copies the abstain (D12) and the Case is scored 0 with
  `abstained: true`, as before E4c. [proposed — review 2 F3]
- **BC-36 A nested abstain reaches the root.** Given `sf.Cascade([s1, s2, s3], escalate_if=…,
  otherwise="abstain")` at the candidate root where every stage escalates, When the innermost Gate
  abstains `gate_not_met`, Then each outer JOIN copies its `otherwise` terminal's result (the inner
  JOIN's), the root JOIN's `decision.result` is that abstain, and the Case is scored 0 with
  `abstained: true` ([cascade](cascade.md) CA-9, CA-20). [proposed — review 3 F1]
- **BC-37 A recipe body that ends in an abstaining Vote.** Given an input Gate whose taken `then`
  body is `sf.Fanout([...]) >> sf.Vote()` and that vote abstains (`no_votes`, `cut_not_met`), When
  JOIN runs, Then it copies the vote's combine result and the Case is scored 0 with `abstained:
  true`, as the same vote at the root was before E4c. [proposed — review 3 F1]
- **BC-33 Band or no votes with a recipe `then`.** Given a panel gate whose `then` is a recipe and
  whose decision call hits the band (or finds no voters, with a step or word `otherwise`), When
  DECIDE runs, Then `wanted` and `branch` are null, no body runs, and the result is the decision
  call's abstain (`in_band` / `no_votes`). [stated ans:Q25]

### 3.2 Error paths

- **BC-8 Word `abstain`.** Given the taken branch is the word `abstain`, When JOIN runs, Then the
  output is `""` and `result = {"status": "abstain", "reason": "gate_not_met"}`; when the Gate is
  the candidate's final node, the Case is scored 0 with `abstained: true` (D3 final reference).
  [stated epic; proposed reason]
- **BC-9 Word `fail_closed`.** Given the taken branch is the word `fail_closed`, When JOIN runs,
  Then JOIN raises a permanent `fail_closed` failure, no model is called after DECIDE, and the
  Case is `failed` with code `fail_closed`, never an abstain. [stated epic]
- **BC-10 A body fails.** Given the taken recipe body fails permanently, When the iterate resolves,
  Then `on_error="fail"` fails the Gate and the Case with the body's own failure code; DECIDE's
  record stays on `op_gate_N` with `result` unset, so the report shows which branch failed.
  [proposed]
- **BC-11 Malformed contexts.** Given a DECIDE context with an unknown key, a missing input, a
  spec with a wrong schema id or a `cmp`/`observe` mismatch, When DECIDE runs, Then it raises the
  permanent `benchmark_contract_error` with a message that names the field and never echoes input
  text; OPEN and JOIN refuse a non-record context the same way. [proposed]
- **BC-12 JOIN sees two results.** Given both `then` and `otherwise` hold a result, When JOIN
  runs, Then it raises `benchmark_contract_error` ("a gate ran both branches"). [proposed —
  invariant GD-I1]
- **BC-27 Refusal inside a body.** Given the taken body's model refuses, When the Case ends, Then
  the Case outcome equals the outcome of the same refusal in a Pipeline stage (refusal text and
  `provider_refusal`), and DECIDE's record stays attached. [proposed — review finding 7]
- **BC-38 An AFTER reference out of scope.** Given a renderer change that makes AFTER reference a
  binding that is not visible in its scope (for example a member inside a `member_i` slot), When
  the recipe compiles, Then the compile raises the D10 renderer error, so DECIDE can never run
  before a call it reads. [proposed — review 3 F5]
- **BC-26 A body references an outer-only model source.** Given a renderer change that places a
  model source outside a body and references it inside, When the recipe compiles, Then the
  compile raises the D5 renderer error, so no hidden eager call can exist. [proposed — review
  finding 8]

### 3.3 Derived scenarios (risk-ordered)

| # | Title | Tag | I×L | G/W/T |
|---|---|---|---|---|
| BC-25 | Panel branch rule | [proposed — review finding 6; stated ans:Q25] | H×H | Given each row of the D4 table, Then DECIDE writes the stated `wanted` and `branch`, and JOIN the stated result; a budget-refused `otherwise` that falls back to an abstained `then` step slot abstains with that reason. |
| BC-13 | Replay takes the same branch | [implied — GD-I6] | H×M | Given a captured run whose ancestors all have reference costs, When it replays from the pinned cache, Then every DECIDE returns byte-identical records and the same bodies run. |
| BC-28 | Gate as a later stage | [proposed — review finding 7] | H×M | Given `A >> Gate(...) >> B`, Then B's input is JOIN's text (the taken branch's answer), never JSON. |
| BC-29 | Pending record is not a call | [proposed — review finding 13] | H×M | Given a `phase=decide` pending outcome, Then the accounting index and the budget fold skip it and its operation has output `""` and no evidence. |
| BC-34 | DECIDE context stays small | [proposed — review 2 F1] | H×M | Given ancestors whose answers total 8 MiB, Then DECIDE's context holds only `"after": ""`, ids, labels and numbers, and stays under 1 MiB; the AFTER source carries the references. |
| BC-35 | Pending gate record read | [proposed — review 2 F6] | H×M | Given a lazy E4b fallback, Then DECIDE finds the pending outcome by fingerprint in `current_operation_calls()` and reads its `gate_record`; no value is kept in request scope. |
| BC-14 | Bodies never hold live accounting in prompts | [proposed — corrective OME-1168 lesson `S/_evaluation/corrective.py:452-461`] | H×M | Given any body, When it is compiled, Then no prompt text contains a sibling's accounting envelope. |
| BC-15 | Stable operation ids | [proposed] | H×M | Given the same recipe compiled twice, Then every binding and `op_` id is equal. Body operations keep the attributed binding kinds with one candidate-wide number (`model_N`, `synthesis_N`, `judge_N`, `writer_N`); the JOIN is `gate_N`, a LabelModel call `selector_N`; the pattern widens in `E/benchmarks/operation_outputs.py:52`, `S/_operation_bindings.py:5-9` and the Engine-only `ET/data/combine_contract/binding_names.json` that the SDK conformance test reads (PIN); this also widens `OPERATION_REFERENCE`, `TOPOLOGY_BINDING` (plus `gate_\d+_block`) and the url4 decode patterns `S/url4.py:74-76`; the reference patterns gain the trailing boundary `(?![A-Za-z0-9_])` so helper names such as `$gate_3_after` never decode as `gate_3` [proposed — review 3 F10]. The combine call's own `binding=synthesis_N` check is unchanged. DECIDE, OPEN and AFTER use unattributed names (`gate_N_decide`, `gate_N_open_then`, `gate_N_open_else`, `gate_N_after`) and the Gate block is `gate_N_block`, as the corrective `loop_*` names do. |
| BC-16 | Not-run body leaves no operation | [implied] | H×M | Given a not-run body, Then no `OperationOutput` exists for its operations and the topology still lists them (planned), so the report can show them as not run. |
| BC-30 | Keywords once per tree | [proposed — review finding 12; review 2 F11] | M×M | Given four nested Gates that read two Keywords selectors, Then one KEYWORDS source runs once and every DECIDE receives its results; given a tree with only a LabelModel, Then the KEYWORDS source still runs and returns the input `summary`. |
| BC-17 | `model_calls` range | [stated ans:Q22] | M×M | Given a body with 3 model leaves and a nested Gate with 2 and 4 on its branches, Then its NOT_RUN_ENTRY has `model_calls = {"min": 5, "max": 7}`. |
| BC-18 | Depth cap | [proposed] | M×L | Given 9 nested Gates, When the SDK compiles, Then it raises "sf.Gate nests at most 8 deep" before any run. |
| BC-19 | Cancellation | [proposed] | M×L | Given the Case is cancelled while a body runs, Then the cancellation propagates like any url4 subtree; no partial branch is reported as taken. |
| BC-21 | Empty Case input | [proposed] | M×L | Given an empty Case input, Then DECIDE still decides from its inputs (a selector sees no match) and the default branch runs. |
| BC-22 | Large inputs | [proposed] | M×L | Given a DECIDE context over 1 MiB, Then DECIDE refuses it with `benchmark_contract_error` (the inputs are labels, numbers and ids, never answers). |
| BC-20 | Concurrent siblings | [implied] | L×M | Given two Gates side by side in one Case, Then each DECIDE reads only its own declared inputs; their records do not share state. |

State table (per Gate per Case):

| State \ event | DECIDE ok | DECIDE error | OPEN(then/otherwise) | body ok | body error | JOIN |
|---|---|---|---|---|---|---|
| pending | decided (record published, result unset) | failed (contract error) | refused (needs decided) | — | — | refused |
| decided | refused (one decision) | — | open/closed per branch | — | — | refused until both iterates resolved |
| branch running | — | — | — | branch done | failed (body code; DECIDE record kept) | — |
| branch done | — | — | — | — | — | joined (answered/abstain/fail_closed; record republished) |
| joined | — | — | — | — | — | refused (one join) |

## 4. Non-functional requirements

- Overhead per Gate: DECIDE, 2×OPEN and JOIN, all pure and local; target < 5 ms CPU per Gate at
  p99 on the Engine-world test host [proposed].
- The not-run guarantee is structural (empty collection plus the D5 invariant), not a runtime
  check that could be skipped [implied].
- Observability: each JOIN logs `gate=<id> branch=<then|otherwise|none> result=<status>`, never
  input text (OME-990 log rule) [proposed].
- Security: DECIDE/OPEN/JOIN read only labels, numbers, ids and texts they pass through; they never
  interpret model text as instructions; the 1 MiB context cap bounds parse cost [proposed].
- Attribution cost: the recursive walk parses each iterate body once per Case result; bodies are
  bounded by the depth cap (8) [proposed].

## 5. Out of scope

- A url4 grammar change (`;when=` annotations) [stated ans:Q1].
- Parallel race with cancellation of slower branches (OME-1465 race form, OME-559) [stated ans:Q5].
- Clusters / embeddings [stated ans:Q4].
- Retrying a failed body in the other branch (that is a Cascade with failure escalation, owned by
  [cascade](cascade.md)) [stated ans:Q17].

## 6. Open questions

None.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: core-out and risk-first. CHAR rows first (they pin the corrective pattern and today's
attribution), then the endpoints and attribution (the blocker), then the Engine-world runs (they
need the renderer of plan unit 3). RED first, always; a test that passes at once proves nothing.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `corrective_continue_gate_empty_runs_no_body` (an empty gate collection runs no deeper round) | integration | [existing `E/world/corrective.py:17-26`] | H×M | passes today |
| 2 | CHAR `attribution_keeps_the_corrective_loop_candidate_opaque` (only Gate blocks are walked; `loop_candidate` bindings stay opaque before and after E4c) | unit | [existing `E/benchmarks/operation_outputs.py:176-209`] | H×H | passes today and after row 7 |
| 3 | `open_returns_one_item_only_for_the_taken_branch` (decision table: then/otherwise × branch then/otherwise/null) | unit | BC-3 | H×H | `E/world/branch.py` `_open` |
| 4 | `decide_writes_one_record_with_every_field` | unit | BC-2 | H×H | `_decide`, `GateDecision` model |
| 5 | `join_returns_the_taken_branch_text` | unit | BC-4 | H×H | `_join` (D2) |
| 6 | `join_copies_the_decision_call_result_on_a_step_slot_and_a_null_branch` (answered, abstain `in_band` / `no_votes` / `cut_not_met`) | unit | BC-32, BC-33 | H×H | `_join` reads `decision.panel.operation_id` (D12) |
| 6a | `nested_cascade_abstain_reaches_the_root_and_marks_the_case_abstained` | integration | BC-36 | H×H | JOIN copies the `terminal` result (D12) |
| 6b | `recipe_body_ending_in_an_abstaining_vote_marks_the_case_abstained` | integration | BC-37 | H×H | `terminal` = the body's combine call |
| 7 | `attribution_walks_gate_blocks_and_their_iterate_bodies` (body model op, call #2 evidence, `op_gate_N.decision`; iterate with and without intent) | unit | BC-23 | H×H | recursive `_operation_bindings` limited to `gate_N_block`; `f"({body})!{intent}"` / `f"({body})"` parse |
| 8 | `gate_call_record_last_write_wins` (JOIN over DECIDE; DECIDE alone when a body failed; DECIDE carries `gate=gate_N`, JOIN exactly one `binding` param) | unit | BC-7, BC-10 | H×H | `record_gate_call`, `OperationCall.decision` (D3, D11) |
| 9 | `panel_branch_rule` (decision table D4: majority / fallback / band / null × otherwise kind × then kind, incl. null with the word `fail_closed` → `fail_closed`; the budget-refused case is budget #5) | unit | BC-25, BC-33 | H×H | `_decide` panel mapping |
| 10 | `decide_runs_after_every_ancestor_with_delayed_replies` (fake gateway delays the decision call and two ancestors; also a delayed member behind a quorum panel) | integration | BC-31 | H×H | AFTER source with instrumental slots (D10) |
| 11 | `e4b_vote_abstain_under_a_lazy_gate_still_marks_the_case_abstained` (no_votes, in_band, cut_not_met at the root) | integration | BC-32 | H×H | D12 + `final_operation_abstained` follows `gate_N_block` |
| 12 | `not_selected_branch_makes_zero_calls` (Engine world, fake gateway counts calls per binding) | integration | BC-1 | H×H | renderer + endpoints |
| 13 | `body_calls_reach_the_case_recorder` (two nested internal Gates: the outer taken body's call is in `current_operation_calls()` when the inner DECIDE runs) | integration | BC-24 | H×H | inline bodies (D1) |
| 14 | `final_reference_follows_inner_expressions_to_the_gate` (word `abstain` at the root → Case abstained) | integration | BC-8 | H×H | `final_operation_abstained` |
| 15 | `fail_closed_word_fails_the_case_with_fail_closed` | integration | BC-9 | H×H | JOIN raises `fail_closed()` helper |
| 16 | `recipe_body_input_is_the_gate_input` (root and first stage: the Case input; later Pipeline stage: the previous answer; never the panel) | integration | BC-5 | H×H | `_capture_recipe(input_context=<gate input>)` |
| 17 | `body_references_only_unconditional_outer_bindings` (a hoisted selector and the panel are allowed; an outer model source read only inside one body is a compile error) | unit | BC-26 | H×H | D5 check in the renderer |
| 17a | `after_references_resolve_to_in_scope_bindings` (an AFTER reference to a `member_i` slot member is a compile error; AFTER's packed context is empty) | unit | BC-38 | H×H | D10 check in the renderer |
| 18 | `refusal_inside_a_body_matches_a_pipeline_stage_refusal` | integration | BC-27 | H×M | refusal propagates (D2) |
| 19 | `gate_as_later_stage_passes_its_text_to_the_next_stage` | integration | BC-28 | H×M | — |
| 20 | `join_refuses_two_results` | unit | BC-12 | H×M | GD-I1 check |
| 21 | `replay_returns_identical_decision_records` | integration | BC-13 | H×M | records depend only on inputs + reference costs |
| 22 | `nested_gate_in_unselected_body_writes_no_record` | integration | BC-6 | H×M | nested iterate |
| 23 | `failed_body_fails_the_case_and_keeps_the_decide_record` | integration | BC-10 | H×M | `on_error="fail"` |
| 24 | `decide_refuses_malformed_context_without_echo` (parametrized: unknown key, schema id, cmp/observe pair, missing input) | unit | BC-11 | H×M | closed key sets |
| 25 | `operation_ids_are_stable_and_gated_calls_carry_the_binding_param` | unit | BC-15 | H×M | renderer naming |
| 26 | PIN `binding_names_admit_gate_and_selector` (Engine-only `ET/data/combine_contract/binding_names.json`, `E/benchmarks/operation_outputs.py:52`, `S/_operation_bindings.py:5-15` incl. `TOPOLOGY_BINDING` `gate_\d+_block`, `ST/unit/test_binding_pattern_conformance.py`; the widened `OPERATION_REFERENCE` and `S/url4.py` `_REFERENCE` gain the trailing boundary `(?![A-Za-z0-9_])`, so `$gate_3_decide` and `$gate_3_after` never decode as `gate_3`) | unit | BC-15 | H×M | owner-approved pinned edit |
| 27 | `not_run_body_emits_no_operation_output_but_topology_lists_it` | integration | BC-16 | H×M | topology kind `gate`; drop unmatched gated bindings |
| 28 | `body_prompts_hold_no_accounting_envelope` | unit | BC-14 | H×M | projection like corrective coach |
| 29 | `decision_record_holds_no_prompt_or_answer_text` (property: random answers never appear in the record bytes) | unit | GD-I5 | H×M | record builder takes no text args |
| 30 | `pending_combine_record_is_not_a_provider_call` | unit | BC-29 | H×M | `OperationCall.pending`; skip in the accounting index and the fold |
| 31 | `decide_reads_a_pending_gate_record_from_the_recorded_calls` | unit | BC-35 | H×M | `OperationCall.gate_record` by fingerprint (D11) |
| 32 | `decide_context_stays_under_the_cap_with_8_mib_ancestor_answers` | unit | BC-34 | H×M | DECIDE holds `"after": ""`; AFTER never parses its context |
| 33 | `keywords_source_runs_once_per_tree_and_returns_the_input_summary` (also in a tree with only a LabelModel) | integration | BC-30 | M×M | one KEYWORDS source (D6) |
| 34 | `not_run_entry_counts_min_and_max_model_calls` | unit | BC-17 | M×M | topology walk per path |
| 35 | `gate_depth_nine_is_refused_at_compile` | unit | BC-18 | M×L | renderer depth counter |
| 36 | `empty_case_input_takes_the_default_branch` | integration | BC-21 | M×L | — |
| 37 | `decide_refuses_a_context_over_1_mib` | unit | BC-22 | M×L | size check before parse |
| 38 | `cancelled_case_reports_no_taken_branch` | integration | BC-19 | M×L | — |
| 39 | `combine_package_never_imports_world` (import `E/combine/*` with `screamingface_engine.world` blocked) | unit | contracts C12 | M×L | arch test beside the layering check |
| 40 | `two_sibling_gates_decide_independently` | integration | BC-20 | L×M | — |
