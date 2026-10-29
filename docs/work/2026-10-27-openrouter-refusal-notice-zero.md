---
ticket: OME-1753
stack: aigateway
status: done
started: 2026-10-27
finished: 2026-10-27
---

# openrouter-refusal-notice-zero — a refusal notice is not output

## Intent

The pre-output refusal proof (spec 2026-10-26, §9) counts any text in `message.refusal` as
output. Anthropic sometimes puts a fixed policy notice there ("This request triggered
restrictions on violative cyber content…", "…high-yield explosives…"). These replies have no
`usage`, no output tokens and no cost, so OpenRouter did not bill them. Today they stay
`unavailable` and the run shows "—". The prod cache backfill of 2026-10-27 found 8 such rows
(of 160) and the owner priced them at $0 by hand. This unit makes the live proof agree: text in
`refusal` is not output. The proof still needs no `usage`, so a refusal that comes after billed
output (it carries `usage.cost`) keeps its reported price.

## Planned changes

- `apps/aigateway/src/aigateway/plugins/openrouter_provider/billing_facts.py`: remove `refusal`
  from `_MESSAGE_OUTPUT_FIELDS`, with a WHY.
- `apps/aigateway/tests/unit/usage_accounting/test_openrouter_pre_output_refusal_notice.py`
  (new).
- `apps/aigateway/tests/unit/usage_accounting/test_openrouter_pre_output_refusal.py`: remove the
  one `refusal-text` case (owner-approved prior-test change,
  `.claude/test-change-approvals/OME-1753.json`).
- `docs/spec/2026-10-26-openrouter-pre-output-refusal-zero.md` §10;
  `apps/aigateway/docs/usage-accounting.md`.

## Test plan

- RED: both real notices, and a plain refusal sentence, with no `usage` → certified zero, both
  through `proves_pre_output_refusal` and end to end through the plugin.
- Still unknown: a notice with `usage` (cost or output tokens), a notice with `content`,
  `reasoning` or `reasoning_details`, a notice with a paid stage, a notice with a cost field.

## Acceptance

- A refusal before output that carries a notice in `refusal` and no `usage` is certified
  `provider_guaranteed_zero` / `openrouter.pre_output_refusal`.
- Every other rule of the proof is unchanged; aigateway gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `.claude/test-change-approvals/OME-1753.json` and the task
  mirror `docs/tasks/2026-10-27-OME-1753-openrouter-refusal-notice-zero.md`.
- **Commits:** one commit, `fix(aigateway): price an OpenRouter refusal with a policy notice at $0`.
- **Gates:** `run_gates.py aigateway`: ALL GATES GREEN (approved OME-1753 test transition,
  append-only, ruff check, ruff format, pyright, no-enterprise, pytest with coverage >= 80%).
  Usage-accounting suite: 790 passed. RED first: the 3 certify cases failed before the change.
- **Deviations:** none.
