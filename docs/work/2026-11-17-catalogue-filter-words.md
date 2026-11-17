---
ticket: OME-1957
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-11-17
finished: 2026-11-17
---

# catalogue-filter-words — match each word in the catalogue filter, and correct the public docs

## Intent

The notebook filter of `sf.models.list()` matches one string, so the query `claude 5.5` finds nothing. The filter must match each word of the query. The public docs must describe the curated list and the search. Spec and plan are in the worktree `models-list-live-catalog`: `docs/spec/2026-11-17-OME-1955-refresh-curated-model-list.md` §5.3 and §5.5, and `docs/plan/2026-11-17-OME-1955-refresh-curated-model-list.md` §4 (PR C).

## Planned changes

- `packages/screamingface/src/screamingface/_ui/catalog.py`
- `packages/screamingface/tests/test_rich_display.py (new tests at the end)`
- `packages/screamingface/CHANGELOG.md`
- `public-docs/src/pages/sf-client/guides/ModelsPage.vue`
- `public-docs/src/pages/sf-client/api/ModelsCatalogPage.vue`

## Test plan

- The four tests of the plan, §4 C1, written first. No current test changes.

## Acceptance

- The query `5.5 openrouter` shows only the matching model. The `screamingface` gates and the public docs lint and build are green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `packages/screamingface/src/screamingface/_ui/catalog.py`, `packages/screamingface/tests/test_rich_display.py`, `packages/screamingface/CHANGELOG.md`, `public-docs/src/pages/sf-client/guides/ModelsPage.vue`, `public-docs/src/pages/sf-client/api/ModelsCatalogPage.vue`. The ledger file `docs/work/2026-11-17-catalogue-filter-words.md` is also new and untracked. The `git diff --stat` matched this list (5 files, 97 insertions, 12 deletions).
- **Commits:** `d370de35d` feat(screamingface): match each word in the catalogue filter; `c6b81dbdb` docs(public-docs): describe the curated model list and the search. The docs commit follows them.
- **Gates:**
  - `uv run .claude/scripts/run_gates.py screamingface` (worktree root): PASS. Output ends with `ALL GATES GREEN`.
  - `uv run --extra notebook pytest tests/test_rich_display.py -q -rs` (packages/screamingface): PASS. 23 passed, 0 skipped. The `-rs` skip list is empty, so new filter tests ran, not skipped.
  - `cd public-docs && npm ci && npx oxlint . && npx eslint . && npm run build`: PASS. Every command exited 0, and the build reported `built in 1.42s`.
- **Deviations:**
  - (a) The plan query `5.5 openrouter` is already a substring of the current search text `openrouter/openai/gpt-5.5 openrouter`. So the first test also checks the reverse order `openrouter 5.5` (spec §9, test 10). That query failed before the change.
  - (b) The tests for `claude openrouter` and for a query of spaces only passed before the change. The widget strips the query, and the old filter already found no match. They are guards for the new rule, so they could not fail first. The tests for `openrouter 5.5` and for the benchmark query `probe draco` failed first.
  - (c) The first new test has its WHY comment wrapped over two lines, because one line broke ruff E501.
  - (d) The C2 step edited the two `.vue` files, separately from the C1 step. Both files are in the expected list. No unexpected file changed, and no gate failed.
  - (e) One gate run failed with `Coverage failure: total of 61 is less than fail-under=95`. The cause was two `run_gates.py screamingface` runs at the same time in the same directory. They wrote the same `.coverage` data files, and one run was killed. The code did not cause it. The fix: delete the ignored `.coverage*` files in `packages/screamingface` and run the gates one time only. That run passed (`ALL GATES GREEN`). No code, test or gate changed.
  - (f) The design review gave two small fixes. The CHANGELOG entry now states only the matching rule; the spaces-only sentence is removed, because the old code already stripped the query. The ModelsPage.vue search paragraph now says that the filter box needs the `[notebook]` extra.
  - (g) Final check on 2026-11-17 after the review fixes: `uv run .claude/scripts/run_gates.py screamingface` gives ALL GATES GREEN, and `npx oxlint .`, `npx eslint .`, `npm run build` in `public-docs` pass. Review finding F3 is not applied: the sentence "A ModelInfo is one model route the configured engine can currently reach" in `ModelsCatalogPage.vue` is outside the lines that the plan names.
