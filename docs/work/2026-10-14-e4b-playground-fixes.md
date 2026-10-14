---
ticket: OME-1601
stack: screamingface, screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-14
finished:
---

# e4b-playground-fixes — fixes found live on the PR #1409 playground

## Fix: the stage after an empty Rank/Filter cut still gets the Case input

### Intent

Found live on PR #1409: in `sf.Pipeline([sf.Fusion(json_members, synthesizer=sf.Rank(k=2,
by_field="confidence")), writer])`, when fewer than k members have a confidence, the Rank step
abstains with `cut_not_met` and the writer gets an empty text. The writer then replied that there
was no question. A Filter that keeps no member (`no_votes`) does the same (the deviation in
`docs/work/2026-10-13-e4b-recipes.md`). By ans:Q7 the stage after a Rank or a Filter always gets
the input; by ans:Q4 an empty Filter abstains. The fix keeps both: the abstain stays in the step
evidence (same status and reason), and the step output is the empty envelope
`{"input":"<input>","selected":[]}`, the same canonical JSON as unit 1 (selection-input). When the
selection is the last step of a hand-written url4, the Case abstains with the empty answer, as
before. Stacks: screamingface-engine (source and tests), screamingface (README, CHANGELOG, one
docstring), and the E4b spec docs.

### Planned changes

- `apps/screamingface-engine/src/screamingface_engine/combine/ports.py`: `OperatorDescriptor.envelope`
  (select only, not in the catalog); `selection_envelope(chosen, combine_input)` (moved from
  `selection.py` `_selection_text`).
- `.../combine/operators/selection.py`: `top_k@1` and `kept@1` set `envelope=True` and call
  `selection_envelope`.
- `.../combine/endpoint.py`: `_Plan.envelope`; `_abstain` writes the empty envelope for such a
  select step, inside the 8 MiB result cap.
- `.../benchmarks/invocation.py`: an abstained last step gives the empty Candidate answer.
- `.../world/combine.py`: docstring only.
- New engine test `tests/unit/test_combine_empty_cut_envelope.py` (ECE#1–8).
- PR-added tests (not pinned) that expect the empty envelope now: `test_combine_recipes.py`
  (RC#4), `test_combine_selection_input.py` (SI#13, renamed), `test_combine_filter_judge.py`
  (FJ#7).
- `packages/screamingface/README.md`, `packages/screamingface/CHANGELOG.md`,
  `packages/screamingface/src/screamingface/selection.py` (docstring only); the spec docs
  `00-overview.md`, `contracts.md`, `erd.md`, `test-plan.md`, `prd/selection-input.md`,
  `prd/recipes.md`, `prd/filter-judge.md`; one pointer line in `docs/work/2026-10-13-e4b-recipes.md`.

### Test plan

- CHAR (pass before and after): ECE#3 an abstain of another select step keeps the empty text;
  every url4, flow and golden fixture stays the same.
- RED then GREEN: ECE#1 a Filter with no pass; ECE#2 no member can be read (Filter, Rank); ECE#4
  unicode, quotes and newlines round-trip; ECE#5 the 8 MiB cap (an input of 8388582 characters
  passes, 8388583 fails with `combine_input_too_large`); ECE#6 only `top_k@1` and `kept@1` set
  `envelope`, and only a select operator can set it; ECE#7 recipe S7 with a Rank cut, the writer
  gets the input; ECE#8 a Filter that is the last step still abstains the Case; SI#13, FJ#7 and
  RC#4 expect the empty envelope.
- Invariant protected: the abstain status, reason, `chosen` and `built` do not change; no url4
  byte, schema, fixture, catalog entry or failure code changes.

### Acceptance

- The writer after an abstained Rank or Filter gets `{"input":"<input>","selected":[]}`.
- A hand-written url4 that ends with an abstained Rank or Filter gives a completed, empty,
  abstained Case.
- The three gates (screamingface-engine, screamingface, repo) are green against `origin/main`.
  No pinned file changes.

### Outcome (fill at the end — required before COMMIT)

- **Actual files:** (commit B)
- **Commits:** (commit B)
- **Gates:** (commit B)
- **Deviations:** (commit B)
