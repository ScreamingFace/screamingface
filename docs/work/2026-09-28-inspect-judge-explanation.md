---
ticket: OME-1339
stack: screamingface-engine
status: done
started: 2026-09-28
finished: 2026-09-28
---

# inspect-judge-explanation — imported boards' judge reasoning reaches the notebook report

## Intent

On imported (inspect_evals) boards the notebook report's criteria section shows a verdict and
no reasoning: the inspect adapter copies the scorer's `explanation` only into the evidence's
`raw_output`, and the report reads `explanation`. Fill `explanation` too, so a judged imported
board shows its judge's reasoning like our own judged boards.

Owner decision (2026-09-28): inspect's match, choice, pattern and math scorers set
`explanation` to the candidate's own answer, not to any reasoning. The adapter fills
`explanation` only when the text differs from the answer being graded, so exact-match boards
don't repeat the answer under the verdict. `raw_output` keeps the verbatim text either way.
A scorer's own message differs from the answer and does show (boolq's `pattern()` "Scoring
pattern not matched in output: …", AIME's "Model produced empty completion"); it says why a
Case failed, which is what the field is for (review finding, kept by the literal decision).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/shim.py` — the check builder
  receives the graded completion and sets `explanation` when the scorer's text is non-empty
  and differs from that completion.
- `apps/screamingface-engine/tests/unit/inspect/test_inspect_shim.py` — new tests (append-only).
- `apps/screamingface-engine/tests/unit/inspect/test_inspect_frontierscience_board.py` — one
  new end-to-end test through the board's aggregate route.

## Test plan

- A judge-style explanation (differs from the answer) lands in `explanation`; `raw_output` is
  byte-identical to before.
- A real `match()` scorer (explanation = the completion) leaves `explanation` absent.
- An empty or missing explanation leaves `explanation` absent.
- End to end: a judged imported board's aggregate result carries the judge's text in the
  case evidence's `explanation`, and the wire model accepts it.

## Acceptance

- Ticket acceptance, amended by the owner decision above.
- `run_gates.py screamingface-engine` green, plus the inspect lane
  (`uv run --extra inspect pytest tests/unit/inspect`).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `shim.py` (new `_judge_reasoning`, the graded completion
  threaded from `_task_state`'s output into `_check`), two test files, plus the `docs/tasks`
  mirror for OME-1339.
- **Commits:** see the PR (squash-merged).
- **Gates:** `run_gates.py screamingface-engine` — ALL GATES GREEN; inspect lane
  `uv run --extra inspect pytest tests/unit/inspect` — 364 passed. RED showed the two
  "fills explanation" tests failing and the three "stays absent" guards passing.
- **Deviations:** (1) the owner decision above narrows the ticket: an explanation equal to
  the graded answer is not copied. (2) The ticket expected recorded replay fixtures to need
  re-recording; no committed fixture carries inspect evidence, so none changed. (3) The
  ticket's SDK render test is not here: rendering `explanation` is already pinned SDK-side,
  and the long-text rendering is `OME-1340`'s. This PR proves the engine writes the field
  and the wire model accepts it, end to end through the frontierscience board.
