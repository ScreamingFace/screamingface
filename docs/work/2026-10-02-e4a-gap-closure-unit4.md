---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-02
finished: 2026-10-02
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

### Commits

A ledger; B `test(sdk): pin report.v1 bytes ...`; C `feat(sdk): decode the Answer rows ...`;
D `feat(sdk): add sf.signal ...`; E `feat(sdk): add sf.Extract and sf.matches ...`;
F `refactor(sdk): build every combine spec from one reducer plan`; G `feat(sdk): add sf.Reduce ...`;
H `feat(sdk): join member and computed Answers to a Case`; I `feat(sdk): decode an abstained Case ...`;
J `feat(sdk): derive the per-Case trace ...`; K `test(sdk): pin the public block names`; L this commit.

### Rows with no RED of their own (by design)

- B (RT#8, RT-D2): CHAR. The two `report.v1` goldens (`report_v1_reducer_report.json` from B,
  `report_v1_combine_report.json` from C) are unchanged since the commit that wrote them.
- Row 6 (engine ports conformance): guard, green at once (the SDK grammar copy came first, in C).
  Row 9 (RE2 docstring) is a guard too, but it failed against the stub module docstring and went
  green when `_regex_rule.py` got its real docstring.
- F: the `_ReducerPlan` seam refactor. Guards: `test_reducer_characterization`,
  `test_combine_contract_fixture`, `test_reducer_slot`, `test_reducer_url4_round_trip`, plus the new
  `test_combine_spec_reads_only_the_reducer_plan` (`tests/test_reducer_plan.py`).
- K (row 36): guard.
- RED by an error, not an assertion: row 1 (C, the decoder rejected `member_id` with an
  `ExecutionError`, as the spec says); rows 14, 17, 18 and the compile rows of G (the stub `_plan`
  and `_from_spec` raised `ValueError("stub")`).

### Deviations from the spec (all small and faithful)

- D1 `_signals.py` is split across two commits. Commit C needs `is_signal_key` and the grammar for
  `CombineSignal`, so C creates `_signals.py` and `answer.py` with the vocabulary; D adds `Signal`,
  `signal()` and the reserved-key table (RED: a stub `Signal` that accepts everything).
- D2 `Matches` passes `ignore_case` to the check when it is not `False` (not only when `True`), so
  `sf.matches("a", ignore_case="yes")` is refused like `sf.Extract("regex", ignore_case="yes")`. A
  default `False` still never enters the args.
- D3 The `re._parser` check: `sys.modules` cannot show it, because the stdlib `re` package imports
  `re._parser` itself. `test_the_private_parser_is_imported_lazily` checks instead that
  `_regex_rule.py` has no module-level import of it (and a function-level one).
- D4 `_reducer_class` was deleted from `reducer.py`: `_reducer_from_call` no longer uses it.
- D5 Option value checks raise `TypeError` for a wrong type and `ValueError` for a wrong value (the
  spec did not fix the type per check).
- D6 The extra RT#8 golden (`report_v1_combine_report.json`) was added in C as the second golden.
- D7 `Extract.args` are stored sorted by key (repr and hash use the same order).
- D8 The engine gate needed `uv sync --directory apps/screamingface-engine --extra inspect` (the
  inspect lane of unit 2 imports `inspect_ai`; pyright could not resolve it). Environment only; no
  engine file changed.
- D9 `report_view` had no `_abstained_text` before; the helper sits beside `_card_html`.

### Gates (from the worktree)

- `run_gates.py screamingface --base e4a-engine-wiring-evidence` (once): the only offender is
  `tests/public_surface_snapshot.json` ("existing test artifact is unsupported or unparseable"), as
  planned. `GATE FAILED` is the expected exit.
- `... screamingface --base e4a-engine-wiring-evidence --skip-append-only`: `ALL GATES GREEN`
  (ruff, format, pyright, pytest with `--cov-fail-under=95`, notebooks, build, distribution).
