---
ticket: unfiled
stack: screamingface
status: planned
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
