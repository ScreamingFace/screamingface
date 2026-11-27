---
ticket: OME-2054   # Engine; sibling OME-2053 (Client SDK) lands in the same lockstep PR
stack: screamingface-engine, screamingface   # one lockstep reader change on both sides (C10)
status: done
started: 2026-11-27
finished: 2026-11-27
---

# router-no-selection-readers — accept `no_selection` in `answer.v1` readers before any writer (C10, Unit 6)

## Intent

Add the reader side of C10 (`docs/spec/2026-11-16-router-recipe-extension/contracts.md`, C10). A
Router abstention is the answer `{"member_id": null, "value": null, "status": "abstain",
"reason": "no_selection"}`. Both the Engine and the SDK must read it before any writer exists,
as E4c did for `budget_refused`.

This unit therefore adds the word to the `answer.v1` vocabulary on both sides:
- the Engine `AbstainReason`, `AnswerReason` and `ABSTAIN_REASONS`;
- the SDK `AbstainReason` and `AnswerReason`, with their derived sets.

It also regenerates the two pinned schemas with their IDs unchanged. Readers accept the word
only with status `abstain` and refuse it everywhere else.

No existing writer may emit it. The Gate, Band, Pick and budget paths write fixed words, and
the one parametric writer, `NoVotes`, keeps the legacy six. A later Router writer emits it; this
unit adds no writer, no Router runtime, no report and no UI.

## Planned changes

Product:
- `apps/screamingface-engine/src/screamingface_engine/combine/ports.py`:
  - add the word to `AbstainReason`, `AnswerReason` and `ABSTAIN_REASONS`;
  - add a private legacy writer set for `NoVotes`.
- `packages/screamingface/src/screamingface/answer.py`: add the word to `AbstainReason` and
  `AnswerReason`. The derived `ABSTAIN_REASONS` and `ANSWER_REASONS` follow, and with them the
  combine-evidence and Gate decision readers.
- `apps/screamingface-engine/src/screamingface_engine/combine/evidence.py`: a failed
  `AnswerRecord` refuses every abstain word, as the SDK answer row already does. Without this
  check the wider `AnswerReason` would let a failed member carry `no_selection`.
- `apps/screamingface-engine/src/screamingface_engine/router_record_parts.py`: a Router
  `ModelSynthesis` or `VoteSynthesis` refuses `no_selection` and keeps every other abstain word.
  A synthesis runs only after a non-empty subset was selected, and `no_selection` is the outcome
  of selecting none.

New tests:
- `apps/screamingface-engine/tests/unit/test_router_abstain_reader.py`;
- `packages/screamingface/tests/test_router_abstain_reader.py`.

Pinned schemas, regenerated: each gains only the new enum entries, and its ID is kept.
- `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`;
- `packages/screamingface/tests/data/schemas/screamingface.answer.v1.json`.

Prior tests: owner-approved on 2026-11-27, 13 assertion transitions in 10 files. Each edit only
adds `no_selection`, changes the exact count 16 to 17, or excludes `no_selection` from a
writer-coverage set. No assertion is removed or weakened.
- Engine:
  - `test_combine_band.py`;
  - `test_combine_gate_words.py`;
  - `test_combine_pick_output.py`;
  - `test_combine_evidence_words.py`;
  - `test_combine_evidence_contract_fixture.py`;
  - `test_e4c_decision_cases.py`.
- SDK:
  - `test_gate_words.py` (2 tests);
  - `test_band_words.py` (2);
  - `test_evidence_words.py` (2);
  - `test_pick_output.py`.

No dependency, lock, public writer, Router runtime, report, UI or other prior path changes. The
private Router vocabulary (`router_vocabulary.py`) stays separate from the public `answer.v1`
words.

## Test plan

Each new case is written first and must fail first.

- **One synthetic answer, both sides.** These exact bytes decode on both sides, with status
  `abstain` and reason `no_selection`:

  `{"member_id":null,"value":null,"status":"abstain","reason":"no_selection"}`

  The Engine reads them through `ResultRecord`. The SDK reads them through `CombineResult` and
  the combine-evidence wire decoder, and reads the seven-field `answer.v1` `Answer` through
  `Answer.from_dict`. The Engine record serializes back to the same bytes.
