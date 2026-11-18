---
ticket: OME-1947
stack: scoreboard
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-17
finished:
---

# scoreboard-copy-claims — the scoreboard claims the frozen copy of each Score (units B2 and B3)

## Intent

The scoreboard claims the frozen copy of a Score at submit, and it claims the copies of all stored Scores at each start. A submit whose copy the gateway does not hold sealed is refused. With no gateway URL, the scoreboard works as today.

Spec: `docs/spec/2026-11-16-frozen-copy-retention/`. Plan: `docs/plan/2026-11-17-frozen-copy-retention-stack-b.md` (owner approved 2026-11-17).

## Planned changes

Paths are under `apps/scoreboard/` unless they start with `.github/`.
- B2: `src/scoreboard/core/copy_claims.py` (new; port), `src/scoreboard/gateway_copy_claims.py` (new; adapter), `src/scoreboard/config.py`, `src/scoreboard/main.py`, `src/scoreboard/routes/copy_claim.py` (new), `src/scoreboard/routes/scores.py` (one call, two descriptions), chart values and ConfigMap, `.github/scripts/verify_chart_wiring.py`, `DEPLOYMENT.md`, chart `README.md`
- B2 tests: `tests/unit/test_copy_claims.py`, `tests/unit/test_submit_claims_copy.py` (new)
- B3: pass function and start task in `core/copy_claims.py`, `ScoreStore.scores_that_name_a_copy` in `scores/store.py`, lifespan in `main.py`, `src/scoreboard/claim_copies.py` (new)
- B3 tests: `tests/unit/test_claim_copies_cli.py`, `tests/unit/test_claim_pass_at_start.py` (new)
- No schema change.

## Test plan

RED first. Test ids of `prd/score-claim.md`.
- B2: K-8 (mapping fails closed), K-17 (settings pair), CH-1 to CH-3 (today's behaviour with no client), K-9 to K-16, K-23, K-24, K-26, K-35 (submit guard).
- B3: K-18 to K-22, K-27 (command), K-28 to K-34 (start task and lifespan; Q29: a database error also waits 10 minutes and tries again).
- Invariant protected: a Score is stored with a copy id only after the gateway confirmed a sealed, claimed copy; a gateway answer that is not exact counts as unavailable.

## Acceptance

- `run_gates.py scoreboard` all green (it needs a local Node).
- `python3 .github/scripts/verify_chart_wiring.py` green.
- No existing test is changed.
- An independent design review against the spec has no open major finding.

## Notes at start

- Owner order of 2026-11-17: both plans approved; build stacks B and C in parallel.
- The branch is cut from the stack A branch (commit a06fc9802), because pull request #1911 is not
  merged. After the merge of #1911, rebase the branch onto `origin/main`. The local gates use
  `--base` at the commit below this unit.
- The `tortoise-dev` companion skill is not installed on this machine. Code that touches the ORM
  follows the house pattern that the plan names.

## Outcome (fill at the end — required before COMMIT)

State on 2026-11-17: B2 is built, reviewed and committed on the branch
`OME-1947-scoreboard-copy-claims`. `status` stays `in_progress` until the pull request is merged.

### B2 (the claim at submit)

- **Actual files:** as planned, plus `tests/unit/test_copy_claims_wiring.py` (review finding 9:
  the lifespan, OpenAPI, `create_app` and K-26 tests are in their own file).
- **Commits:** `feat(scoreboard): claim the frozen copy of a score at submit (OME-1947)`.
- **Gates:** `uv run .claude/scripts/run_gates.py scoreboard --base a06fc9802` → ALL GATES GREEN.
  `verify_chart_wiring.py` → 148/148 checks passed.
- **Design review:** verdict ACCEPT-WITH-FIXES, 2 minor and 11 low findings, none major. 12 are
  fixed. Minor 1: the submit guard read `app.state.copy_claims` with a default, which accepts a
  submit with no claim if the attribute is missing; it now reads the attribute directly. Minor 2:
  four other routes share the 503 entry of the submit in the OpenAPI document; the claim text is
  now in an entry that only `POST /v1/scores` uses. Open, low: finding 13 (the log does not say
  which gateway answer gave `unavailable`; the spec does not ask for it).
- **Deviations:**
  - The 503 description of the submit is a separate entry (`_SUBMIT_503`), not new text in the
    shared entry (the plan, B2.5). The model stays `MessageErrorResponse` (Q28).
  - `create_app` sets its state in a helper `_attach_state`: the function was at the limit of 26
    statements.
  - The gateway URL setting also removes surrounding spaces (review finding 11).
  - The build workflow stopped at its second wave check because the check named a test file
    path that does not exist. The code was complete; the gates and the review ran by hand.
  - CH-1: `tests/unit/test_pinned_cache_lookup.py:181`. CH-2: the idempotency tests of
    `tests/unit/test_scores_routes.py`. CH-3: `tests/unit/test_submit_claims_copy.py`. No
    existing test is changed.