- `... screamingface-engine --base e4a-engine-wiring-evidence --skip-append-only`: `ALL GATES GREEN`.
- `... repo`: `ALL GATES GREEN`.
- SDK coverage 97 % (full suite: 2467 passed, 26 skipped). New modules: `blocks.py` 100 %,
  `_regex_rule.py` 100 %, `report_trace.py` 100 %, `_case_views.py` 99 %.

### Snapshot diff

`git diff e4a-engine-wiring-evidence -- packages/screamingface/tests/public_surface_snapshot.json`
shows only: `sf.Answer`, `sf.Extract`, `sf.Reduce`, `sf.matches`, `sf.signal`; `sf.report.TraceEntry`;
`CaseResult.abstained`/`answers`/`trace` (under both `sf` and `sf.report`); `CandidateResult.abstained_count`;
`Report.trace_dict`; the `CombineEvidence` signature (`result`, `dropped`, `signal`, Answer rows);
and the entries the earlier unit 4 commits already added (`EngineCapabilityError`, the Fusion
`synthesizer` annotation).

### Notes for the evidence caveat (RT#15)

`whole@1` and `last_line@1` extract the member text itself, so their `raw`/`value` in the evidence
and in the trace `extract` entries are member text by design (the I-E1 caveat). The sentinel test
uses `last_number`.

### Errata for the orchestrator

- F9: `reduce.rule` and `signal.values` refine erd s8.
- F14: RX-2 holds with `whole` + `set`, not `json`.
- F16: the VERBOSE-flag refusal is beyond the coordinator's list; it can be dropped.
- F17: the `Answer` field set has no `operation_id`; callers scope with `answers(operation_id=...)`.
- Open for review: `Reduce("pick_field", equals=True) == Reduce("pick_field", equals=1)` (Python
  equality of `True` and `1`); `pick_field` does not compile in this unit, so no bytes depend on it.

## Review round (Opus review: accept after fixes)

The branch was rebased by the orchestrator onto the final unit 3 tip (`1e356cb7d`). One fix round:

- `e798cda39` MAJOR 1: `sf.Extract("field", path=...)` needs text (`TypeError` for `True`, `None`, `3`).
- `dc29603a5` 2: `sf.Reduce` has its own `__eq__`/`__hash__` over a key with each option's type, so
  `equals=True`, `1` and `1.0` stay three blocks; one renderer for `__repr__`/`_python`; `Extract`
  drops the default `ignore_case=False` (as `sf.matches` already did).
- `b0f9a95d0` 3: the url4 recovery (`_from_spec`) checks data with `isinstance` and raises
  `ValueError` ("cannot rebuild"), no `assert`; merged the identical median raises.
- `0681d4738` 4: `CandidateResult.__init__` binds the operation graph as its last step; a Candidate
  that fails validation leaves its Cases unbound.
- `e30a0ecc8` 5: the signal-key conformance test reads the Engine's corpus by AST from
  `apps/screamingface-engine/tests/unit/test_combine_ports.py` (the workflow path filters gain that
  file).
- `ef9818028` 6: `\z` is accepted (rewritten to `\Z` for the Python-side check); `[[:class:]]` and
  `[:class:]` are refused before the compile (no `FutureWarning`); `\Q..\E`, `\C`, `\x{..}` stay
  refused; docstring and CHANGELOG say the check is stricter than RE2 there. The test module runs
  with `error::FutureWarning`. Not covered: other Python-only `FutureWarning` set syntax such as
  `[a&&b]` (same meaning in RE2 and Python today, only the warning differs).
- `236a5cd28` 7: `CombineAnswerRow` refuses a `fail` row with an abstain reason.
- `c8cfbc330` 8: weighted `_from_spec` with 12 members (the `member_10` ordering), exact messages in
  the Reduce and evidence tests, the lazy-import test reads `ast` imports.
- `c4d6fccb6` NITs: `_require_abstained` tests `refusal is not None`; `_cache_label` docstring;
  `sf.__all__` order; the snapshot note above; the needless `type: ignore` is gone (the one on the
  `normalize` argument stays: pyright needs it).

RED seen first: items 1, 2, 3, 4, 6, 7 (item 7 by temporarily restoring the old source). Items 5, 8
and the nits changed tests or wording only and passed at once (item 5 was a rewrite of a vacuous test).
