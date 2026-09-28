---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress
started: 2026-09-28
finished:
---

# paid-smoke-haiku-member — swap the paid smoke's deepseek member for claude-haiku-4.5

## Intent

The 2026-09-28 paid press went red on two boards (`inspect-lab_bench_cloning_scenarios`,
`inspect-lab_bench_seqqa`): every Case died on `model_token_cap`, so their grading ran zero
times. The pipe was fine; the panel was not. A Fusion Case needs every member's answer, and
`deepseek-v4-flash-0731` burned its whole 32,768-token budget thinking on 4 of 48 Cases
(qwen did so once). Replace it with `claude-haiku-4.5`, which answers without thinking and so
always finishes, and keep qwen as the one reasoning member so the engine's reasoning-only
code (reasoning-field parsing, token-cap / reasoning-only-reply codes, reasoning-token
accounting) stays proven live.

Decided in conversation with the owner: the Case-dies-when-a-member-fails behaviour is kept
(member quorum stays parked in OME-559); raising `max_tokens` was rejected in favour of the
swap.

## Planned changes

- `packages/screamingface/tests/paid/_panel.py` — `MEMBER_MODELS[1]` →
  `openrouter/anthropic/claude-haiku-4.5`, plus a WHY comment on the roster.

## Test plan

- Free: `tests/paid/test_panel_models.py` stays green (haiku is a gateway seed).
- Paid (owner-run): re-press the two lab_bench boards; both must grade ≥1 Case.

## Acceptance

- Free paid-lane guards green.
- Owner's re-press: `lab_bench_cloning_scenarios` and `lab_bench_seqqa` each grade ≥1 Case.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `packages/screamingface/tests/paid/_panel.py`, plus this ledger.
- **Commits:** `test(screamingface): swap the paid smoke's deepseek member for claude-haiku-4.5`
- **Gates:** free paid-lane guards `SCREAMINGFACE_TEST_PAID=1 pytest tests/paid --deselect <the paid smoke>` → 25 passed (incl. `test_panel_models_are_gateway_seeds`); ruff check + format clean. Paid re-press pending (owner).
- **Deviations:** none.
