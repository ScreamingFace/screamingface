---
ticket: OME-2014
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-24
finished:
---

# engine-gateway-fixture-paths — run the Engine suite on every repo file an Engine test reads

## Intent

`screamingface-engine-tests.yml` runs only when its `paths:` filters match a change. Engine tests
also read files outside `apps/screamingface-engine` and `packages/url4`: Gateway fixtures and
source, SDK source and metadata, a scoreboard schema, the layering script and the SDLC card. Only
some of those paths are in the filters. A change to any other one alone does not run the Engine
suite, so a Gateway, SDK or scoreboard change that breaks an Engine contract twin merges green and
the break surfaces on the next unrelated Engine change. Known case:
`tests/unit/test_gateway_error_relay_contract.py:29` reads
`apps/aigateway/tests/fixtures/provider_error_relay/`, which no filter matches.

This unit adds every such path to both triggers' filters and a guard test in the Engine suite
that fails when an Engine test reads a repo path outside the filters, so the list cannot drift
again unnoticed. Owner decision in chat, 2026-11-24: the full list plus the guard.

The full list includes `packages/screamingface/src/**` (three Engine tests run the SDK package
in a subprocess) and `.github/workflows/*.yml` (one test checks every workflow that builds the
benchmark image). Over the four weeks before this unit, 45 SDK commits and 30 workflow commits
on `main` touched neither the Engine nor url4, and each would now run the whole workflow,
including the 30 to 45 minute image build. Second owner decision, 2026-11-24: add every path,
and run the `image`, `conformance` and `chart` jobs only when the change touches the Engine,
url4 or the workflow itself. A change outside them runs the `test` job, which is where the
contract twins live. The images build only from `packages/url4` and `apps/screamingface-engine`.

Base: `origin/main` `744f3b89b`.

## Planned changes

- `apps/screamingface-engine/tests/unit/test_engine_ci_path_filters.py` (new): the guard and a
  synthetic self-test of its path resolver.
- `.github/workflows/screamingface-engine-tests.yml`: the missing paths in the `push` and
  `pull_request` `paths:` lists, each with a comment naming the test that reads it, as the
  existing entries do. A new `changes` job classifies the change, and `image`, `conformance`
  and `chart` depend on it and run only for an Engine change. A manual run, an empty diff or a
  base git cannot find counts as an Engine change. A new branch's first push, whose base is all
  zeros, is compared with where it left the default branch.
- `apps/screamingface-engine/tests/unit/test_engine_ci_heavy_jobs.py` (new): pins the gating,
  and runs the classifier's own shell script against a throwaway git repository.
- This ledger; at PR-open, the Linear leaf under `OME-1306` and its `docs/tasks/` mirror.

## Test plan

- RED: the guard on the current workflow fails and names every uncovered path, at least
  `apps/aigateway/tests/fixtures/provider_error_relay`.
- The guard's resolver, on synthetic sources: a repo-relative string literal, a literal joined to
  a repo-root expression (`Path(__file__).resolve().parents[k]`, `.parent`), a name bound to such
  an expression and joined later, and an Engine-local path, which is not reported.
- The guard also requires the `push` and `pull_request` lists to be equal.
- Heavy jobs, RED first: `image`, `conformance` and `chart` need `changes` and run only on its
  `engine` output; `test` runs for every change; every build-context path the Engine
  Dockerfiles copy, and the workflow itself, is an Engine change; an SDK, Gateway or other
  workflow path is not. The classifier script, run against a throwaway repository: an SDK-only
  diff gives `false`; an Engine diff, a manual run, an empty diff and an all-zero base with no
  fork point give `true`; a new branch's all-zero base is compared with its fork point.
- GREEN: with the filters extended and the jobs gated, both tests pass; no prior test changes.

## Acceptance

- The guard passes on the final workflow and fails when any one added entry is removed.
- The heavy-job test fails when any one heavy job loses its `if`.
- `run_gates.py screamingface-engine --base origin/main` all green on Python 3.12 and 3.13, the
  append-only check included.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
  - `.github/workflows/screamingface-engine-tests.yml`: 103 added lines, no removed line. The
    added paths appear in both triggers. The `changes` job was added, and `image`,
    `conformance` and `chart` were gated on it.
  - `apps/screamingface-engine/tests/unit/test_engine_ci_path_filters.py` (new, 365 lines).
  - `apps/screamingface-engine/tests/unit/test_engine_ci_heavy_jobs.py` (new, 195 lines).
  - This ledger.
- **Commits:** `a99e099ae` `ci(screamingface-engine): run the Engine suite on every repo file
  an Engine test reads`, then the commit that files `OME-2014` and adds its mirror. The PR and
  its merge are recorded at close-out.
- **Gates:** `run_gates.py screamingface-engine --base origin/main` is all green on Python
  3.13.11 and 3.12.9. That covers the append-only check, ruff check, ruff format, pyright,
  layering, and the full pytest suite with coverage. The two new modules give 26 passed.
- **The tests bite:**
  - Guard: each check below removes one item from the final workflow, and the guard fails each
    time. The removed items are `packages/screamingface/src/**`,
    `apps/aigateway/tests/fixtures/provider_error_relay/**`,
    `apps/aigateway/src/aigateway/plugins/*/models.py`, `*/*/justfile`,
    `packages/screamingface/examples/*.ipynb`, `apps/aigateway/uv.lock` and
    `.claude/scripts/check_layering.py`.
  - Heavy-job test:
    - It fails when the `image` job loses its `if`.
    - It fails when the classifier's empty-diff guard (`-s`) is dropped.
    - It fails when the all-zero-base fork-point fallback is removed. The SDK-only new branch
      then reads as an Engine change.
- **Deviations:**
  - The scope grew with the second owner decision, which added the `changes` job, the gating
    and `test_engine_ci_heavy_jobs.py`.
  - The fork-point fallback came out of a design review after the first heavy-job tests. It was
    written into the workflow before its test. Its RED was then shown by removing it, as
    listed above.
  - No workflow linter was run on the YAML. The tests parse the workflow, and they run the
    classifier script itself.
  - The branch's required-check list could not be read from here. A job skipped by its `if`
    reports success, so a skipped heavy job does not block a merge. The first SDK-only pull
    request after the merge should confirm this.
  - The first run of the removal checks used a pattern that never matched, so it removed
    nothing. Those checks were redone with an exact line removal, and the results above come
    from that rerun.
