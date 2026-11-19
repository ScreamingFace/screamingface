---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-11-19
finished: 2026-11-19
---

# credit-reason-followup — keep "Key rejected" when the execution key itself is rejected

## Intent

Follow-up to PR #1942 (OME-1968, merged 2026-11-19), from Sergey's review (request changes,
1 blocker, 2 minor). In the BYOK connection panel, a rejected **execution** key now shows
"Management key rejected" on the account box, even for users with no management key. When the
execution key's `/key` call returns 401/403 the Gateway marks both amounts
`credential_rejected` and never tries the management key. So the management wording is right
only when the key allowance itself still read.

## Planned changes

- `packages/screamingface/src/screamingface/_ui/credit_view.py`: apply `_ACCOUNT_NOTES` to the
  account box only when `status.key.reason != "credential_rejected"`; otherwise `_REASON_NOTES`.
- `packages/screamingface/src/screamingface/credit.py`: the WHY comment in `_unavailable()`
  cites OME-1968, not OME-1935 (minor).
- `docs/spec/2026-11-17-credits-repr.md`: the account-box sentence says the management wording
  applies only "when the key allowance was not itself rejected".
- `docs/work/2026-11-18-credit-reasons.md`: correct "three tests failed first" to two tests that
  fail first plus tests that pin unchanged wording (minor).
- New tests only in `packages/screamingface/tests/` (no prior test edited).

## Test plan

- Panel mode (`hosted=False`), both amounts `credential_rejected`: notes are
  `["Key rejected", "Key rejected"]`. Fails today (gives "Management key rejected" first).
- Companion: only the account amount rejected, key reads an amount: the account note is still
  "Management key rejected". Passes before and after; pins the intended wording.

## Acceptance

- Both tests green; `run_gates.py screamingface` green; append-only check green.
- Spec, ledger and comment corrected as listed.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus a one-sentence CHANGELOG clarification. New test file
  `tests/test_credit_panel_rejection.py` (2 tests).
- **Commits:** see the PR.
- **Gates:** `run_gates.py screamingface` ALL GATES GREEN. The append-only check passed, so
  no prior test was edited. The credit tests give 29 passed.
- **Deviations:** none. The companion test asserts only the account box's note, because a
  readable key allowance renders an empty note element.
