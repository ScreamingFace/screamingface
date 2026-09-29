---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done
started: 2026-09-29
finished: 2026-09-29
---

# revert-inspect-pins — put inspect back on the versions the published exams were built with

## Intent

Dependabot's #1026 (`36038f7ed`) bumped the engine's exact pins from `inspect-ai 0.3.263` /
`inspect-evals 0.20.0` to `0.3.266` / `0.21.0`. Every imported board hashes those two versions
into its revision, so all 18 published revisions moved: gsm8k, mmlu, FrontierScience and the
rest are now, by our own rule, different exams. The inspect CI lane reported "18 failed, 478
passed", but the job stayed green: the step pipes `pytest | tee` without `pipefail`, so it takes
`tee`'s exit code. This unit reverts only the two inspect pins, and holds both packages in
Dependabot until bumps can be verified (the bump-verification ticket, filed with this PR).

## Planned changes

- `apps/screamingface-engine/pyproject.toml`: `inspect-ai==0.3.263`, `inspect-evals==0.20.0`.
  Everything else #1026 bumped stays, `datasets==5.0.1` included.
- `apps/screamingface-engine/uv.lock`: relocked. The diff is the exact reverse of #1026's
  inspect part: the two versions plus `aioboto3` / `aiofiles`, which 0.3.263 depends on.
- `.github/dependabot.yml`: `ignore` inspect-ai and inspect-evals for the engine directory,
  with the reason and the removal trigger.

## Test plan

- No new test: `test_published_revisions` is the pin. It fails on main today (18) and must pass
  after the revert.

## Acceptance

- `uv run --extra inspect pytest tests/unit/inspect` fully green; `pinned_inspect_packages()`
  reports 0.3.263 / 0.20.0.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** `revert(screamingface-engine): pin inspect back to the versions the published exams use`.
- **Gates:** `tests/unit/inspect` 496 passed (main: 18 failed, 478 passed); the pre-push gate
  runs the full engine suite. `dependabot.yml` parses.
- **Deviations:** none. The CI `pipefail` gap is left for the bump-verification ticket, because
  it's CI tooling (an owner decision).
