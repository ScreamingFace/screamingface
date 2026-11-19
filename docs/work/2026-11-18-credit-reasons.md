---
ticket: OME-1968
stack: screamingface
status: done
started: 2026-11-18
finished: 2026-11-18
---

# credit-reasons — the right note when a hosted lookup or a management key fails

## Intent

Follow-up to `OME-1935` (PR #1883), from its second independent review. Two credit notes
say the wrong thing; neither has reached PyPI, so fixing them before the next SDK release
means no grantee sees them.

1. A failed credit request falls back to `credit._unavailable()`, whose hosted amount
   carries `hosted_unavailable`. A hosted user's panel then says "Not available on hosted"
   instead of "Lookup failed".
2. The Gateway marks the account `credential_rejected` when the management key gets a 401
   while the execution key still reads. The account box says "Key rejected", which reads as
   the execution key failing.

Behaviour is specified in `docs/spec/2026-11-17-credits-repr.md` (updated here).

## Planned changes

- `packages/screamingface/src/screamingface/credit.py`: `_unavailable()` marks every amount,
  hosted included, `lookup_failed`.
- `packages/screamingface/src/screamingface/_ui/credit_view.py`: the account box maps
  `credential_rejected` to "Management key rejected"; the key box and the neutral box keep
  "Key rejected".
- `packages/screamingface/tests/test_credit_repr.py`: three new tests.
- `docs/spec/2026-11-17-credits-repr.md`, `packages/screamingface/CHANGELOG.md`.

## Test plan

- RED first:
  - a hosted panel on the real `_unavailable()` result says "Lookup failed";
  - the account box says "Management key rejected" next to a readable key allowance;
  - both amounts rejected still read "Key rejected" in the neutral box.
- One committed test case encodes the old account-box wording
  (`test_an_unavailable_amount_says_why[credential_rejected]`, reason on the account slot).
  Owner decision 2026-11-18: move that case's reason to the key slot, where "Key rejected"
  is correct. Recorded under Deviations.

## Acceptance

- The three new tests pass; all other credit tests pass unedited apart from the one case
  above.
- SDK gate green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned: `credit.py` (`_unavailable()`), `_ui/credit_view.py`
  (`_ACCOUNT_NOTES`, a `notes` parameter on `_amount_html`), `tests/test_credit_repr.py`
  (4 new tests, 1 case moved), `CHANGELOG.md`, the OME-1935 spec; plus this ledger, the
  mirror and `.claude/test-change-approvals/OME-1968.json`.
- **Commits:** `31c1158e8`, squash of [PR #1942](https://github.com/ScreamingFace/screamingface/pull/1942), merged 2026-11-19 after HupBaHa's approval.
- **Gates:** `run_gates.py screamingface` all green, including the append-only check with
  the approved OME-1968 transition. `test_credit_repr.py`: 27 passed.
- **Deviations:** the `credential_rejected` case of `test_an_unavailable_amount_says_why`
  (reason on the account slot, expecting "Key rejected") moved to the key slot in a new
  test, by owner decision and recorded in the approval manifest. The CHANGELOG entry from
  OME-1935 was rewrapped to keep its lines under 100 characters.
