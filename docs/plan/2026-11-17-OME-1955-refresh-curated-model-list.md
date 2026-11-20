# Plan — refresh the curated model list, newest first, search with words (OME-1955)

Spec: `docs/spec/2026-11-17-OME-1955-refresh-curated-model-list.md`.
Status: draft. Code starts only after the owner approves this plan in plain words.

## 0. Assumptions

The owner approved the 49 models (spec §11, Q1) on 2026-11-17. The other questions have no answer
at this time. This plan uses the recommendations of the spec. If one is wrong, the plan changes.

| Question | Assumption |
|---|---|
| Q2 | The seeds that are not in the OpenRouter catalogue stay in the list. |
| Q3 | Units 2 (newest first) and 4 (the command) are in scope. |
| Q4 | `OME-1955` gets the label `aigateway` and a new title when PR A opens. |
| Q5 | The direct provider lists are not in scope. |
| Q6 | The public docs change is in the `client-sf` ticket of PR C. |

## 1. Three PRs

The PRs change different files, so their order is free. Each PR has its own worktree from
`origin/main`.

| PR | Units of the spec | Ticket | Worktree and branch | Gates |
|---|---|---|---|---|
| A | 4 (the command), then 1 (the list) | `OME-1955` | This worktree. Rename the branch to `OME-1955-refresh-curated-model-list` when the PR opens. | `aigateway`, `screamingface-engine` |
| B | 2 (newest first) | A new leaf with the label `aigateway`, filed when the PR opens | `.claude/worktrees/openrouter-newest-first` | `aigateway` |
| C | 3 (search with words) and 5 (public docs) | A new leaf with the label `client-sf`, filed when the PR opens | `.claude/worktrees/catalogue-filter-words` | `screamingface`, public docs lint and build |

The gate command for a stack is `uv run .claude/scripts/run_gates.py <stack>`
(`.claude/sdlc.local.md`). Before the Engine gates, run `uv sync --dev` in
`apps/screamingface-engine`. The public docs have no stack card: the checks are those of
`.github/workflows/public-docs-tests.yml` (`npm ci`, `npx oxlint .`, `npx eslint .`,
`npm run build`, in `public-docs`).

## 2. PR A — the command and the list

### A1. The command (unit 4). Tests first.

New files:

- `apps/aigateway/scripts/check_openrouter_seeds.py`
- `apps/aigateway/tests/unit/openrouter/test_check_openrouter_seeds.py`

Example files to follow: `apps/aigateway/scripts/verify_openrouter_credits.py` for the script, and
`apps/aigateway/tests/unit/credits/test_owner_verification.py` for a test that loads a script
with `runpy.run_path`.

Shapes:

```python
CATALOG_URL = "https://openrouter.ai/api/v1/models?output_modalities=text"
TRACKED_AUTHORS: frozenset[str]  # the 14 names of the spec, §5.1

@dataclass(frozen=True, slots=True)
class SeedReport:
    dead: tuple[str, ...]             # seeds that are not in the catalogue, in seed order
    new: tuple[tuple[str, int], ...]  # (gateway id, created), newest first

def seed_report(rows: Sequence[Mapping[str, object]], seeds: Sequence[str]) -> SeedReport: ...
def main() -> None: ...  # GET CATALOG_URL with httpx, call seed_report, print the two parts
```

Rules:

- A seed is dead if its id without the `openrouter/` prefix is not an id in `rows`.
- A row is new if all of these are true: the id is a string that passes
  `is_valid_upstream_model_id` and has no `:` and no `~`; the author is in `TRACKED_AUTHORS`;
  `architecture.output_modalities` is exactly `["text"]`; `created` is an `int` and not a
  `bool`; the id is not a seed; and `created` is larger than the largest `created` of the seeds
  that are in `rows`.
- A row that is not a mapping, or that has no string id, is ignored.
- The seeds come from `OpenRouterPluginSettings().default_models`.
- The script does not change a file and always exits with 0 after a report.

Tests (no network; `main` gets a patched `httpx.get`):

1. A seed that is not in the rows is in `dead`, in seed order. A seed with a colon is tested also.
2. A new row of a tracked author is in `new`, newest first.
3. These rows are not in `new`: a different author, a colon id, a `~` id, an output of text and
   video, a row older than the newest seed, a row that is a seed, a row with no `created`, a row
   with `created: true`, a row that is not a mapping.
