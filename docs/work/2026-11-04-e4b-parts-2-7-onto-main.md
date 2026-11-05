---
ticket: OME-1652, OME-1653
stack: screamingface, screamingface-engine, aigateway, repo
status: in_progress
started: 2026-11-04
finished:
---

# e4b-parts-2-7-onto-main — land E4b parts 2 to 7 on main

## Intent

The E4b stack was #1409 (part 1) → #1460 (parts 2 and 3) → #1461 (parts 4 to 7 and the map →
select → reduce surface). #1409 merged into `main` on 2026-10-30 at 13:06 UTC. The repo does not
delete a branch at merge, so #1460 kept the #1409 branch as its base and merged into it at 13:27,
and #1461 merged into the #1460 branch at 13:28. Parts 2 to 7 never reached `main`, and the
0.1.10 package does not have them. This unit applies the same change onto `main` in one PR. The
owner chose one PR that reuses OME-1652 and OME-1653 on 2026-11-04.

## Planned changes

- Apply `69ea4cc15..122e76a35` (the tip of #1409 to the tip of #1461, as merged) onto `origin/main`
  at `00802ae3f`.
- Resolve the conflicts with main's later work (OME-1739 `cases=`, OME-1733/OME-1478 picture
  notebook, classification, gateway refusal) by keeping both sides.
- Point the OME-1652 and OME-1653 test-change manifests at this branch, with base blobs at
  `origin/main`.

## Test plan

- No new test. The gates of every touched stack run against `origin/main`.

## Acceptance

- `git diff origin/main` names the same files as `69ea4cc15..122e76a35`, except the renamed
  notebook 19 and its test.
- The gates of screamingface, screamingface-engine, aigateway and repo pass against `origin/main`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the 492 files of `69ea4cc15..122e76a35`. 7 files conflicted
  (`world/connector.py`, `CHANGELOG.md`, `README.md`, `build_notebooks.py`, `__init__.py`,
  `_scoreboard/leaderboards.py`, `public_surface_snapshot.json`); 17 files differ from the #1461
  tip because main changed them too.
- **Commits:** `0755523da` — feat(screamingface): land E4b parts 2 to 7 on main; the ledger commits.
- **Gates (local, base `origin/main`):** aigateway and repo ALL GATES GREEN. screamingface: the
  append-only check (every pinned test file approved), ruff, ruff format and pyright pass; pytest
  6594 passed, 1 failed — `test_member_usage_memory_does_not_grow_with_lazy_cases` (tracemalloc
  peak), which passes alone and in small parallel runs; a probe showed no retained growth, only
  pytest-xdist work-stealing allocations. screamingface-engine: ruff, ruff format and the layering
  check pass; pyright fails only in 4 untouched `tests/unit/inspect/` files because the local
  `uv run` installs inspect-ai (CI does not); the test suite went over the 20-minute local limit.
  The owner chose to let CI run the full suites.
- **Deviations:**
  - Main added `18_picture_benchmarks.ipynb`, so the E4b notebook is now
    `19_map_select_reduce.ipynb` and its test is `test_example_19_recipes.py`.
  - `world/connector.py`: with main's `_GatewayRefusal` and the E4b `logprobs_unsupported` rule,
    `_raise_for_status` went over the ruff complexity limits. The detail parsing moved to
    `_refusal_detail`; the behavior does not change.
  - The CHANGELOG keeps the E4b bullets first in Features (the part 4, 5 and 6 doc tests pin their
    positions); main's `cases=` bullet follows the parts 2 to 7 bullets.
