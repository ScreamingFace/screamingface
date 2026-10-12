---
ticket: OME-1503
stack: screamingface
status: done
started: 2026-10-11
finished: 2026-10-11
---

# Reject Unicode corruption during result indexing

## Intent

The user requested fixing the review finding on PR #1269: the default incremental JSON parser silently replaces unpaired high surrogate escapes with question marks. Reject malformed Unicode before indexing rather than returning altered paid results.

## Planned changes

- Add bounded Unicode escape validation in `_results/unicode_validation.py` and invoke it from `_results/cases.py`.
- Add `tests/test_recovery_unicode.py` regressions for malformed escapes, valid pairs, literal backslashes, buffer boundaries, and healthy partial reports in both recovery APIs.
- Record the correction in a focused spec and plan.

## Test plan

Run new regressions RED on the reviewed head, then implement the validator. Preserve inherited tests. Run focused recovery tests and all SDK card gates.

## Acceptance

Unpaired escaped surrogates fail explicitly; valid Unicode and literal escape text retain exact values. Validation uses bounded reads. Healthy sibling results remain accessible. No new dependency or public API change.

## Outcome

- **Actual files:** the planned validator, index integration, new regression file, spec, plan, and this ledger.
- **RED:** the initial 11 cases produced 6 failures and 5 passes at the reviewed head. Lone high surrogates and both grouped recovery cases returned success; lone low surrogates failed without the expected explicit diagnostic.
- **Focused validation:** 103 Unicode/index cases pass, covering token boundaries, valid pairs, escaped literal text, both grouped recovery APIs, and old derivative receipts. Validation reads at most 65,536 bytes at a time.
- **Wisdom review:** retain the existing C parser and storage contract; a bounded pre-check prevents irreversible parser substitution. One extra sequential read is accepted so old matching index receipts cannot bypass validation. No dependency, API, schema, or inherited test changes.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface` — ALL GATES GREEN: append-only check, Ruff lint/format, Pyright, full parallel pytest with the 95% coverage floor, deterministic notebooks, build, and distribution checks. The first run found missing notebook test dependencies and a new assertion needing type narrowing; both were corrected.
- **Commit message:** `fix(screamingface): reject unpaired surrogate escapes in saved results`. Update existing PR #1269; no GitHub review comment or ticket closure.
- **Deviations:** none.