4. `main` prints the two parts.

### A2. The list (unit 1). Tests first.

Test edits (RED):

- `apps/aigateway/tests/unit/openrouter/test_openrouter_settings.py`: add the 49 ids at the end of
  `_SEEDS`, after `"openrouter/z-ai/glm-5.3-flash"`, with a comment that names `OME-1955`.
- `apps/screamingface-engine/tests/unit/test_model_seeds.py:35-36`: 117 becomes 166, and 88
  becomes 137. The value 29 stays. Add a comment line with the date and `OME-1955`, as the lines
  above it do.
- Add one new test in `test_model_seeds.py`: `openrouter/anthropic/claude-opus-5.5` and
  `openrouter/deepseek/deepseek-v4.1-flash-1017` are in `BUILTIN_MODEL_WORLD.routable`.

Code edits (GREEN):

- `apps/aigateway/src/aigateway/plugins/openrouter_provider/settings.py`: add the 49 ids at the
  end of the list in `_default_model_slugs()`, after `"openrouter/z-ai/glm-5.3-flash"`. The
  comment gives `OME-1955` and the date on which each id was in the live catalogue.
- `apps/screamingface-engine/src/screamingface_engine/world/models/seeds/openrouter.py`: add the
  same 49 ids, in the same order, at the end of `slugs`.

The 49 ids, in file order:

```python
    "openrouter/anthropic/claude-fable-5.2",
    "openrouter/anthropic/claude-opus-5.5",
    "openrouter/anthropic/claude-sonnet-5.5",
    "openrouter/anthropic/claude-haiku-5.5",
    "openrouter/anthropic/claude-fable-5.1",
    "openrouter/openai/gpt-6.2-astra",
    "openrouter/openai/gpt-6.2-astra-pro",
    "openrouter/openai/gpt-6.2-sol",
    "openrouter/openai/gpt-6.2-sol-pro",
    "openrouter/openai/gpt-6.1-terra",
    "openrouter/openai/gpt-6.1-terra-pro",
    "openrouter/openai/gpt-6.1-sol",
    "openrouter/openai/gpt-6.1-sol-pro",
    "openrouter/openai/gpt-6-luna",
    "openrouter/openai/gpt-6-luna-pro",
    "openrouter/openai/gpt-6-sol",
    "openrouter/openai/gpt-6-sol-pro",
    "openrouter/openai/gpt-6-astra",
    "openrouter/openai/gpt-6-astra-pro",
    "openrouter/google/gemini-4-hydrogen",
    "openrouter/google/gemini-4-carbon",
    "openrouter/google/gemini-4-argon",
    "openrouter/google/gemini-3.8-flash",
    "openrouter/google/gemini-3.7-flash",
    "openrouter/qwen/qwen4-max",
    "openrouter/qwen/qwen3.8-max-prime",
    "openrouter/qwen/qwen3.8-omni-flash",
    "openrouter/qwen/qwen3.8-max-0902",
    "openrouter/qwen/qwen3.8-flash",
    "openrouter/qwen/qwen3.8-27b",
    "openrouter/mistralai/mistral-large-4-0",
    "openrouter/deepseek/deepseek-v4.1-flash-1017",
    "openrouter/deepseek/deepseek-v4.1-flash",
    "openrouter/x-ai/grok-4.7",
    "openrouter/meta/muse-ember",
    "openrouter/meta/muse-spark-open",
    "openrouter/meta/muse-wonder",
    "openrouter/meta/muse-spark-1.3",
    "openrouter/moonshotai/kimi-k3.1-pro",
    "openrouter/z-ai/glm-5.3-prime",
    "openrouter/z-ai/glm-5.3-flashx",
    "openrouter/z-ai/glm-5.3",
    "openrouter/tencent/hy4-flash",
    "openrouter/tencent/hy4",
    "openrouter/minimax/minimax-m3.1-flash",
    "openrouter/xiaomi/mimo-v2.6-pro",
    "openrouter/xiaomi/mimo-v2.6-flash",
    "openrouter/xiaomi/mimo-v2.6-pro-ultraspeed",
    "openrouter/stepfun/step-5-preview",
```

