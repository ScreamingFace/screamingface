---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-13
finished:
---

# e4b-selection-input — the stage after a Rank or Filter sees the Fusion input (E4b unit 1)

## Intent

A benchmark author wants the writer model after a Rank or a Filter to see the Case question, so
that one recipe answers a different question in each Case (scenarios S7, S9, S10). Today the writer
gets only `{"selected":[...]}`. By ans:Q7 ("Always, automatically"), ans:Q13 (Rank and Filter only)
and P4 (option C, in place under ans:Q5), the engine adds the combine context `input` to the
`top_k@1` and `kept@1` output: `{"input":"...","selected":[...]}`. The SDK compile and every
compiled url4 stay the same. Spec: `docs/spec/2026-10-13-e4b-combine-extensions/prd/selection-input.md`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/combine/ports.py` — `CombineInput.input: str | None = None`.
- `apps/screamingface-engine/src/screamingface_engine/combine/endpoint.py` — `_read_members` sets `input=context.input`.
- `apps/screamingface-engine/src/screamingface_engine/combine/operators/selection.py` — `_selection_text` adds `input` when it is set; docstrings.
- New engine tests: `tests/unit/test_combine_selection_input.py`, `tests/unit/test_combine_selection_input_world.py`, `tests/unit/test_e4b_catalog_pins.py`.
- New SDK tests: `tests/test_selection_input_bytes.py`, `tests/test_e4b_schema_pins.py`.
- Pinned test edits (owner approval pending): `tests/unit/test_combine_rank_world.py`, `tests/unit/test_sdk_candidate_contracts.py`, `tests/unit/test_combine_selection.py:26,74`.
- `packages/screamingface/README.md` (:276-277, :592-595, :621, :657-659), `packages/screamingface/CHANGELOG.md` (:53, :57).

## Test plan

- CHAR (pass before and after): SI#1 concat unchanged, SI#2 selection url4 bytes unchanged, SI#13 cut_not_met abstains, CS#8 no new failure code, CS#10 report.v1 and report-trace.v1 unchanged.
- RED then GREEN: SI#3 top_k envelope, SI#4 kept envelope, SI#5 CombineInput.input verbatim (CI-I1), SI#6 unicode/quotes/newlines round trip, SI#7 rank world writer message, SI#8 filter pipeline writer message, SI#9 later-stage Fusion input, SI#10 conversation input as JSON text, SI#11 8 MiB cap boundary (8388554 passes, 8388555 fails with combine_input_too_large), SI#12 a Fusion stage after the selection.
- Invariant protected: the input is copied verbatim and never cut; no url4 byte, schema id or failure code changes.

## Acceptance

- The writer after a Rank or a Filter gets `{"input":<Fusion input>,"selected":[...]}`; Concat output is unchanged.
- `screamingface` and `repo` gates green; `screamingface-engine` green with `--skip-append-only`, and its append-only check lists only the three approved pinned files until the owner approval manifest exists.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message> (A, B, C)
- **Gates:** <run_gates.py result line / counts, per stack, with and without append-only>
- **Deviations:** <anything that differed from the plan, or "none">
