---
ticket: OME-1878
stack: repo
status: done
started: 2026-11-11
finished: 2026-11-16
---

# ci-burst-ratelimit — a burst of merges to main costs fewer GITHUB_TOKEN calls and no longer fails Release Please, the Preview reconcile or the test lanes' report steps

## Intent

Every push to main starts Release Please, Preview images → Preview admission, CodeQL, dev builds
and the test lanes, all sharing the repo's `GITHUB_TOKEN` hourly limit. On 2026-11-11, 14
Dependabot merges in a row exhausted it: 60 runs failed with "API rate limit exceeded for
installation" (Release Please 22, Preview admission 12, CodeQL 6, test lanes ~5 — tests green,
the report step 403'd), and GitHub emailed the merging owner for each one. This unit makes such a
burst cost less and stops failing runs for bookkeeping that the next run redoes anyway.

## Planned changes

- `.github/workflows/release-please.yml` — `concurrency: {group: release-please, cancel-in-progress: false}`:
  a burst runs one at a time, and GitHub keeps only the newest pending run. Release Please
  reads main's HEAD and finds merged release PRs by label, so the newest run does every
  skipped run's work.
- The seven `*-tests.yml` lanes — `continue-on-error: true` on the `dorny/test-reporter` and
  `orgoro/coverage` steps. They only publish results; the test step still fails the job.
- `.github/scripts/preview_contract.py` — a 403/429 whose body says "rate limit" raises
  `RateLimited`. The `reconcile` command (cron every 5 min + Preview images completion)
  logs a `::warning::` and exits 0 on it, so the next run reconciles. Per-PR commands still fail
  hard: a PR status must never be silently skipped.

## Test plan

- `test_preview_contract.py` (append): a rate-limited `GET /pulls` makes `reconcile` warn and
  return; a non-rate-limit 403 still raises; a rate-limited per-PR command still raises.

## Acceptance

- The workflow YAML parses; the repo gates pass; preview tests are green.

## Scope (narrowed 2026-11-16, PR #1742 review by HupBaHa)

This unit lowers the burst's token use and stops three run kinds failing on it. It does NOT cover
the default CodeQL workflow: its Analyze jobs still upload SARIF through the installation token
and can fail with `API rate limit exceeded for installation` in a burst (6 of the 60 failures on
2026-11-11). Residual filed as `OME-1927` under `OME-733`.

## Spec/plan note

Config-and-guard unit sized below a separate `docs/spec` + `docs/plan`. The design is the
"Planned changes" above (owner chose "Repo fix PR" in session, 2026-11-11).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `.github/scripts/preview_contract.py`, `.github/scripts/test_preview_contract.py`, `.github/workflows/aigateway-tests.yml`, `.github/workflows/aigateway-ui-tests.yml`, `.github/workflows/release-please.yml`, `.github/workflows/report-intake-tests.yml`, `.github/workflows/scoreboard-tests.yml`, `.github/workflows/screamingface-engine-tests.yml`, `.github/workflows/screamingface-tests.yml`, `.github/workflows/url4-tests.yml`, `docs/tasks/2026-11-11-OME-1878-ci-burst-ratelimit.md`, `docs/work/2026-11-11-ci-burst-ratelimit.md`.
- **Commits:** squash `7acd3fa27` (#1742, merged 2026-11-16); this ledger close-out in the follow-up PR.
- **Gates:** repo gates green; `test_preview_contract.py` 23 passed (3 new); CI green on the
  main-refreshed head `58b566d6c`.
- **Deviations:** (1) #1742 was merged at 11:53Z with HupBaHa's CHANGES_REQUESTED (11:17Z)
  outstanding — the merge gated on CI only; both review points are closed by this follow-up
  (claim narrowed, ledger completed). (2) CodeQL is out of scope → `OME-1927`.
