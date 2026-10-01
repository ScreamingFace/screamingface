---
ticket: OME-1031
stack: screamingface
status: done
started: 2026-09-29
finished: 2026-09-29
---

# report-accounting-model-completeness — prevent incomplete model totals

## Intent

Address PR #1097 review: missing accounting must not disappear from a model's total.
The owner approved implementation of reliable identity plus conservative fallback in chat.
This is a follow-up on the existing PR and clean report-accounting worktree.

## Planned changes

- `accounting.py`: resolve missing record identities from unambiguous declarations only
  when retained request identities do not conflict; poison named model summaries when any
  row's model remains unknown. Remove mixed judge/request identity grouping.
- New `test_accounting_model_completeness.py`: regression and boundary coverage.
- Append spec/plan clarification and document the derived API behavior in the README.

## Test plan

- RED first: same model in two Cases with one missing accounting record.
- Direct member and solo model declarations; differing request identities; ambiguous
  synthesis; grading producer/request mismatch; missing request model on a present record.
- Preserve complete unrelated groups when attribution is reliable, actual zero costs,
  anonymous bucket observations, immutable mappings, root totals and retained JSON.
- Run all Client gates with append-only comparison to PR head `0ba16f8`.

## Acceptance

No named model group presents a partial total as complete; no inferred alias or invented
usage. Existing tests remain unchanged. Root totals and serialization remain unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** planned accounting source, new regression module, README, spec, plan
  and this ledger; no prior tests changed.
- **Commits:** `fix(client): keep incomplete model accounting totals unknown` (the commit
  containing this ledger; PR #1097 / existing OME-1031 branch).
- **Gates:** ALL GATES GREEN from `uv run .claude/scripts/run_gates.py screamingface
  --base 0ba16f8ce5dc7e71c59b7e4161b1ac95ecf84322`: append-only protection, Ruff lint/format,
  pyright, full pytest with the 95% coverage threshold, notebook provenance, build and
  distribution checks. Focused accounting tests: 26 passed, including 10 new cases.
- **Deviations:** two premature full-suite interruptions while investigating expected
  transport retry waits; the third unchanged full run passed every gate. Existing PR and
  issue reused; no new ticket, branch, public API entry or dependency required.

## Validation notes

- RED: 8 of the 10 new cases failed with numeric partial totals; 2 existing-behavior
  controls passed. GREEN: all 26 focused accounting tests passed.
- First full gate run passed append-only, lint, format and types, then was interrupted after
  1,800 passed tests near the local artifact-fetch fixture, after 265 seconds;
  isolated artifact-fetch tests passed 10/10 in 6.65 seconds without changes.
- Retried the unchanged full gate runner with `PYTEST_ADDOPTS=-o faulthandler_timeout=30`
  for diagnostic thread dumps only; no tests or checks excluded. Interrupted that run at
  135 seconds (655 passed), then confirmed from its thread dump and transport source that
  the disconnect tests exercise the full 90-second retry window. These interruptions were
  premature, not established test failures. A third unchanged full gate run is allowed to
  finish with the original waits intact.

## Wisdom and confidence review

The change stays inside the derived accounting view. Declaration lookup uses existing
operation/producer identity and rejects conflicting observed request names; no alias
heuristics, new dependency, wire change, or second accounting source. Unknown identity
invalidates named totals instead of guessing; complete anonymous observations remain
inspectable. Tests exercise numeric correctness, uncertainty, immutability and unchanged
root/JSON. Existing tests and API snapshots are untouched. No payload logging or schema
changes. This implements the owner's approved precise-attribution/conservative-fallback
choice with the existing summary type and no new public interface.

Final unchanged full gate run completed successfully: ALL GATES GREEN.
