---
ticket: OME-1864 (engine), OME-1865 (SDK), OME-1866 (aigateway); epic OME-1291
stack: screamingface
status: in_progress
started: 2026-10-22
finished:
---

# e4c-routers-cascades — choose whether a model runs (OME-1291)

## Intent

Epic OME-1291: a model in the recipe might not be called. `sf.Gate` becomes the one branch
construct (nested binary Gates for N-way), with real skipping through gated url4 iterates, the lazy
E4b fallback, `sf.Cascade`, Keywords and LabelModel selectors, skip-Gate members, guards with
`fail_closed`, and a per-Case budget on the candidate. Interview 2026-10-22, Q1–Q26.

## Planned changes

- See the plan: `docs/plan/2026-10-22-e4c-routers-cascades.md` §2 (units 0–15, three PRs).

## Test plan

- See `docs/spec/2026-10-22-e4c-routers-cascades/test-plan.md` (272 scenarios, 294 TDD rows).

## Acceptance

- An unselected branch makes zero model calls in every flow (call counts per binding on the fake
  gateway); replay takes the same branches; E4b recipes without a lazy fallback keep their bytes;
  `fail_closed` and abstain stay apart; the report shows every decision; all gates green against
  `e4b-integrated`.

## Log

- 2026-10-22: spec written (prompt-planner): ERD, 10 PRDs, contracts C1–C12, test plan, overview
  with owner-review list P1–P14. Waiting for owner review. Not committed before the review.
- 2026-10-22: Opus review round 1 → ESCALATE (blocker: operations inside gated bodies were never
  attributed; 10 major). Owner answered Q20–Q23. Fix round applied: branch-core D1–D9 (inline
  bodies, plain-text JOIN, recursive attribution + `record_gate_call`, null-branch rule, body
  reference invariant, Keywords once per tree, fingerprint ancestors, skip-member DECIDE outside the
  slot, calls-avoided range); selectors in PR-1; `fail_closed` vocabulary in PR-1; plan rows by TDD
  number, each in one unit; P15–P21; line-number and tag fixes. Waiting for review round 2.
- 2026-10-22: Opus review round 2 → ESCALATE (blockers: DECIDE had no url4 edge to the data it
  reads; a failed cascade stage could not escalate under `quorum="all"`; 5 major). Owner answered
  Q24–Q26. Fix round applied: AFTER source (D10), `gate=` param and `OperationCall.gate_record`
  instead of request scope (D11), JOIN copies the panel result and the panel branch table with
  Q25 (D4, D12), restated body-reference rule (D5), KEYWORDS source with the input summary in every
  selector tree (D6), attribution limited to Gate blocks, cascade stage panels at url4 `quorum=0`
  (Q24), skip slots required under `quorum="all"` (no internal failure code, no
  `OperationCall.failure_code`), Gate/CorrectiveLoop refusal (Q26), Engine-only
  `binding_names.json`, min–max counts, failed-selector report line; plan rows re-assigned (CHAR
  first, no PR-1 row needs the budget); P22–P26. Waiting for a targeted re-review and owner review.
