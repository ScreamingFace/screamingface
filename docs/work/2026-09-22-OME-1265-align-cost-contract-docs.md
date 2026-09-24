---
ticket: OME-1265
stack: scoreboard
status: done
started: 2026-09-22
finished: 2026-09-22
---

# OME-1265 — Align the OME-822 contract docs with the expand phase that shipped

Follow-up from the review of PR `#841` (Dmitry, 2026-09-22, explicitly non-blocking). Branch
from `origin/main` at `99e2d4b2` — the `#841` merge itself, so the shipped behaviour is in the
base and can be read directly.

## Intent

`#841` shipped the **expand** phase. Six contract surfaces still describe the **contract** phase
that `OME-1258` owns. A reader would conclude the board already refuses a silent client. It does
not, and shipping a client on that belief is the concrete way this drift costs something.

## Ground truth, read from the base commit

`ScoreSubmission.validate_cost_matches_its_status`:

```python
if self.run_cost_status is None:
    if self.run_cost_usd is not None:
        self.run_cost_status = "complete"
    return self          # neither field: ACCEPTED, both stay None
```

Pinned by `tests/unit/scores/test_schemas.py::test_a_submission_with_neither_amount_nor_status_stays_unlabelled`.
So "omitting both is rejected" is false against the code, and a prior test says so.

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/schemas.py` — two comment blocks (~L410-414, ~L431-433)
- `docs/spec/2026-09-21-OME-822-cost-status.md` — §2
- `docs/plan/2026-09-21-OME-822-cost-status.md` — the RED list and the wire bullet
- `docs/tasks/2026-09-04-OME-822-require-run-cost.md` — the contract table and narrative

Already fixed outside this unit, on 2026-09-22: the `OME-822` Linear Scope bullet and its
**Acceptance bullet 1, which was ticked ✅ for a behaviour the code does the opposite of.** That
one was corrected immediately rather than queued here, because closing `OME-822` would have
frozen a false "delivered" into the record. PR `#841`'s body is the sixth surface and is edited
alongside this branch.

## Test plan

**None, and deliberately.** This unit changes comments and prose only. No production statement
changes, so no test can demand it and no prior test may move. The bar is that the scoreboard
gates stay exactly where they are: a comment-only change that moves a gate means it was not
comment-only.

## Acceptance

- no surface in the repo claims a submission omitting both fields is rejected
- no surface claims `run_cost_status` is required on the request today
- `schemas.py` no longer contradicts its own validator docstring 40 lines below
- each corrected location names `OME-1258` as the owner of the flip
- scoreboard gates green

## Outcome

- **Actual files:** the four planned, plus a fifth found during verification —
  `apps/scoreboard/src/scoreboard/scores/schemas.py`,
  `docs/spec/2026-09-21-OME-822-cost-status.md`,
  `docs/plan/2026-09-21-OME-822-cost-status.md`,
  `docs/tasks/2026-09-04-OME-822-require-run-cost.md`,
  `docs/work/2026-09-21-OME-822-cost-status.md`.

- **Gates:** `run_gates.py scoreboard --base origin/main` — **ALL GATES GREEN**, and notably
  **without** `--skip-append-only`. That is the proof this was comment-only: the append-only
  check compares tests against `origin/main` and found nothing moved.

- **Deviations:**

  1. **A SEVENTH location, not in the review.** Dmitry named six. Grepping the shipped claims
     turned up `docs/work/2026-09-21-OME-822-cost-status.md` as well — the `OME-822` ledger's own
     Intent says *"Omission is still rejected, which is what this ticket exists to enforce."* Its
     Review-round-2 section 130 lines below already records the correct expand contract, so the
     document contradicts itself, and the stale half is the half a reader meets first.

  2. **Marked, not rewritten, in the two historical artifacts.** The plan and the `OME-822`
     ledger are records of what was planned and believed at the time. Rewriting them would erase
     the audit trail this repo's SDLC rests on, and the review finding is precisely that the
     record misleads — so each false claim is struck through with a pointer to what superseded
     it. The spec and the task mirror ARE corrected in place: a governing spec and a status
     mirror are supposed to state the current contract, not a past intention.

  3. **The sharpest drift was not on anyone's list.** `schemas.py` asserted two opposite things
     about the same validator 40 lines apart — *"Omitting both is still rejected"* above the
     field, and *"An absent status with no amount stays absent"* in the validator docstring
     below it. Its `INVARIANT (OME-822)` header also described a *"non-nullable required field"*
     declared `Decimal | None = Field(default=None, ...)` 24 lines later. Both now carry the
     phase and name `OME-1258`.

  4. **No test, by design, and the ledger said so upfront.** No production statement changed, so
     no test could demand one and no prior test could move. The bar was the gates staying
     exactly where they were, which they did.

  5. **Two of the six were fixed before this unit existed** — the `OME-822` Linear Scope bullet
     and its Acceptance bullet 1, which was ticked ✅ for a behaviour the code does the opposite
     of. Closing `OME-822` would have frozen a false "delivered" into the record, so that one was
     not queued behind a PR.
