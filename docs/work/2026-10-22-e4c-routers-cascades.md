---
ticket: unfiled
stack: screamingface
status: done
started: 2026-10-22
finished: 2026-10-26
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

## Outcome

- **Actual files:** as planned in `docs/plan/2026-10-22-e4c-routers-cascades.md` §2 (units
  1–15), plus this ledger. Spec and plan in `docs/spec/2026-10-22-e4c-routers-cascades/`.
- **Commits:** `49fe62852` docs(e4c) spec and plan; `65651753a` feat(e4c) units 1–15;
  `5f974eab1` refactor(e4c) simplify; `a7faca9e2` fix(e4c) Gate replay, Keywords `$` escape and
  the budget-refusal row; then this ledger close.
- **Gates:** `run_gates.py screamingface --base HEAD` ALL GREEN after each pass (ruff, pyright,
  pytest with 95% coverage, notebooks, build, distribution). Engine: `run_gates.py
  screamingface-engine` green after the build and the simplify pass (after `uv sync --dev`); the
  bug-fix pass changed no Engine file, and the Engine's E4c tests pass on it (1328 passed).
- **Deviations:** (1)–(16) in the Log. Design-review findings 12 (panel scan), 14 (public names
  `sf.Budget` vs `sf.budget.Budget`, an owner question) and 16 were not changed.
- **Follow-ups (not filed):** the Engine could record the refused body's first operation in
  `gate-decision.v1`, so the refusal row does not read it from the graph shape (it relies on the
  Gate's then-before-otherwise dependency order); a failed Case keeps no operations (deviation 4,
  a Candidate invocation contract change).
- **Open before the PRs:** the PIN test-change manifest
  (`.claude/test-change-approvals/OME-1291.json`), the three-PR split, and the Linear leaves
  under OME-1291 (filed at PR open).