Do not change the order of the current entries, and do not remove an entry.

Verification:

1. In `apps/screamingface-engine`:
   `uv run pytest tests/unit/test_declared_models_match_aigateway.py tests/unit/test_model_seeds.py -q`.
   The first test must pass with no edit.
2. In `apps/aigateway`: `uv run python scripts/check_openrouter_seeds.py` (this uses the network).
   The `dead` part must contain only the four seeds of the spec, Appendix A.5. If one of the 49
   ids is there, remove that id from the three lists, record it in the ledger, and tell the owner.
3. Record the output of the script in the ledger.

### A3. The approval for the two test edits

The gate runner refuses an edit inside a current test or a current module-level list
(`.claude/scripts/run_gates.py`, `append_only_check`). The edits of A2 to `_SEEDS` and to the
counts are such edits. The repo procedure is a manifest, as commit `8202894f8` did with
`.claude/test-change-approvals/OME-1478.json`.

- New file: `.claude/test-change-approvals/OME-1955.json`, with the fields of that example:
  `issue`, `branch`, `approver`, `date`, `scope`, `reason`, `files`.
- `branch` is the final branch name. Thus write the manifest after the branch rename.
- For each of the two test files: `base_blob` is `git rev-parse origin/main:<path>`, and
  `approved_blob` is `git hash-object <path>` of the final file.
- **Stop here for the owner.** The manifest names an approver. The owner must say who approves
  these two edits.

### A4. Gates, commit, PR

1. `uv run .claude/scripts/run_gates.py aigateway`, then
   `uv run .claude/scripts/run_gates.py screamingface-engine`.
2. Fill the "Outcome" part of `docs/work/2026-11-17-OME-1955-refresh-curated-model-list.md`.
3. Commits (conventional, no `Co-Authored-By`):
   - `chore(aigateway): add a command that compares the OpenRouter seeds with the catalogue`
   - `feat(aigateway): add 49 OpenRouter models to the curated list` (the gateway list, the
     Engine copy, the tests, and the manifest in one commit, because the equality test needs
     the two lists together)
   - `docs: spec, plan, ledger and mirror for OME-1955`
4. Before the PR opens: ask the owner to confirm. Then update `OME-1955` (title, text, label),
   rename the branch, write the manifest, push, and open the PR with `Refs: OME-1955`.
5. Give the owner the run URL and the checks URL. Do not poll CI. When all checks are green,
   merge with `gh pr merge --squash` (never `--auto`, never `--admin`).
6. Close: the close comment on the ticket, and the mirror status.

## 3. PR B — the newest OpenRouter models first (unit 2)

Files:

- `apps/aigateway/src/aigateway/plugins/openrouter_provider/live_models.py`
- `apps/aigateway/src/aigateway/plugins/openrouter_provider/plugin.py`
- New: `apps/aigateway/tests/unit/openrouter/test_live_models_newest_first.py`

Example to follow: the input-types evidence of `OME-1537`
(`parse_page_input_modalities`, `live_models.py:154-178`, and
`tests/unit/openrouter/test_openrouter_input_modalities.py` for the test helpers `_row`, `_page`,
`_RoutingClient`).

Changes:

1. New function `parse_page_created(payload: Any) -> dict[str, int]` in `live_models.py`. It
   never raises. It keeps the `created` of a row only if the value is an `int`, is not a
   `bool`, and is larger than 0.
2. `LiveCatalog` gets a field `created: Mapping[str, int]` with an empty default.
3. `fetch_live_model_catalog` collects `parse_page_created(payload)` for each page, in the same
   place as the input-types evidence, and returns it in `LiveCatalog`.
4. `live_listing_entries` gets a keyword parameter `created: Mapping[str, int] | None = None`.
   The discovered ids are sorted with the key
   `(id has no date, -date, id)`. Operator entries stay first, as today.
5. `plugin.py`, `discover_live_models`: pass `created=catalog.created`.
6. Update the docstring of `live_listing_entries`, which says that the discovered ids are in
   sorted order.

Do not change `parse_catalog_page`, `publishable_upstream_ids`, the row content, or a current
test. With no dates, the new key gives the alphabetical order of today, so the current tests
pass with no edit.

Tests (new file, written first):

