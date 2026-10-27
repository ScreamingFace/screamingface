---
ticket: OME-1746   # review follow-up of PR #1571; owner chose to reuse the issue
stack: aigateway
status: done
started: 2026-10-27
finished: 2026-10-27
---

# openrouter-zero-proof-review-fixes — three review fixes for the OpenRouter zero proofs

## Intent

The `/code-review` of PR #1571 (OME-1746, merged 4cb803eab) found three issues in the OpenRouter
zero proofs that the owner chose to fix (2026-10-27):

- **#7 crash:** a pipeline stage `type` that is a list or object raises `TypeError`, and a
  count `"sNaN"` raises `InvalidOperation`. The proof must return a result for any value.
- **#1 refusal output in other fields:** the refusal proof reads only five message fields, so
  output in `audio`, `images`, `annotations` or a top-level `output`/`content` is not seen.
- **#2 paid stage:** the `plugin`/`server_tools` stage rule is only in the 429 proof. Both
  proofs must share it.

Not in scope (owner decision): review findings #3–#6, #8–#10.

## Planned changes

- `apps/aigateway/src/aigateway/plugins/openrouter_provider/billing_facts.py`: `is_zero` never
  raises (`Decimal.is_zero()`); new `is_empty`, `has_no_output(raw_response, message)` and
  `pipeline_has_paid_stage` (moved from `zero_insurance.py`; a paid name anywhere in the stage
  `type`, any value shape).
- `pre_output_refusal.py`: use `has_no_output` (every message field except `role` is empty, and
  the top-level `output`/`content` are empty) and `pipeline_has_paid_stage`.
- `zero_insurance.py`: use the shared `pipeline_has_paid_stage` and output check.
- New test `tests/unit/usage_accounting/test_openrouter_zero_proofs_review_fixes.py`.
- Specs: `docs/spec/2026-10-26-openrouter-pre-output-refusal-zero.md` §9;
  `docs/spec/2026-10-06-OME-1446-proven-zero-retry-accounting.md` amendment note;
  `apps/aigateway/docs/usage-accounting.md`.

## Test plan

- #7: stage `type` as a list or object, and `"sNaN"` / `Decimal("sNaN")` counts and costs,
  give a result and never raise; `["plugin"]` is a paid stage.
- #1: a refusal with non-empty `audio`, `images`, `annotations`, an unknown non-empty message
  field, or a top-level `output`/`content` stays unknown; empty values (`[]`, `{}`, `""`,
  `null`) still certify.
- #2: a refusal with a `plugin` or `server_tools` stage stays unknown; a `guardrail` stage still
  certifies.
- All prior tests stay unchanged and green.

## Acceptance

- The three issues are fixed in both proofs; no prior test changed; `run_gates.py aigateway` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. `_PAID_STAGE_TYPES` and the output check moved from
  `zero_insurance.py` / `pre_output_refusal.py` into `billing_facts.py`; the refusal proof now runs
  the cheap refusal checks before the walks over the whole reply.
- **Commits:** see the PR (one squash commit).
- **Gates:** `run_gates.py aigateway --base <merge-base 4cb803eab>` ALL GATES GREEN (2026-10-27):
  append-only, ruff, format, pyright, no-enterprise, pytest with coverage; 779 accounting tests
  pass (28 new). No prior test changed.
- **Deviations:** none. A stage `type` is read as text in any shape, so `["plugin"]` and
  `{"name": "server_tools"}` count as paid stages (fail toward unknown for a paid name).
