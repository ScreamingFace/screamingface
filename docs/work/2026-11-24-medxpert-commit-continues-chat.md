---
ticket: OME-1980
stack: screamingface-engine
status: done
started: 2026-11-24
finished: 2026-11-24
---

# medxpert-commit-continues-chat — send MedXpertQA's turn 2 as a continuation of the Candidate's own chat

## Intent

MedXpertQA's commit turn (turn 2) is a new chat holding one user message: a JSON object with the
question, turn 1's reasoning and the trigger. The model does not see the reasoning as its own,
so it explains again ("A humeral shaft fracture should be…") and the first-letter grader reads
the wrong letter: an external researcher lost 475 of 2,450 Cases, about 11 points. A Fusion also
re-runs every member on turn 2 (8 calls per Case) and the members can overturn its answer.

Fix (owner decisions on OME-1980, 2026-11-23/24): turn 2 sends a real chat (user: the turn-1
CoT prompt, assistant: the turn-1 answer, user: the trigger), the official harness's layout.
When one model call wrote the turn-1 answer, only that model commits (a Fusion's synthesizer,
without its synthesis prompt: 5 calls per Case); any other recipe runs whole on the chat. The
answer reader keeps only the text between the first and second trigger, as the harness does.
Sampling and the system message stay as today (declared on the page), so turn 1 is
byte-identical and reruns replay it from the AI Gateway's shared cache.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/medxpert/commit.py` (new) —
  build the commit chat and the commit recipe.
- `.../benchmarks/medxpert/definition.py` — bind the commit chat and commit recipe between the
  turns; turn 2 reads them; description, answer format, named deviations; revision moves.
- `.../benchmarks/medxpert/runtime.py` — install the two routes; the check copies the members'
  turn-1 rows (evidence only) into a shortcut commit's record.
- `.../benchmarks/medxpert/answering.py` — first-to-second trigger split.
- `.../benchmarks/medxpert/revision_inputs.py` — protocol v3; drop unused sampling constants.
- Tests: `test_medxpert_commit_turn_bytes.py`, `test_medxpert_answering.py`, the fingerprint pin,
  the migration golden, the early-grade fixture, new `test_medxpert_commit_recipe.py`.

## Test plan

- The commit recipe: single model → itself; Fusion → synthesizer alone, no synthesis prompt,
  budget kept; Vote (combine route) / Gate / unparsable → the whole recipe.
- The commit chat: roles and order; empty turn-1 answer → no assistant message; malformed
  turn-1 record refused.
- End to end on the production executor: the gateway sees [system, user, assistant, user] on
  turn 2; a Fusion sends 5 calls per Case; a rerun's turn 1 and turn 2 bytes are identical;
  the Fusion's graded record keeps every member's row.
- Turn-1 request bytes unchanged from revision `1e5a3b8a461a52f7` (pinned digest).
- Reader: double trigger / double " answer is " read the text between the first two.

## Acceptance

- A prose-opening commit reply can no longer be produced by the JSON layout: turn 2 is the
  chat continuation, pinned by the end-to-end test.
- The relevant MedXpertQA tests, ruff and pyright on touched files pass.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `benchmarks/operation_outputs.py` (public `final_reference`),
  `benchmarks/picture_admission.py` (`node_model_routes`: the world's model routes),
  `tests/unit/inspect/test_benchmark_bump.py` and `CHANGELOG.md`.
- **Commits:** one squash-ready commit on `OME-1980-medxpert-commit-continues-chat`.
- **Gates:** relevant tests only, per owner rule: `test_medxpert_*.py` (all 13 files),
  `test_early_grade_compatibility.py`, `test_early_grade_connector_cache.py`,
  `test_picture_admission.py` → 180 passed; `inspect/test_benchmark_fingerprints.py`,
  `inspect/test_benchmark_bump.py` (inspect extra) → 107 passed; ruff check + format and
  pyright clean on the 12 touched Python files. Full suite left to CI.
- **Deviations:** (1) A model step is recognised by the world's model routes
  (`node_model_routes`), not by "not an Engine route": the world registers every model as an
  endpoint too, so the first draft took a Fusion for a non-model and ran it whole. (2) The chat's
  user message is the turn-1 CoT prompt, not the bare question, as the harness sends it.
  (3) Turn-1 bytes verified identical to `1e5a3b8a461a52f7` by running the same one-Case render
  at that revision's commit (digest pinned in `test_medxpert_commit_recipe.py`). (4) Edited prior
  tests, all owner-decided behaviour changes: the commit-bytes test's JSON-shape assertions became
  chat assertions; the reasoning-text route tests target the commit-chat route; the revision
  pins and the early-grade fixture's medxpert protocols moved to the new id and shape; found
  by the pre-push gate: the stage map lists the two new routes, the canonical url4 hash is
  re-pinned, the frozen-copy test counts member C's failure once (it is no longer called on
  turn 2), and the local-model Fusion test expects null accounting on the copied member rows.
- **Review round 1 (2026-11-24):** the turn-1 answer is stripped before it becomes the assistant
  turn (the harness's `response.strip()`), so a whitespace-only answer drops the message too;
  copied member rows now carry their turn-1 accounting, because the SDK's per-member and per-Case
  cost views read "unknown" on a null row and the run total comes from its own usage frame, so
  nothing is counted twice; an empty prompt or trigger fails as `benchmark_definition_error`, not
  `candidate_contract_error`; the commit-recipe route logs which path ran; the description says
  "a fusion closed by a synthesizer model"; a new end-to-end test runs a recipe the shortcut
  cannot lift; the local-model Fusion test is back to its original assertion.