1. `parse_page_created` keeps a good value and drops a missing value, a `bool`, a string, a
   negative number, a row that is not a mapping, and a payload that is not a mapping.
2. `fetch_live_model_catalog` collects the dates from two pages.
3. With dates, `live_listing_entries` gives the discovered ids newest first.
4. Two ids with the same date are in the order of the id.
5. An id with no date comes after all the ids with a date.
6. With no dates, the order is the alphabetical order (the behaviour of today).
7. Operator entries are first, in their configured order.
8. `discover_live_models` of the plugin gives the newest id first, from catalogue rows with
   dates.

Then: `uv run .claude/scripts/run_gates.py aigateway`, the ledger, the commit
`feat(aigateway): list the newest OpenRouter models first`, and the PR steps of A4 (items 4 to 6)
with the new ticket.

## 4. PR C — search with words, and the public docs (units 3 and 5)

### C1. The filter (unit 3)

File: `packages/screamingface/src/screamingface/_ui/catalog.py:120-121`.

```python
def _matches(self, value: T, query: str) -> bool:
    text = self._search_text(value).casefold()
    return all(word in text for word in query.split())
```

An empty query has no words, so all the models match, as today.

Tests (new functions at the end of `packages/screamingface/tests/test_rich_display.py`; follow
`test_catalogue_notebook_search_filters_presentation_not_values`, lines 113-135):

1. The query `5.5 openrouter` shows `openrouter/openai/gpt-5.5` and not
   `anthropic/claude-opus-4.8`.
2. The query `claude openrouter` shows "No models match."
3. A query of spaces only shows the two models.
4. The benchmark catalogue filters with two words in the same way.

Do not change a current test. `tests/public_surface_snapshot.json` must pass with no edit.

Add one line to `packages/screamingface/CHANGELOG.md`, under "Unreleased": the catalogue filter
matches each word of the query.

### C2. The public docs (unit 5)

`public-docs/src/pages/sf-client/guides/ModelsPage.vue`:

- Line 36: remove "110 entries across 6 providers on a local engine". Keep the "…" line with a
  text that gives no number.
- Lines 176-179: remove the sentence "The hosted engine lists more routes than a local one (112
  against 110)."
- Lines 185-187: replace the "The catalogue is fixed" block. The new block says: the catalogue is
  curated; the team adds the new models of the large labs; an OpenRouter model that is not in the
  list still runs when you name its route `openrouter/<author>/<model>` and you have an
  OpenRouter connection.
- After that block, add a short part on the search: the filter box of the notebook, the search
  with more than one word, and the line `[m for m in sf.models.list() if "claude" in m.id]` for
  a script.

`public-docs/src/pages/sf-client/api/ModelsCatalogPage.vue`:

- Lines 157-160 and 174: "every route the configured engine can currently reach" and "every
  addressable route" become "the curated routes of the configured engine".

Checks in `public-docs`: `npm ci`, `npx oxlint .`, `npx eslint .`, `npm run build`. Then look
at the two pages with `npm run dev`.

Then: `uv run .claude/scripts/run_gates.py screamingface`, the ledger, the commits
`feat(screamingface): match each word in the catalogue filter` and
`docs(public-docs): describe the curated model list and the search`, and the PR steps of A4
(items 4 to 6) with the new ticket.

## 5. Who does the work

| Step | Who | Why |
|---|---|---|
| A1, the command | An implementer agent with the spec of A1, then a design review | The task is fully specified |
| A2, the list | A mechanic agent, then a check in the main session | The same pattern in four files |
| B | An implementer agent with the spec of §3, then a design review | The task is fully specified |
| C1 | The main session | Three lines |
| C2 | The main session | The text needs judgement |

## 6. Stop conditions

- One of the 49 ids is not in the catalogue on the day of PR A (A2, verification).
- The gate runner refuses a test file that is not in the manifest.
- A current test of PR B or PR C must change. The design says that none must change.
- A gate is red for a reason that is not in the changed files.

## 7. Open items for the owner

1. The approver of the two test edits (A3).
2. The parent epic of the PR C ticket. `OME-1315` is about the gateway, and PR C is a Client and
   docs change.
3. The answers to Q2 to Q6 of the spec, if an assumption of §0 is wrong.
