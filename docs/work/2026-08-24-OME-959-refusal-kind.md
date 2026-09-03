---
ticket: OME-959
stack: screamingface
status: in_progress
started: 2026-08-24
finished:
---

# OME-959 — Say whether a refused case was declined by the provider or refused by the model

## Intent

A refused Case in a client `Report` carries one ambiguous `refusal: str | None`; a
reader cannot tell a provider that declined to serve the call apart from a model that
answered by refusing. The Engine already emits the split on the wire — this unit reads
it client-side, without touching the wire format or the `scored/refused/failed` status
semantics.

## Wire evidence (decision gate: signal IS on the wire)

The Engine classifies a refused turn in
`apps/screamingface-engine/src/screamingface_engine/runner/model_response.py:50`:
`finish_reason == "content_filter" or refusal is not None` → `provider_refusal`
(OME-745). The bound `ModelOutcome(finish_reason, refusal)` is carried verbatim onto
the `screamingface.candidate-result.v1` Case
(`benchmarks/invocation.py:45-59` → `benchmarks/contract.py:135-136` `CaseResult
.finish_reason/.refusal` → `benchmarks/aggregation.py:278-311 refused_case_result`).
So a refused Case on the wire TODAY distinguishes the two kinds by its raw fields:

- provider declined: `finish_reason == "content_filter"` (filter turns normally carry
  null refusal text — invariant comment at `model_response.py:49`)
- model refused: non-null `refusal` (the provider `message.refusal` field — the
  model's own refusal message), `finish_reason` typically `"stop"` or null

No explicit kind field exists on the wire; the classification is a deterministic
function of the two fields the client already decodes
(`packages/screamingface/src/screamingface/_evaluation/results.py:256-268`).

## Planned changes

- `packages/screamingface/src/screamingface/case_result.py` — `RefusalKind` type
  alias + derived read-only property `CaseResult.refusal_kind` (no new wire field,
  no `to_dict` change: absence stays absence, old payloads load unchanged).
- `packages/screamingface/tests/test_case_refusal_kind.py` — new test module
  (per-concern module layout, keeps prior test files untouched).

## Test plan

Failing tests first, each naming its invariant:

- a `content_filter` refused payload reads as the provider declining
- a `refusal`-field refused payload reads as the model refusing
- both signals present → provider declined (mirrors the Engine's own check order)
- a refused payload with neither signal (older Engine) loads with kind `None` — never
  a crash, never a guess
- a failed Case with a provider error (e.g. a 402) has no refusal kind — a provider
  402 must not read as a model refusal
- a scored Case has no refusal kind
- `to_dict()` is byte-identical to the wire payload — the derived kind is never
  serialized, so saved reports and old readers are untouched
- a locally built refused CaseResult derives the kind the same way

## Acceptance

- A refused case in a client `Report` states which of the two kinds it was,
  round-tripping from the real engine payload shape.
- `scored/refused/failed` semantics unchanged; full screamingface suite green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** exactly as planned —
  `packages/screamingface/src/screamingface/case_result.py` (+26 lines: `RefusalKind`
  alias + derived `CaseResult.refusal_kind` property, nothing serialized) and
  `packages/screamingface/tests/test_case_refusal_kind.py` (11 new tests, RED-first:
  10 failed before the property existed, the byte-identical-export test passed by
  construction).
- **Commits:** uncommitted — pending local owner review
- **Gates:** ALL GREEN — ruff check ✓ · ruff format --check ✓ · pyright ✓ (0 errors) ·
  `pytest --cov=screamingface --cov-fail-under=95 -q` ✓ **1076 passed, 1 skipped**
  (was 1066 collected; coverage 95.05%) · check_notebooks.py ✓ · uv build ✓ ·
  check_distribution.py ✓.
- **Deviations:** none in scope. One ruff-shaped adjustment: the property folds its
  last two returns into one conditional expression (PLR0911 caps returns at 3).
  Surface note for the sibling ticket pinning the public SDK surface: `sf.CaseResult`
  gains the read-only `refusal_kind` property (and `screamingface.case_result` gains
  the `RefusalKind` alias); `sf.__all__` is unchanged. Merge-order with the
  surface-pinning ticket (OME-963) IS load-bearing: that branch replaces
  `test_public_interface.py` with a snapshot pinning class-defined properties, so
  `refusal_kind` will appear in the snapshot — whichever branch merges second must
  regenerate it (owner-review confirmed).
- **Review follow-up (2026-08-25):** the five classification tests collapsed into one parametrized signal-table test (owner-requested); count unchanged at 11.
