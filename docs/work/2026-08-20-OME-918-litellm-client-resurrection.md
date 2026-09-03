---
ticket: OME-918
stack: aigateway
status: done
started: 2026-08-20
finished: 2026-08-20
---

# OME-918 — Observe shutdown on the captured client, not the self-healing property

## Intent

Dependabot #640 carries `litellm 1.97.0` (the rebase re-resolved past the 1.96.2 named in the
PR body). 1.97.0 turned `AsyncHTTPHandler.client` into a self-healing property that rebuilds
the client whenever it finds the stored one closed, with `__init__` setting `_owns_client =
True` and assigning `self._client` directly — bypassing the setter that would have cleared it.

Shutdown itself still works: capturing the client before `close()` shows `is_closed is True`
afterwards. What broke is two tests' *observation technique* — they re-read `handler.client`
after close, and that read is exactly what resurrects a new, open client.

## Planned changes

Test-only. No production code, no dependency change (the bump stays Dependabot's).

- `tests/unit/usage_accounting/test_handler.py` —
  `TestLifecycle::test_close_closes_the_underlying_client`
- `tests/unit/usage_accounting/test_lifespan_and_correlation.py` —
  `TestSharedHandlerLifecycle::test_lifespan_shutdown_closes_the_handler`

Both: bind the client once before `close()` and assert on that object.

## Test plan

**This modifies two PRIOR tests** — a `sdlc-python` rule 5 / Confidence-Gate decision. Raised
with the owner before any edit and approved: fix the observation, change nothing else.

The §9.12 invariant is *preserved, not weakened*. Before and after, the test still proves the
app-lifetime pool is genuinely released at shutdown; it just stops asking a property whose
getter has the side effect of undoing what is being measured.

- The two tests must FAIL on `litellm 1.97.0` before the edit (already reproduced locally on
  the PR head) and PASS after.
- They must also still pass on main's current `litellm 1.95.0`, so this lands safely ahead of
  the bump — same pattern as OME-912/OME-913.
- Full aigateway suite green, no other test touched.

## Acceptance

- Both tests pass under litellm 1.95.0 AND 1.97.0.
- `run_gates.py aigateway` green.
- Diff is test-only; #640 goes green on `@dependabot rebase`.

## Outcome

- **Actual files:** as planned — test-only. No production code, no dependency change.
  - `tests/unit/usage_accounting/test_handler.py`
  - `tests/unit/usage_accounting/test_lifespan_and_correlation.py`
- **Commits:** see below.
- **Gates:** `run_gates.py aigateway --skip-append-only` — ALL GATES GREEN (ruff check, ruff
  format --check, pyright, check_no_enterprise, pytest --cov-fail-under=80).
- **Evidence:**

  | litellm | before the edit | after the edit |
  |---|---|---|
  | 1.95.0 (main) | pass | **pass** |
  | 1.97.0 (PR #640) | **fail** ×2 | **pass** |

  Sanity check that the fix is not vacuous — on 1.97.0, re-reading the property after close
  still returns an open client, which is precisely what the old assertion did:
  `re-read handler.client.is_closed -> False`.

- **Deviations:**
  - **`--skip-append-only` was used.** The append-only gate fired exactly as designed and
    named both edits. Its purpose is to force a Confidence-Gate stop on any prior-test
    change; that stop happened before a single line was edited, the owner chose "fix the
    tests only", and the flag is the runner's own documented path for a sanctioned change.
    The skip is printed in the gate output, so it is visible rather than silent. Every other
    gate ran normally.
  - The §9.12 invariant is **preserved, not weakened**. Both tests still prove the
    app-lifetime pool is genuinely released at shutdown. What changed is only that they stop
    asking a property whose getter has the side effect of undoing what is being measured.
  - The blocking dependency is `litellm 1.97.0`, not the `1.96.2` named in #640's body —
    Dependabot re-resolved during the rebase. 1.96.2 does not contain the self-healing
    property. Worth remembering when diagnosing any rebased Dependabot PR.
  - Deliberately NOT done: blocking the resurrection itself (e.g. clearing `_owns_client` on
    close). Raised as decision 2 on the issue; the owner scoped this unit to the tests.
    A post-shutdown access can still silently open an unowned pool — recorded on OME-918.