- **Refused elsewhere**, on both sides:
  - with status `answered`, `fail` or `excluded`;
  - with a member or a value;
  - with the status and reason reversed;
  - with an extra or missing key;
  - with a reason that differs in case or whitespace, or is null for `abstain`.
- **Writers cannot emit it.**
  - `NoVotes(reason="no_selection")` is refused, and the six legacy words still work.
  - No module of the Engine combine package except `ports.py` names the word.
  - The Gate decision and combine scenario writers never produce it.
- **Legacy identity.**
  - Every legacy abstain word reads and serializes to the same bytes as before.
  - The new word is appended after `budget_refused` in the Engine enums, so earlier positions
    are unchanged.
  - The schema IDs stay `screamingface.answer.v1` and `screamingface.combine-evidence.v1`.
- **Cross-stack.** The SDK words equal the Engine's pinned combine-evidence enums, and both
  pinned schemas list the word.
- **Regression.** The full Engine and SDK suites run, with the 13 approved transitions and no
  other prior change.

## Acceptance

- The Engine and the SDK decode the same synthetic `no_selection` answer.
- An incompatible status or a malformed record fails closed.
- The pinned schemas keep their IDs and gain only the required enum entries. Legacy bytes are
  unchanged.
- The Gate, Band, Pick, budget and `NoVotes` writers cannot emit `no_selection`.
- Exactly 13 additive assertion transitions in 10 files, and no other prior path changes.
- New files are at most 450 lines.
- The Engine and SDK gates are green on Python 3.12 and 3.13, and the repo gates are green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, and no others.
  - Product: `combine/ports.py` (+15/-2), `combine/evidence.py` (+5), `router_record_parts.py`
    (+6/-1) and `answer.py` (+11/-1).
  - New tests: the Engine `test_router_abstain_reader.py` (307 lines) and the SDK
    `test_router_abstain_reader.py` (236 lines).
  - Pinned schemas: `screamingface.combine-evidence.v1.json` (+4/-2) and
    `screamingface.answer.v1.json` (+2). Both IDs are unchanged.
  - Prior tests: the 13 approved transitions in 10 files, Engine +34/-6 and SDK +22/-5.
- **Commit:** this ledger ships in the same publication commit as the implementation; the branch
  history and PR record its exact SHA. The candidate base is `7ec6329e`.
- **RED first:**
  - Engine: 4 failed (the synthetic round trip, the Gate read, the enum order and the pinned
    schema); the 31 guard cases passed before and after, as intended.
  - SDK: 6 failed (the wire round trip, `Answer.from_dict`, the Gate wire read, the word sets
    and both pinned schemas); the 33 guard cases passed before and after.
  - Engine, the two reader checks: 10 failed (a failed member with each of the seven abstain
    words, a Model and a Vote synthesis with the word, and the completed Router record); the 23
    new guard cases (the seven failure words, the six legacy words on both synthesis kinds, and
    syntheses without an abstention) passed before and after.
- **Gates:**
  - `run_gates.py screamingface-engine` and `run_gates.py screamingface` on Python 3.13: every
    gate is green except the append-only check. That check lists exactly the 12 approved prior
    paths and passes once the PR-open approval manifest pins their blobs. The draft blob map
    for those 12 paths, checked against the repository's approval matcher, accepts all 12 and
    refuses a changed blob.
  - Engine pytest: Python 3.13 13303 passed, 577 skipped, coverage 96.56%; Python 3.12 (ruff,
    format, pyright 0 errors, layering OK) 13302 passed, 578 skipped, coverage 96.56%.
  - SDK pytest, with `--extra notebook` as in CI: Python 3.13 and 3.12 both 8768 passed,
    54 skipped, coverage 97.02% and 97.01%. On 3.12, ruff and format are clean and pyright has
    0 errors.
  - `run_gates.py repo`: ALL GATES GREEN. `git diff --check` is clean.
