---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-09-30
finished: 2026-09-30
---

# e14-final-apps-screamingface-engine — count a failed grant call as a version miss (RP-X1)

## Intent

Finding RP-X1 (blocking, confirmed). A replay call that the version did not serve and that then
ends non-2xx on the live path (credential error, provider 4xx/5xx) is counted by no side: the
gateway sends no version header on an error response, and the engine raises in `_raise_for_status`
before `_report_version`. A benchmark that collects the failed call finishes with misses == 0, so
the SDK says coverage "complete" (RP-H5, ans:Q13). The connector must count a grant-carrying call
that ends non-2xx, other than `403 replay_grant_invalid`, as a version miss. The C12 rule in the
spec covers only 2xx and is amended to cover the non-2xx case.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/world/connector.py`: in `_fetch_completion`,
  report a version miss for a grant-carrying call whose final response is non-2xx (both the first
  post and the re-issue), before `_raise_for_status` raises. The rejected-grant 403 is not counted
  (it fails the run through `report_grant_rejection`).
- `apps/screamingface-engine/tests/integration/test_replay_failed_grant_calls.py` (new).
- `docs/spec/2026-09-29-e14-reproducible-submission/contracts.md`: amend C12 "A call with no
  version answer" to cover non-2xx outcomes.
- Not touched (other side of the contract): gateway header on error responses (optional in the
  finding), SDK, scoreboard.

## Test plan

- RED first: a grant call gets 500 / 401 / 404 / 429 (parametrised), the benchmark endpoint collects
  the failure and answers, the run completes, the closing frame shows `misses >= 1`.
- Mixed: one version hit, one failed call collected: hits == 1, misses == 1.
- A call that sent NO grant and fails non-2xx counts nothing (plain run byte-identical).
- The 403 `replay_grant_invalid` call still fails the run and is not counted as a miss (existing
  test `test_replay_grant_rejection_collected.py` stays green).
- Failed call counted once (no double count with the 2xx path).

## Acceptance

- The new tests pass; all prior engine tests are unmodified and green; all card gates green.
- C12 text in contracts.md covers non-2xx.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** connector.py (new `_raise_for_status_counting_miss`, used at both `_fetch_completion` raise sites), tests/integration/test_replay_failed_grant_calls.py (new), contracts.md (C12 amended), this ledger. As planned.
- **Commits:** see `git log` on branch final/apps-screamingface-engine (fix(engine): count a failed grant call as a version miss).
- **Gates:** `run_gates.py screamingface-engine`: ALL GATES GREEN (append-only, ruff, format, pyright, layering, pytest with coverage).
- **Deviations:** none. Left alone: a transport failure with no HTTP response (RunnerRequestError after retries) is not counted, since the finding names non-2xx responses only; the optional gateway header on error responses is on the other side of the contract.
