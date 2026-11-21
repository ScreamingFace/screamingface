---
ticket: OME-1786
stack: screamingface-engine
status: done
started: 2026-11-21
finished: 2026-11-21
---

# medxpert-turn2-reasoning-text-only — send only the reasoning text on MedXpertQA's commit turn

## Intent

MedXpertQA asks each Case in two turns: turn 1 reasons, turn 2 (the commit) is a new call that
carries the question, turn 1's answer and the trigger. Turn 2 carried turn 1's WHOLE result
record, a JSON string that also holds the call's accounting (tokens, cost, latency, attempts,
cache hit or miss). On a rerun turn 1 is a cache hit, the Engine accounts it as zeros and
"hit", so turn 2's request bytes change, the AI Gateway's request cache (which hashes the
messages verbatim) misses, and the commit is billed again and can draw another letter. An
external researcher saw 1,899 of 2,450 commit calls billed again on an identical rerun, and one
grade changed. A frozen-copy replay of a scored Case fails the same way (`frozen_copy_miss`),
which is how the ticket was first filed. The model also read its own token counts in the prompt.

Fix: turn 2's `reasoning` field carries only the record's `output` text. This is the "smaller
first step" named by GitHub issue 1966; turn 2 stays one new call to the whole Candidate.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/medxpert/definition.py` — a
  MedXpertQA-owned route `REASONING_TEXT_ROUTE` bound between the turns; turn 2 reads
  `$reasoning_text`; `compute_revision` takes the protocol constant; `REVISION` moves.
- `.../medxpert/runtime.py` — the route's handler, reusing `_reasoning_text`; installed by `install`.
- `.../medxpert/revision_inputs.py` — `PROTOCOL_REVISION` `two-turn-cot-v1` → `two-turn-cot-v2`.
- `apps/screamingface-engine/tests/unit/test_medxpert_commit_turn_bytes.py` (new).
- Revision pins, per `docs/adding-an-imported-benchmark.md` "Changing a Benchmark's published
  revision": the migration golden, the early-grade fixture, the fingerprint table, plus the
  canonical-expression hash and the bump test's printed line. `CHANGELOG.md`.
- This ledger and the mirror `docs/tasks/2026-10-29-OME-1786-medxpert-turn2-replay-miss.md`.

## Test plan

- RED first: one Case run twice on the production executor against a gateway stand-in with a
  request cache keyed on the body; run 2's turn 1 is a cache hit. The two turn-2 request bodies
  must be identical and run 2's commit must be a hit.
- Turn 2's user message is exactly `{question, reasoning: <turn-1 text>, trigger}` and holds
  none of the record's keys.
- A scored Case replays from its frozen copy.
- Turn 1 refused / empty / abstained / failed (see Decisions).
- The revision moved, and the old protocol constant still computes the old id.

## Decisions — what turn 2 receives when turn 1 has no usable answer

A Candidate's record always has a text `output`; it is empty unless the status is `completed`
with an answer. The route returns `output` and nothing else, so:

| turn 1 | record | turn 2 before | turn 2 now | grading outcome |
|---|---|---|---|---|
| answered | `completed`, text | whole record | the text | unchanged rule: commit letter graded |
| refused | `refused`, `output` empty, refusal text or null | whole record, refusal inside | empty reasoning | unchanged: turn 2 still runs, its letter is graded |
| empty answer | `completed`, `output` empty | whole record | empty reasoning | unchanged: turn 2 still runs |
| Fusion abstained | `completed`, `abstained`, `output` empty | whole record | empty reasoning | unchanged: turn 2 still runs |
| failed (error, token cap) | no record: the call raises | never reached | never reached | unchanged: the Case fails before turn 2 |

Why empty and not the refusal text: the task is that turn 2 carries the answer text and nothing
else from the record; a refusal is not the model's reasoning, and an empty string is the same
bytes on every run. The ticket asks for no change to how these Cases are graded, and none is
made: the same turns run and the same reply is graded. The model's reply to an empty reasoning
may differ from its reply to a record; that is part of the exam change the revision move names.

`_reasoning_text` is reused unchanged (its fallback returns its input when the input is not a
decodable record; a turn-1 binding is always a record, so the route never takes it).

## Acceptance

- A rerun sends byte-identical turn-2 requests; the commit is a cache hit.
- No accounting key reaches the turn-2 prompt.
- MedXpertQA's published revision moves and every pin names the old id.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Also `.claude/test-change-approvals/OME-1786.json`, pinning the
  five prior test files the revision move edits (owner-approved move).
- **Revision:** `1e5a3b8a461a52f7` → `490235dc9a53b7d9` (fingerprint equal). Signed off by the
  owner on 2026-11-21 (implementation and the revision move approved in plain words).
- **Commits:** `fix(screamingface-engine): send only the reasoning text on MedXpertQA's commit turn`,
  `docs(tasks): close the OME-1786 mirror and ledger`.
- **Gates:** RED on the unchanged code: 3 of 3 executor-level pins failed (turn-2 bodies differ
  at `input_tokens` 40 vs 0 and `misses` 1 vs `hits` 1). GREEN: 345 passed, 12 skipped across
  the 46 Engine test files that mention medxpert plus `test_early_grade_compatibility.py`
  (extra-less venv, as CI); the new file is 10 of those. Mutation check: putting the record
  back on turn 2 fails 4 of the 10. Inspect lane (`uv run --isolated --extra inspect`), the 10
  `tests/unit/inspect` files that mention medxpert: 327 passed, 2 failed, both on the
  `enigmaeval` row's description (`test_answer_formats_every_row.py`,
  `test_draft_feedback_on_page.py`); this branch touches no file of the inspect plugin, so
  they are not from this change (not re-run on `main` here). ruff check, ruff format and
  pyright clean on the 8 touched Python files.
- **Deviations:**
  - The early-grade fixture's two medxpert protocols gained the reasoning-text binding as well
    as the new id. The bump checklist names only the id, but the fixture is compared call for
    call with today's protocol, so the legacy-shaped protocol has to describe the same exam.
  - Five prior test files changed (revision pins only), approved by blob in
    `.claude/test-change-approvals/OME-1786.json`.
  - `tests/unit/test_frozen_copy_failed_case.py` keeps an AIDEV-NOTE saying a scored MedXpert
    Case cannot replay. It is now out of date (the new replay test proves the opposite). Left
    unedited: append-only rule, and it is outside the revision pins the owner approved.
- **Owner-verify:**
  - Post the revision move to the team (bump checklist step 4).
  - The Fidelity Record `apps/screamingface-engine/docs/benchmarks-fidelity/medxpert.md` pins
    the old id and describes turn 2 as carrying the record; it now reads stale in
    `just engine fidelity-check`. Re-auditing it and its verdict is an owner step.
  - Entries under the old id leave the default leaderboard; a hand-built Benchmark has no
    re-grade path, so they need fresh (paid) runs.
  - `public-docs/src/pages/sf-client/` shows the old id in five example outputs (another
    landing, not touched here).
  - GitHub issue 1966's real continuation will move the revision again unless it merges
    together with this; whether to hold this PR for it is the owner's call.
  - No recorded golden or snapshot of MedXpertQA exists, so nothing needs a re-record.
