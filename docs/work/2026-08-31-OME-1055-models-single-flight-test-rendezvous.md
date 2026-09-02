---
ticket: OME-1055
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-08-31
finished: 2026-08-31
---

# OME-1055 — Make the /v1/models single-flight concurrency test deterministic

## Intent

`test_concurrent_callers_share_one_upstream_fetch_chain_and_all_get_200` fails
intermittently in CI on Python 3.12 with `assert 4 == 6`, which intermittently blocks every
aigateway PR (first observed on PR #782 / OME-1044, whose diff touches none of the code
under test). The failing assertion is the test's own self-check that six callers overlapped,
not the product invariant — `assert http.dialed == [LIVE_MODELS_URL]` passes on every run.
The overlap is currently arranged by a fixed `await asyncio.sleep(0.2)` racing six thread
startups; on a loaded runner two threads land late, get served by the completed refresh, and
never overlap. This unit replaces the timed window with an explicit rendezvous so the overlap
is a fact rather than a race, keeping both existing assertions intact.

Introduced by `cc9deb4a` / PR #739 (OME-972), merged 2026-08-27; latent through ~16 runs.

## Planned changes

- `apps/aigateway/tests/unit/core/test_models_route_live_catalog.py` — MODIFY
  `test_concurrent_callers_share_one_upstream_fetch_chain_and_all_get_200` only:
  - add a module-level `_RENDEZVOUS_TIMEOUT_S` constant
  - add an `asyncio.Event` the counting wrapper sets once `depth["now"]` reaches `callers`
  - `_SlowClient.get` awaits that event under `asyncio.wait_for` instead of
    `asyncio.sleep(0.2)`; a timeout records a flag rather than raising inside the app stack
  - add an assertion on that flag, ahead of the peak assertion, so a genuine failure to
    overlap reports itself instead of surfacing as `4 == 6`
  - `WHY:` anchor recording why a rendezvous replaces a timed fetch

No production code changes. No other test touched.

## Test plan

This unit's deliverable IS a test change, so the RED/GREEN evidence is behavioural rather
than a new test file:

- **RED (reproduce the defect's mechanism):** force the failure deterministically by making
  the rendezvous unreachable — set the barrier target above the caller count — and confirm
  the new timeout assertion fires with its diagnostic message rather than `assert N == 6`.
  This proves the new guard detects a real overlap failure instead of masking it.
- **GREEN:** the test passes with the rendezvous in place.
- **Determinism:** run the target test in a loop (>=25 iterations) and the whole test file,
  with coverage on, and additionally under CPU restriction (`taskset -c 0,1`) — the
  condition the fixed sleep was sensitive to.
- **No weakening:** both original assertions (`http.dialed == [LIVE_MODELS_URL]` and
  `depth["peak"] == callers`) remain present and unmodified in meaning.
- **Full suite:** the whole aigateway suite stays green (the test shares the app fixture with
  4107 other tests).

## Acceptance

- The fake upstream fetch completes only after all `callers` callers have entered the catalog.
- Both original assertions still asserted; neither relaxed.
- A failure to rendezvous fails loudly with a diagnostic, bounded by a timeout — never hangs.
- Target test green repeatedly (>=25 consecutive runs) under coverage, including pinned CPUs.
- `uv run .claude/scripts/run_gates.py aigateway --skip-append-only` all green.
- CI green on both 3.12 and 3.13.

## Outcome

- **Actual files:** as planned — only
  `apps/aigateway/tests/unit/core/test_models_route_live_catalog.py` (+29 / -4), plus this
  ledger and the `docs/tasks/` mirror. No production code touched.

- **Commits:**
  - `9f2a2d4d` — test(aigateway): make the /v1/models single-flight test deterministic

- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --skip-append-only` — ALL GREEN.
  ruff check / ruff format --check / pyright / check_no_enterprise.py /
  `pytest --cov=aigateway --cov-fail-under=80` (4108 passed). File 449 lines, under the 450 rule.

- **Verification evidence:**

  | Probe | Design | Result |
  |---|---|---|
  | RED-1 — upstream fetch made instant | original | `assert 1 == 6` — reproduces the CI signature |
  | RED-2 — rendezvous made unreachable | fixed | new guard fires with its diagnostic, bounded by the timeout |
  | Stagger — callers arrive 0.15s apart | original | `assert 2 == 6` |
  | Stagger — callers arrive 0.15s apart | **fixed** | **pass** |
  | 30x loop, coverage on, every 2nd run pinned to 2 CPUs | fixed | 30/30 pass |

  RED-1 also justifies keeping the assertion the fix repairs: with ZERO overlap,
  `http.dialed == [LIVE_MODELS_URL]` still passed. The peak-depth assertion is the only
  thing separating "single-flight works" from "a serialized server hit a warm cache".

- **Deviations:**
  1. **Append-only gate bypassed (rule 5).** The unit's deliverable IS a change to a prior
     test, so the gate necessarily fires; adding a new file would have left the flake in
     place. Owner approved the specific edit; ran with `--skip-append-only`. Verified the
     gate does flag it when the flag is omitted:
     `M tests/unit/core/test_models_route_live_catalog.py (removed/changed old line(s)
     [330, 336, 341, 379] …)`. No other gate was skipped or weakened.
  2. **RED/GREEN inverted in form, not in substance.** With no production code to drive,
     RED was executed as a deterministic reproduction of the defect (RED-1) plus a
     verification that the new guard catches a real overlap failure (RED-2), rather than as
     a new failing test file. Declared in the Test plan up front.
  3. **Diagnostic message reworded after RED-2.** The first version read "only 6 of 6 callers
     ever overlapped" under the probe — self-contradictory, because the probe timed out while
     the overlap genuinely happened. Changed to "rendezvous timed out — peak overlap N of M",
     which is accurate in every case. RED-2 earned its keep here.
  4. **Comments trimmed twice to satisfy the 450-line rule** (459 -> 453 -> 449). One comment
     was deleted outright under rule 12 for restating the code beneath it.

- **Residual uncertainty:** the original failure was never reproduced under true CI
  conditions — 27 isolated local runs of the old test passed, and CI runs it inside the full
  4107-test suite. The mechanism is inferred from the assertion signature and the structure
  of the test, both of which the probes reproduce exactly. CI on both 3.12 and 3.13 is the
  real verdict.

- **Follow-up noted, not actioned:** the CI logs also show six `RuntimeError: Event loop is
  closed` lines at teardown of this test. Pre-existing, unrelated to the peak assertion, and
  out of scope here.
