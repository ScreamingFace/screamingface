---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-02
---

# e4a-gap-closure unit 4 -- SDK: sf.Reduce, sf.Extract, sf.signal, Answer, trace, abstain

## Intent

Fold the SDK part of the E4a gap-closure into the reducer slot, on top of units 1-3. Add the block
forms (`sf.Extract`, `sf.Reduce`, `sf.signal`, `sf.matches`), the `Answer` view of a Case
(`case.answers()`), the per-Case trace (`case.trace()`, `Report.trace_dict()`), the abstained Case
mark, and the new combine evidence wire. The SDK compiles one reducer plan (`_ReducerPlan`) for
every reducer, so a block and its named form give the same bytes.

## Planned changes (spec section 2)

- 2.0 rebase checks (below).
- 2.1 `_signals.py`: signal keys, `FIELD_PATH`, `Signal`, `signal()`.
- 2.2 `_regex_rule.py`: pre-spend check of a `regex@1` pattern over the stdlib parse tree.
- 2.3 `blocks.py`: `Extract`, `Matches`/`matches`, `Reduce`, the op table.
- 2.4 `reducer.py`: the `_ReducerPlan` seam.
- 2.5 `_evaluation/combine_spec.py`, `url4.py`, test helpers read the plan.
- 2.6 `combine_evidence.py` (+ `_evaluation/`): the Answer-row evidence wire.
- 2.7 `answer.py`, `_case_views.py`, `CaseResult.answers()`, graph binding.
- 2.8 `report_trace.py`, `CaseResult.trace()`, `Report.trace_dict()`.
- 2.9 abstained Case, `abstained_count`, report card text.
- 2.10 exports, snapshot, CHANGELOG, evidence fixture, workflow path filter (F21).

## Test plan

A: this ledger. B: RT#8, RT-D2 (CHAR). C: AR#9, G7 (rows 1-3). D: SG#4, BU#8, guard (rows 4-6).
E: RX#11 (rows 7-9). F: seam refactor (no RED). G: BK#5-7, BK#9-10, BK#13 (rows 10-18).
H: AR#12-14, AR#16 (rows 19-23). I: AB#17 (row 24). J: RT#5-15, RT#17 (rows 25-35).
K: BK#11 (row 36). L: ledger close.

Rows that pass at once by design: B (CHAR), 6 (guard), 9 (guard), F (refactor), K (guard).

## Notes

### 2.0 rebase checks

- `git log --oneline e4a-engine-wiring-evidence..HEAD` shows the six unit 4 commits
  (`f0b8bf5cb` .. `3c2a40943`).
- `git merge-base HEAD e4a-engine-wiring-evidence` = `5e0d9c9b0` = the unit 3 tip.
- `git diff --stat 0d6be5c86 e4a-engine-wiring-evidence -- packages .github apps/screamingface-engine/tests/unit/data`
  lists: `_report_primitives.py`, `tests/unit/test_combine_failure_vocabulary.py` (unit 1),
  `packages/screamingface/pyproject.toml` and `uv.lock` (unit 2 added `google-re2` to the SDK
  `[runtime]` extra). Expected; nothing else.
- Post-rebase suites (no repair commit needed): SDK `2212 passed, 26 skipped, 26 deselected`;
  engine `5235 passed, 67 skipped, 13 deselected`.

### Decisions F1-F21 (from the unit spec)

- F1 no textual conflict; two silent wire breaks (S1 evidence, S2 Case `abstained`) fixed in commits C and I.
- F2 all 11 op-table rows construct; only `plurality`, `weighted` (number list) and `median` compile.
- F3 `judge`/`rubric`/`by`/`fields` are reserved options; giving one raises.
- F4 `mode=None` means the op's first mode; the resolved mode is stored.
- F5 `Reduce.name` = the row's spec reducer.
- F6 recovery: registered named class, else `Reduce._from_spec`.
- F7 `CaseResult._operation_graph` is a write-once private slot bound in place; no case copy.
- F8 closure rule for transitive `member_id`; shared inputs get no label.
- F9 closed trace field sets; `reduce.rule` and `signal.values` refine erd s8.
- F10 SDK-local fixture `tests/data/combine_evidence_cases.json`, generated once from the real engine.
- F11 `abstained_count` is derived and not in `to_dict`; `CaseResult.to_dict` writes `abstained` last, only when true.
- F12 the SDK accepts `score:judge` now; the conformance test compares only the key grammar.
- F13 signal comparison predicates are not in unit 4 (10S).
- F14 RX-2 holds with `whole` + `set`, not `json`; `json` maps to `json_object` (9E).
- F15 RX#11 under RE2: structural check over `re._parser` with a `\p`/`\P` carve-out; RE2 stays authoritative.
- F16 extra refusal of inline/scoped VERBOSE (beyond the coordinator's list).
- F17 the `Answer` field set has no `operation_id`; callers scope with `answers(operation_id=...)`.
- F18 GP-E2 enforced in `sf.Extract` (`benchmark` + `normalize`).
- F19 `Reduce("median")` stores `normalize="numeric"`.
- F20 no `sf.Filter` in unit 4.
- F21 the workflow path filters gain `combine/ports.py`.

### AMENDMENT 2

Every `_Steps(...)` call uses keyword arguments (`_Steps(reduce, select, extract=None, normalize=None)`).

### Errata for the orchestrator

F9, F14, F16, F17 (see above).

## Results

(filled at commit L)
