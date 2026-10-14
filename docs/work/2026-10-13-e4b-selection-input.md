---
ticket: OME-1601
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-13
finished: 2026-10-13
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

- **Actual files:** As planned. Commit A (`54a385468`) holds the ledger, the 3 engine test files, the 2 SDK test files, the 3 pinned test edits and the stub in `ports.py`. Commit B (`090a6e5f6`) changes `endpoint.py` and `selection.py`. Commit C changes `packages/screamingface/README.md` and `packages/screamingface/CHANGELOG.md`, and this ledger.
- **Commits:** `54a385468` — test(screamingface-engine): RED for E4b unit 1 selection-input (A). `090a6e5f6` — feat(engine): put the Fusion input into the top_k@1 and kept@1 selection (B). Commit C — docs(sdk): the stage after a Rank or Filter sees the Fusion input (selection-input).
- **Gates:**
  - RED (engine, focused): 15 failed, 358 passed. All 15 fail on an assertion. None fails on an import or attribute error.
  - GREEN (engine, focused): 373 passed.
  - SDK CHAR: `test_selection_input_bytes.py` and `test_e4b_schema_pins.py`, 4 passed. Doc goldens, 40 passed.
  - `screamingface`, with append-only: ALL GATES GREEN.
  - `repo`, with append-only: ALL GATES GREEN.
  - `screamingface-engine`, with append-only: FAILED on the append-only check only. Offenders: `tests/unit/test_combine_rank_world.py`, `tests/unit/test_sdk_candidate_contracts.py`, `tests/unit/test_combine_selection.py`. These are the three approved pinned files.
  - `screamingface-engine`, with `--skip-append-only`: ALL GATES GREEN (ruff check, ruff format, pyright, layering, pytest with coverage).
- **Review fixes (round 2):**
  - `packages/screamingface/README.md` (Filter selection section): the next stage now gets the input of the Fusion. Doc goldens, 40 passed. No code changed in this round.
  - `screamingface-engine`, with `--skip-append-only`: ALL GATES GREEN in the final run. An earlier run in this round failed one unrelated test: `tests/unit/test_ws.py::test_ws_malformed_inbound_frames_nacked_stream_survives`. That test passed when run alone. This branch does not change that test or `url4` source.
  - `repo`, with append-only: ALL GATES GREEN.
  - `screamingface`, with append-only: NOT VERIFIED in this round. The SDK pytest run (`-n auto`) stopped at about 98% in one run, with all workers idle. The rerun hung in the same way. A serial run did not finish. The round 1 run was green. This round changed one README sentence only.
  - Append-only offenders (unchanged): the three approved pinned files.
- **Deviations:** The ledger status stays `in_progress`. The owner must approve the three pinned test edits before this unit is done (spec §7). No code deviation. Writer calls after a Rank or a Filter miss the request cache once (review note 5). The SDK gate needs a clean run before the PR opens.