- 2026-10-22: review round 3 (targeted Opus, ESCALATE: 1 blocker, 4 major, 6 minor) fixed.
  F1 GATE_SPEC `terminal` + JOIN copies the taken branch's terminal result (branch-core D12,
  BC-36/BC-37, rows #6a/#6b; erd §1/§6; contracts C4; cascade CA-9/CA-20/#10; lazy-fallback
  delta 4, LF-14, #11). F2/F3 model signal calls and `sf.Consistency` refused with skip-Gate
  members (SM-15/SM-16, rows #5a/#5b). F4 `quorum_not_met` declared in PR-2 (SM-11, rows #2a/#2b;
  guards #4; contracts C10; test-plan §5). F5 AFTER instrumental slots, transitive ancestors,
  in-scope assertion (D10, BC-38, row #17a, BC#10 quorum case; contracts C1/C2b). F6 via F1. F7
  gated last stage with no voters follows its word (D4 rows, CA-30, row CA#11a). F8 skip-Gate
  forces the panel path (skip-members compiled shape, contracts C1). F9 erd §3 JOIN record wins
  for an unselected member. F10 trailing boundary on the widened reference patterns (BC-15, BC#26).
  F11 BC#17 → unit 4, BC#9 budget case → budget #5, RP#11 budget case → RP#11a (unit 14).
  Overview P22 rewritten, P27–P32 added. Totals 272 scenarios, 294 TDD rows; a script confirmed
  every PRD row is in exactly one plan unit.
  Review 2 trace (where each landed): F7 Engine-only `binding_names.json` — branch-core BC-15 and
  #26, test-plan §5, contracts C5; F8 min–max `model_calls` — erd §3 NOT_RUN_ENTRY, branch-core D9,
  lazy-fallback and guards not-run lines, report RP-6/RP-15; F9 guards #10 GREEN note — the tree's
  KEYWORDS source (branch-core D6); F14 SagaLLM note — guards §5 follows P1/BC-5.
- 2026-10-22: owner approved P1–P32 as written and the §7 budget default; scope = all three PRs
  (units 1–15). Build started.
- 2026-10-22: units 1-5 built (uncommitted). Engine: `combine/decision.py` (`gate-decision.v1`),
  `world/branch.py` (AFTER/DECIDE/OPEN/JOIN/KEYWORDS), attribution walk through Gate blocks,
  `fail_closed` code + helper, `OperationCall.decision/pending/gate_record`, `record_gate_call`.
  SDK: `_surface/selectors.py`, `branch.py` (`BranchNode`), `_evaluation/branch.py` (renderer),
  topology kind `gate`, candidate kind `gate`. Fixtures `ET/data/gate_contract/*.url4` (SDK
  compile, drift guard `ST/test_e4c_gate_fixtures.py`); Engine-world runs `ET/test_e4c_gate_runs.py`.
  Deviations from the contracts, by url4 facts found in the build:
  (1) url4 structs have no null, so DECIDE/JOIN contexts leave out an absent key, and the decision
  call's binding moves into GATE_SPEC `panel: {"binding"}`; GATE_SPEC also gains `calls` (the
  NOT_RUN `model_calls` per branch), `selectors` (kind, labels, multi, LabelModel binding) and
  `reads` (the selectors read inside each body), which DECIDE needs to write the record.
  (2) An iterate result reaches JOIN as a JSON array text (`[]` or `["<text>"]`), not joined text.
  (3) JOIN and DECIDE find a recorded call by its `binding=<name>` param, not by a full fingerprint.
  (4) A failed Case keeps no operations (a raised Candidate failure is a url4 collected error), so
  BC-10 / GU-20 / RP-8 records exist only on a refusal; a `fail_closed` Case shows the RP-18 line.
  Changing that is a Candidate invocation contract change (all benchmarks): proposed follow-up.
  (5) BC-16: an operation inside a branch that did not run is absent (attribution drops a gated
  binding with no recorded call).
- 2026-10-22: units 6-11 and 13 built (uncommitted); forks wrote most test files and units 9, 12,
  14, 15. More deviations found in the build:
  (6) The gate spec is the INTENT of DECIDE and JOIN (as a combine spec is a combine call's
  intent), so the url4 decode reads it from the JOIN call; GATE_SPEC repeats each Keywords
  selector's `rules` so the decode can rebuild the selector.
  (7) A `gate_N_block` reference reads the JOIN `gate_N` in the url4 call decode and the topology
  walker (a later stage, a Fanout member).
  (8) Skip members: the combine call reads `selection` (member -> DECIDE record) and, under a
  numeric quorum, `floor` (a second context key, not in C11). A writer block gets an implicit
  labelled `sf.Concat()` (joined text of the selected members), not the SM-4 selection envelope.
  (9) The Budget sits on a marker source `_sf_budget:0.0:usd=..:tokens=..:'budget';budget_mode=
  advisory`, not on the candidate's result source: url4 cannot render `;budget_mode` on an
  expression-valued source (it would re-scope to the expression).
  (10) LF-16: call #2 of a lazy fallback reuses call #1's signal calls (a scores judge runs once).
  (11) `sf.answered()` is a panel condition (no number); its decision call has no combine gate.
  (12) RP-17 card keeps the E4b " · N abstained" text and adds " · fail_closed N".
- 2026-10-22: units 12, 14, 15 done (forks). The budget tests found 4 bugs in main-loop code, all
  fixed: a refused judge fallback now answers with the majority (BU-18); `candidate_budgets` walks
  every iterate body (BU-15); `Estimate` is in the Gate `Branch` type; `to_python()` keeps the
  `Estimate` of a judge fallback. Opus design review: ACCEPT-WITH-FIXES. Fixed: AFTER also
  references every ancestor source under a Budget (finding 1); a refusal falls back only to a step
  slot (finding 2); C9 `decision_cases.json` + tests on both sides (finding 3); JOIN validates its
  record (finding 5); one provider-call index (finding 6); the fold reuses the E4a ledger rule
  (finding 7); the selection parse uses `GateDecision` (finding 8); one recorder loop (finding 9);
  the DECIDE budget log line and the once-per-Case unpriced warning (finding 10); one `_deep`
  body rule (finding 13); two `_sf_budget` sources are refused (finding 15); a pending decision
  call is its own type `PendingCombine` from `run_combine_call`, and `CombineOutcome.evidence` is
  required again (finding 11). Not changed: 12 (panel scan), 14 (public names), 16 (the helper
  keeps `build_world` short).
  More deviations:
  (13) BU-18: a pending decision call keeps its majority answer in-process
  (`OperationCall.kept_output`, never on the wire). When the Budget refuses the fallback, JOIN
  returns that text, answered. `op_synthesis_N` keeps output `""` and no evidence (LF-13), so the
  report shows the answer on `op_gate_N` with no vote evidence. A majority answer over 8 MiB is
  not kept, and the Gate abstains `budget_refused`.
  (14) D10: under a Budget, AFTER also references every named source in scope that holds a model
  call (the ancestors), so the spend DECIDE folds is the same on every run and replay (BU-8). With
  no Budget, AFTER is as D10 says.
  (15) GD-I2 allows `fail_closed` beside `wanted` null for the D4 null + `fail_closed` row (CA-30),
  on both sides. GD-I3 cannot hold there (no branch ran).
  (16) P11 / BU-4 / BU-5: a refused branch falls back only to a step slot that makes no call. A
  word (`abstain`, `fail_closed`, skip) is no current answer, so the Gate abstains
  `budget_refused` (BU-5 input gate, BU-10).
  Environment note: `tests/unit/inspect` fails 2 metric-identity tests on the base commit too
  (pre-existing, not E4c). Run lane 1 after `uv sync --dev`, as CI does.
- 2026-10-26: /simplify pass (no behavior change, no test edits): caches on the url4 parse, the
  gate spec and the decision record; one gate-name vocabulary (`_operation_bindings.GATE_BLOCK`,
  `gate_join`); the decision decoder reuses the `combine_evidence` helpers; `_DelegatingReducer`.
- 2026-10-26: bug-fix pass (4 suspected bugs from the simplify pass, then an Opus design review,
  ACCEPT-WITH-FIXES, all required fixes applied):
  (a) Replay: a Gate's JOIN has no parsed dependencies, so a replayed `sf.Gate >> sf.Model` lost
  the Gate's branch models. The JOIN now gets edges to every call in its block. Also fixed: Gate
  members and Gate-terminated bodies named `op_gate_N_block` (5 fixtures failed to replay); a
  non-skip Fanout replayed its selectors first; a classifier Gate and a nested Gate replayed a
  different model order. The compiler now lists selectors only at the tree root, as the topology
  does. Every Gate fixture replays to the compiled Candidate.
  (b) A `$` in a Keywords pattern was rewritten by url4 interpolation (`\$input` reached the
  Engine as `\CASE INPUT`). The KEYWORDS intent and the gate spec use `canonical_json` (D-1).
  (c) The budget-refusal row took a panel Gate's decision call for a branch result and named the
  wrong operation; `prep >> Gate` named the prep model (pre-existing).
  (d) A lone surrogate in the JOIN context: not a bug. Every caller sends ASCII-escaped JSON.
- 2026-10-26: code-review pass (`/code-review` high over `origin/main...HEAD`; 4 findings
  reproduced). Tests: `tests/test_e4c_skip_member_review.py` (SDK) and
  `tests/unit/test_e4c_keywords_compile_once.py` (Engine).
  (e) A panel Gate's second reducer step over a skip-member Fanout had no `selection` or
  `floor`: an unselected member counted as a failed member, and `quorum="all"` did not compile.
  The step now reads the panel and the same selection and floor as the decision call (SM-11).
  (f) `_skip_member` dropped the member's `sf.Estimate`, so a Budget could not refuse a selected
  member before spend (SM-17, BU-14).
  (g) A skip member with a `sf.budget.remaining()` condition raised a bare AssertionError. The
  Fanout now refuses it with a message: a skip-Gate member reads `sf.label` or `sf.labels` (SM-8).
  (h) Every skip member listed every member's LabelModel models and selector topology. A
  tree-root Gate now lists only the LabelModels it reads that no earlier root listed.
  (i) A branch word spelled another way (`"fail-closed"`, `"ABSTAIN"`) became a model route; it
  is now refused with the GT-12 message, so a guard never becomes a model call.
  (j) KEYWORDS compiled each RE2 pattern twice per rule per Case and cleaned the input head per
  rule; the rules now compile once per intent (cached) and the head is cleaned once per request.
  (k) Skipped combine members are built as `not_selected` rows when the evidence is built, not
  patched into a dumped and re-validated evidence (no wire change).
  Five gate_contract fixtures changed by (f) and (h); owner manifest `OME-1291.json`.
- 2026-10-26: the three open design-review findings (no behavior change, no test edits):
  12 fixed: the compile step that makes a member panel returns its reference on
  `_ResolvedRecipe.panel`, and a panel Gate's second reducer step reads it from the decision. The
  Gate does not scan `panel_N` names. 14 fixed in part: the `_BudgetRefs` singleton is replaced by a
  plain `remaining()` function that returns `Remaining`, not `Any`; `sf.budget.remaining()` does
  not change. The names `sf.Budget` (the recipe wrapper) and `sf.budget.Budget` (the E4a record)
  stay; this is an owner question. 16 closed: `_install_engine_runtimes` stays, because
  `build_world` with the four calls inline has 27 statements and ruff PLR0915 allows 26.
- 2026-10-26: finding 14 (names) closed. The owner chose to rename the recipe wrapper:
  `sf.Budget` is now `sf.Budgeted`. The E4a record `sf.budget.Budget`, `sf.budget.remaining()`,
  `sf.Estimate` and every wire and schema name do not change. E4c is not released, so there is
  no alias. The spec, the plan, the README, example 19, the CHANGELOG and the tests use the new
  name. The public surface snapshot changes, and the PIN manifest approves it again. The Log
  entries above keep the old name, because they record what happened.
- 2026-10-26: LF-22 with a judge or writer fallback (owner decision: remove the refusal). The SDK
  refused a Gate with two reducer steps over a Fanout with `sf.Consistency`. The refusal is
  removed: the decision call compiles the sample calls once, before the block, and the gated
  call #2 reads the same sample panels (`_CandidateCompiler._reused_samples`, like the LF-16
  signal reuse). The members make 1 + 5 calls on every Case and the fallback never samples again.
  New fixtures `consistency_judge.url4`, `consistency_writer.url4`; the strict xfail is now a
  test. The recipe topology of call #2 lists the reused sample nodes again, as it does for a
  reused signal.
- 2026-10-27: simplify pass 2 (no behavior change, except one bug fix: `code()` dropped
  `sf.Estimate` around a nested Gate when the output wrapped).
- 2026-10-27: Q21 superseded by Q21b (owner chose option B, "one price for both"). The
  differing-view flag was never wired: a replay through `score_id` gets no per-Case records. The
  real cause of Q21 was in the gateway: a frozen-copy replay rendered a cache hit with no
  `cache.reference`, so the Engine priced every replayed call as unknown ($0), and a budget Gate
  could take another branch. Now the replay carries the captured call's price as
  `cache.reference` (`cache_reference_from_captured_aigw`): the last succeeded attempt of a
  complete capture, or the captured hit's own reference. A stored cache entry with a `partial`
  status now withholds its tokens as well as its cost, as the live path does. The SDK flag
  (`budget_view_differences`, the `differs` parameter, the summary count) and its 3 tests are
  removed; BU-27 is rewritten and RP-35 removed. Side effect: a frozen-copy replay now reports the
  captured call's price as the cache saving, like any cache hit (OME-1687: reproduction cost is
  spend plus saving). The pinned gateway test `test_cache_entry_metadata_none_space` changes one
  expectation (PIN manifest).
- 2026-11-10: Q32 (owner): the overspend line on a replay uses the cost of the original run. It
  added `usage.cost_usd`, which is $0 on a cache hit, while the Budget charged the
  `cache.reference` cost. The Engine now writes `charges` (one `{usd, tokens}` per provider call,
  the `budget.charge` numbers) on each operation of a candidate with a Budget, and
  `overspend_of` adds them. The owner first chose a Case-level total, then chose the
  per-operation field once the cost was clear: the total had to cross about 8 grading-pipeline
  sites, while `operations` already reaches the SDK on every path. An operation that two
  bindings share keeps no charges (the `accounting` rule), as before. Tests: Engine
  `test_e4c_operation_charges.py`, SDK `test_e4c_overspend_replay.py`; the RP-34 test helper
  `_priced` now carries a charge. End to end (flow 16 world): live and replay both charge $0.003.

- **2026-11-12 Product review: lower cognitive load (Irina's "E4c Proposed API Flows" page).**
  The page rewrites the 17 flows in a proposed API. The sf.Router items (flows 4, 5, 8, 8b,
  15 as a Router, 17a-c, 18; `sf.ScoringClassifier`, `keep=`, `describe=`, Router `default=`)
  are out of scope here: Dmitry owns sf.Router (PR #35, E13). The owner chose, for this PR:
  (a) `sf.Cascade` takes the line form only: `sf.Cascade(t1, sf.escalate_if(c), t2, ...)`, with
  `sf.abstain()` or `sf.fail()` as an optional last part; the list form, `escalate_if=` and
  `otherwise=` are gone (unreleased). (b) Nothing escalates unless a line says so. This
  reverses ans:Q17 and ans:Q24: a failed tier fails the Case (its Fanout quorum decides); a
  tier that abstains makes the Case abstain; `sf.escalate_if(sf.unanswered())` is the old
  first success. The rule lives in every Gate with a recipe `otherwise=` (a Cascade is still
  byte-equal to its Gates): DECIDE escalates on no voters only for an `answered` gate, and a
  missing number fails the Case with the new code `signal_missing`. "Failed or low score" has
  no spelling yet (open). (c) Renames, no aliases: `sf.Budgeted(usd=, tokens=)` ->
  `sf.WithBudget(max_usd=, max_tokens=)` (`sf.Estimate` keeps `usd=`), `sf.Keywords` ->
  `sf.RegexClassifier`, `sf.LabelModel` -> `sf.LLMClassifier` (this reverses the "LLM label"
  wording of b468c5d9c). (d) `sf.abstain()` and `sf.fail()` are the typed outcomes; the SDK
  stores the words, so the compiled bytes do not change; the string `"fail_closed"` is refused
  and `"abstain"` (E4b, released) still works. (e) `sf.signal("x") < 0.7` in a condition reads
  the chosen member, as `.chosen()`. `max_tokens=` is my choice, for symmetry with the USD cap (later renamed `budget_usd=`).
  Done the same day: SDK `_surface/cascade.py` (rewritten), `outcomes.py` (new), `gate.py`,
  `refs.py`, `budget.py`, renders, exports; Engine `world/branch.py` (D4 null rule, D4a
  `signal_missing` before the ledger read) and the `signal_missing` code (68 -> 69). Tests:
  the cascade, gate, budget, docs and run tests moved to the new API; new url4 fixtures
  `cascade_signal` and `signal_fail`; 9 cascade/docs fixtures regenerated (`first_success`
  bytes unchanged). The PIN manifest gains 5 approved blobs (surface snapshot, gate surface,
  three failure-code pins). Agents updated the spec PRDs and README/CHANGELOG/notebook 20.
  Design review: ACCEPT-WITH-FIXES, no structural findings; fixed 1-3, 5-8. Kept: (4) the
  typed `_ORDERED` map; (9) Engine comments keep the wire names; (10) a failed LLM label still
  takes the recipe default (routing, selectors PRD); (11) `otherwise=sf.abstain()` and an
  omitted `otherwise=` are not `==` (same bytes; predates this change). Also: `sf.Cascade`
  refuses any outcome word string (`"abstain"`, `"fail-closed"`, ...) in any tier. A
  `signal_missing` Case has no gate record (DECIDE raises before it writes one).
  Later the same day (owner, on Irina's open note for flow 15): `sf.WithBudget(max_usd=)` is
  renamed `budget_usd=`, because the cap is checked before each optional call only and the calls
  that always run can pass it (Q20); "max" read as a hard maximum. `max_tokens=` keeps its name
  (owner choice). The url4 keeps `usd=`, so no fixture bytes change. README gains one bullet:
  the cap is a budget, not a hard maximum. The PIN manifest's surface-snapshot blob is updated.
  Kind run (sf-prod, this branch's images, 3 GSM8K Cases per flow, about $0.03 in all): 32
  flows ran. It found one bug: `recipes_need_operators()` did not look inside `sf.WithBudget`,
  so `sf.evaluate` did not load the Engine operator catalog for a budgeted recipe with a
  reducer (README d9, flows 11, 15, 16 failed before any call). The offline tests pass the
  catalog by hand, so they missed it. Fixed in `_children`; new test in `test_e4c_budget.py`.
- 2026-11-12 review round (PR #1733: sergio-bershadsky and HupBaHa, both CHANGES_REQUESTED).
  Checked offline (no model calls, no hosted calls). Fixed, each with a RED test first:
  (H1) DECIDE read a condition selector with no record (`not_run`) as false and took the paid
  `otherwise`; now a `benchmark_contract_error`. A failed-call record still takes `otherwise`
  (SL-12). (H5) JOIN read a taken branch with no iterate slot as an empty answer; now a
  contract error, except the step branch that IS the decision reducer (it has no slot,
  branch-core D4). (S3) the SDK overspend line summed floats; it now uses the Engine fold
  (`Decimal(repr(x))`, `_DECIMAL`), so 0.1 + 0.2 under 0.3 is not an overspend. (M1) the SDK
  `gate-decision.v1` decoder refuses NaN and infinity. (M2) an `sf.LLMClassifier` prompt that
  holds the template's `Task:` line replays to itself (strip the known header, not
  `rpartition`). (H2, OME-1866) the frozen-copy reference kept a captured call only if every
  dimension was valid; now each of usage, cost, latency and response model falls back alone,
  as the Engine's live read does. (S4) new twin fixture
  `apps/aigateway/tests/fixtures/replay_reference_twins/twins.json`: the gateway renders it
  with its real replay function and guards it; the Engine reads it by path and checks live ==
  replay for 13 cases; the Engine CI paths include it. Residual: some malformed capture blocks
  still read differently live and on replay (corrected 2026-11-13, see the round 3 entry).
  (N2) the PIN manifest drops 5 entries for `gate_contract/*.url4` files that are new in this
  PR. (N3) the replay-reference test has no grouping classes. Not changed, owner decision:
  (S1) release order. The PR says SDK first; a new SDK on an old Engine pays the members and
  then fails each Case on `phase=decide`, and an old SDK on a new Engine is safe. No E4c
  capability signal exists for an SDK check before spend. (S2) the reply to Kevin on
  `sf.Router` (out of scope here; Dmitry's PR). (H3) charges of a duplicate fingerprint are
  dropped by spec (erd one-claimant rule); the SDK always adds a unique `binding=`, so none of
  the 32 compiled notebook flows has a duplicate. (H4) a failed or `fail_closed` Case keeps no
  decision, operations or charges (deviation 4, the follow-up below). Deviation (17): the plan
  said three stacked PRs (ans:Q11); the work went as one PR (#1733) with three Linear leaves
  (OME-1864/1865/1866), because each later unit changed files of the earlier ones and the
  rebases on main went faster as one branch. The reviewers named the size.
- 2026-11-12 review round 2 (owner decisions). (A) A bare `sf.signal("x") <cmp> v` in
  `sf.Gate(when=...)` or `sf.escalate_if(...)` is refused with `TypeError`, which names
  `.chosen()` and `.mean()`; this reverses decision (e) of the same day. WHY: the bare comparison is
  the per-member test of `sf.Filter`, so one expression had two meanings, and `.chosen()` vs
  `.mean()` can take different branches (a reviewer's point on "E4c Proposed API Flows").
  `refs.signal_condition` became `refs.refuse_bare_signal`; new test
  `test_e4c_bare_signal_refused.py`; spec CA-32 rewritten; README, CHANGELOG (the bare-signal
  feature bullet removed: never released), notebook 20 and the tests new in this PR write
  `.chosen()`. One pinned edit: the `sf.Gate when=` message in `test_gate_surface.py` now shows
  `sf.signal('x').chosen() < 0.7`. (S1) Release order: the Engine ships first. Checked in the
  code: the Engine writes `charges` only when the Candidate has a Budget
  (`operation_outputs.py`, `charged=bool(budgets)`), and the Gate, budget and new failure
  words only for E4c recipes, which an older SDK cannot build; so an older SDK is safe on the
  new Engine and the OME-1233 decoder rule holds. Spec §8, guards, docs DC-9 and the CHANGELOG
  follow; the PR body too. (H3) filed `OME-1904`; (H4) filed `OME-1905` (both under OME-1291).
- 2026-11-13 review round 3. Sergey approved at `6e75dccbf`. Fixed: `contracts.md` C8 and C10
  said SDK first; both now say the Engine ships first and point to overview §8. CA-18 quotes the
  `sf.escalate_if` message with `.chosen()`. Corrected the residual note of the replay twin
  fixture (S4): the gateway rebuilds `usage` and `direct_cost` strictly and drops the whole
  dimension on any error, but the Engine's live read takes each number alone. The reviewer found
  10 of 18 single-field corruptions read differently. Three change a budget charge (a bogus
  `usage.status` with valid counts; `direct_cost.source` missing or not a string). The other
  seven change only the token signals. Only a corrupted capture holds such a block. (S2) Kevin's
  `sf.Router` points were settled in a call with the owner (reply posted 2026-11-13); Kevin
  still has to confirm in the PR thread. Filed (owner OK 2026-11-13, under OME-1291): `OME-1921`
  the Engine tells clients it supports E4c; `OME-1922` the SDK refuses an E4c recipe before the
  first paid call (blocked by OME-1921; split per landing); `OME-1923` the gateway reads a
  malformed captured price block with the Engine's per-number rule.

## Outcome

- **Actual files:** as planned in `docs/plan/2026-10-22-e4c-routers-cascades.md` §2 (units
  1–15), plus this ledger. Spec and plan in `docs/spec/2026-10-22-e4c-routers-cascades/`.
- **Commits** (after the rebase on main; the earlier shas do not resolve): `90e5be3bf` docs(e4c)
  spec and plan; `16b757393` feat(e4c) units 1–15; `984c2d48f` refactor(e4c) simplify;
  `213de5170` fix(e4c) Gate replay, Keywords `$` escape and the budget-refusal row; later
  passes to `ff67c89f9` (`git log origin/main..HEAD`); the 2026-11-12 review round: `f762e7f95`, `3f2112b1e`, `020a41229`, `0ceab8afd`,
  `74da905a8`, `9d340d313`, then this ledger.
- **Gates:** `run_gates.py screamingface --base HEAD` ALL GREEN after each pass (ruff, pyright,
  pytest with 95% coverage, notebooks, build, distribution). Engine: `run_gates.py
  screamingface-engine` green after the build and the simplify pass (after `uv sync --dev`); the
  bug-fix pass changed no Engine file, and the Engine's E4c tests pass on it (1328 passed).
- **Deviations:** (1)–(17) in the Log. Design-review findings 12 and 14 (the singleton) are
  fixed and 16 is closed (Log 2026-10-26). Finding 14 (names) is closed: the owner renamed the
  recipe wrapper to `sf.Budgeted`.
- **Follow-ups:** filed `OME-1899` (combine two conditions), `OME-1904` (charges of a duplicate
  call in a budgeted url4, H3), `OME-1905` (a failed Case keeps its decision, operations and
  charges; deviation 4, H4), `OME-1921` + `OME-1922` (Engine capability signal and SDK refusal
  before the first paid call, S1), `OME-1923` (one read rule for a malformed captured price
  block). Not filed: the Engine could record the refused body's first
  operation in `gate-decision.v1`, so the refusal row does not read it from the graph shape.
- **Open:** PR #1733 review: S2 is answered (settled in a call; reply posted 2026-11-13) and
  waits for Kevin's confirmation in the thread; HupBaHa's re-review is pending; S1,
  H3 and H4 are decided (Log 2026-11-12 review round 2). The three-PR split became one PR (deviation 17); the
  Linear leaves are OME-1864/1865/1866.