- **Mutation controls:** 28 behavioral mutants, each run against the new test file of its side
  after a clean run of both files; all 28 were killed. The files were restored byte-exact, and
  their sha256 was verified. The mutants covered:
  - Engine words: the word dropped from `AbstainReason`, `AnswerReason` or `ABSTAIN_REASONS`,
    or placed before `budget_refused`;
  - Engine writers: `NoVotes` checking the reader set, its set keeping the word, a Pick writer
    emitting the word;
  - Engine readers: an abstain result with a member or value, a reason not tied to abstain on
    the result or the Gate result, the pinned schema losing the word;
  - Engine failed member: the check dropped, narrowed to the new word or to the legacy words, or
    widened to the failure words;
  - Router synthesis: the check dropped, its set keeping the word or holding only the word, a
    null reason refused;
  - SDK: the word dropped from either Literal or moved after the exclude words, a failed
    `Answer` carrying an abstain word, an abstain `Answer` naming a member, an abstain Combine
    result with a member or value, the Gate wire reason not tied to abstain, the `answer.v1`
    snapshot losing the word;
  - cross-stack: the Engine twin's synthetic bytes drifting.
- **Deviations:**
  - **Tail pins.** Six prior assertions pin the end of an enum by slice (`[-3:]`, or `[-2:]`
    once). They now pin one more element, with the word at the end, so every old element stays
    pinned. The 11 changed old lines are these six, the three counts and the two exclusions; no
    other old line changed.
  - **Shared test constants.** Two SDK test constants, `_GATE_NOT_MET_WORDS` and `_FIVE_WORDS`,
    gain the word. Each is used only by the approved tests in its file.
  - **Markers.** Each changed spot carries a C10 owner-approved-edit comment. The earlier E4c
    markers are kept as they were.
  - **NoVotes guard.** `_NO_VOTES_REASONS` is the reader set minus `no_selection`, so a future
    legacy word stays writable unless it is excluded on purpose. The Router synthesis set is
    built the same way.
  - **Two more reader files.** The wider word lists also reached a failed `AnswerRecord` and the
    Router synthesis records, which read the shared `AbstainReason`. Each now refuses the word
    with a validator, so the field types and the pinned combine-evidence schema stay as they
    are, and no prior test or schema changed for it. The SDK already refused a failed member with
    an abstain word (`CombineAnswerRow` and `Answer`).
  - **C5 wording.** The C5 contract calls a synthesis `reason` "an `answer.v1` abstain reason".
    After C10 that literally includes `no_selection`, which the reader now refuses. The contract
    text is unchanged here and may need a later clarification.
  - **File size.** `combine/evidence.py` was already 571 lines. The check adds 5 lines to its
    existing validator, not a new responsibility.
  - **SDK placement.** The word sits in the abstain group, after `budget_refused` and before the
    exclude words. The `answer.v1` snapshot stores sorted lists, so it gains only the two
    inserts.
  - **Not from this unit, found while checking:**
    - Two Engine inspect tests, `test_every_catalogue_row_has_an_answer_format` and
      `test_a_page_mentions_draft_feedback_exactly_when_it_offers_it[enigmaeval]`, fail on the
      clean base with the `inspect` extra, the CI inspect lane's shape: `enigmaeval` has no
      answer format.
    - The SDK e2e harness syncs the Engine venv with the `benchmarks` extra
      (`tests/e2e/harness/inspect_stack.py`). A local Engine run after the SDK suite therefore
      sees that extra, and 8 Engine catalogue and import-isolation tests fail. They fail the same
      way on the clean base with the same extras, and pass with the CI-shaped `--dev` venv.
    - One Python 3.12 Engine run hung at 99% with idle workers. The rerun passed in 2:25, and
      the hang did not recur.
  - **Base.** During this unit `origin/main` moved to `18fe4243`: two docs files of another
    unit, and the url4 2.0.0 release (version strings, a CHANGELOG and one line of the Engine
    lock). None of them overlaps this unit's paths. The gates above ran on the `7ec6329e` base.
  - **Out of scope.** No Router writer, Router runtime, report, UI, dependency or lock change.
    The private Router vocabulary stays separate from the public `answer.v1` words.
