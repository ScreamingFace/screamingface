---
ticket: OME-1168
stack: screamingface
status: in_progress
started: 2026-09-10
finished:
---

# OME-1168 — Stop pasting the runtime envelope into the loop's judge prompt

## Intent

The CorrectiveLoop's coach prompt embeds the whole round object (`$loop_round_k`),
which drags each member's full Candidate Invocation envelope — accounting/usage
token counts, provider/model identifiers, request ids — into a paid model prompt.
Live token counts differ from replay's cache-hit zeros, so multi-round recorded
runs can never replay (all 9 multi-round OME-1098 ifeval cases miss). The fix is
client-side prompt rendering only: the coach's `verdicts` payload becomes a
per-member projection of {answer, feedback} built from dotted refs, leaving
`$loop_round_k` (which gate/select/answer/result legitimately consume, including
the envelope for verbatim selection) untouched. Tie-picker is already clean
(engine `_gate` emits only {key, answer}).

## Planned changes

- `packages/screamingface/src/screamingface/_evaluation/corrective.py` —
  `_coach` panel branch: replace `"verdicts": $loop_round_{attempt}` with a
  per-label struct of `$loop_check_{attempt}_{label}.answer` /
  `.feedback`; fold the verdict shape into the material hashed by
  `CORRECTIVE_PROTOCOL_REVISION` so the revision moves with the prompt shape.
- `packages/screamingface/tests/` — pin the new coach context shape; assert no
  accounting/provider/envelope text appears in any rendered judge-role body.

## Test plan

- RED: rendered-expression test that compiles a CorrectiveLoop candidate and
  asserts the coach role context references `.answer`/`.feedback` projections
  and does NOT reference the bare round object; assert the strings
  `accounting`/`candidate-invocation` cannot flow into the coach context
  (structural: the coach context contains no `$loop_round_` reference).
- Invariant kept: gate/select/answer contexts still reference
  `$loop_round_{k}` (verbatim-selection path untouched).
- `CORRECTIVE_PROTOCOL_REVISION` changes vs the previous constant value.
- All prior corrective tests stay green unmodified (append-only).

## Acceptance

- Coach prompt context = {request, task, verdicts: per-member {answer, feedback}}.
- No envelope fields reachable from any judge-role rendered context.
- Round object untouched for gate/select/answer/result.
- Protocol revision hash covers the verdict shape.
- Full `screamingface` stack gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned —
  `packages/screamingface/src/screamingface/_evaluation/corrective.py`
  (`_coach` panel branch renders per-member `{answer, feedback}` projection;
  new `_COACH_VERDICT_FIELDS` constant generates the projection AND is folded into
  `CORRECTIVE_PROTOCOL_REVISION`, now `f8fcb8eada80aa7d`, was
  `284c47e50ca0ba4f`) +
  `packages/screamingface/tests/test_corrective_compilation.py` (3 new tests).
- **Commits:** single commit on `OME-1168-judge-prompt-minimal`
  (`fix(py-screamingface): render only answer and feedback into the loop coach prompt`).
- **Gates:** `run_gates.py screamingface` ALL GREEN — append-only check, ruff
  check/format, pyright, pytest 1420 passed / 22 skipped (cov ≥95),
  notebooks, build, distribution.
- **Deviations:** review findings applied pre-commit — the verdict-fields constant
  is underscore-private and the coach projection is generated from it, so reshaping
  the prompt shape necessarily moves the protocol revision. Follow-up owned by `OME-1098`: fresh ifeval
  CorrectiveLoop recording (rendered keys changed), then `just e2e-bless-fresh`.
