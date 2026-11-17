---
ticket: OME-1955
parent: OME-1315
status: draft  # owner review pending; open questions in §11
created: 2026-11-17
---

# Refresh the curated model list, show the newest models first, and improve the search (OME-1955)

Owner decisions, 2026-11-17:

1. The Engine listing rule does not change. The list stays curated. No switch and no author
   filter are added. (This replaces the earlier drafts of this spec.)
2. The curated list gets the new models of the large labs, and it gets a procedure that keeps it
   up to date.
3. If the cost is small: the list shows the newest models first, and the user can search it.
4. No model that is in the list today leaves the list.

## 1. Problem

- The curated list is out of date. On 2026-11-17, nine of the ten most used OpenRouter models
  were not in it, and its newest model was 82 days old (Appendix A).
- A grantee of the Ensembles & Routing grant found models that are not in `sf.models.list()` but
  that run correctly through their `openrouter/<author>/<model>` routes.
- The list has no useful order, and the public docs do not tell the user how to search it.
- The public docs say that a model that is not in the list cannot be used. That is not correct:
  the Engine admits an OpenRouter model on demand (`OME-878`).

## 2. Facts that the design uses

All paths are in this worktree (`origin/main` at `f683cd2e6`).

### 2.1 Where the curated list is

- The source is the gateway seed list: `_default_model_slugs()` in
  `apps/aigateway/src/aigateway/plugins/openrouter_provider/settings.py:73-182` (74 ids).
- The Engine has a copy: `apps/screamingface-engine/src/screamingface_engine/world/models/seeds/openrouter.py`.
- `apps/screamingface-engine/tests/unit/test_declared_models_match_aigateway.py` fails if the two
  lists are not the same set. Thus the two lists must change in one PR. Commit `8202894f8`
  (the HLE judge) did this.
- Two tests pin the content:
  `apps/aigateway/tests/unit/openrouter/test_openrouter_settings.py:112-113` (the exact list) and
  `apps/screamingface-engine/tests/unit/test_model_seeds.py:34-37` (117 ids, 88 routable, 29 with
  a colon).
- The check of a seed is only a syntax check. The seed comments say "present in the live
  OpenRouter catalog on <date>; re-check at release" (`settings.py:76-81`). The last large update
  of the list was in August 2026 (`OME-816` on 2026-08-13, `OME-856` on 2026-08-17).

### 2.2 How the list gets its order

- The Engine filters the gateway rows and keeps the gateway order
  (`apps/screamingface-engine/src/screamingface_engine/catalog/executable.py:130-141`).
- The Client keeps the order of the response
  (`packages/screamingface/src/screamingface/_engine/catalog_contract.py:44-83`).
- The gateway lists the providers one after the other. For OpenRouter with a healthy live
  snapshot, it lists the models in alphabetical order of the id
  (`apps/aigateway/src/aigateway/plugins/openrouter_provider/live_models.py:213-222,270-278`).
  With no snapshot, it lists the seeds in the order of the seed file.
- A gateway row has no release date (`apps/aigateway/src/aigateway/core/model_capabilities.py:72-83`).
  The OpenRouter catalogue has one (`created`), and the gateway already reads each catalogue row
  for a different field (`live_models.py:154-178`).

### 2.3 The search that exists today

- In a notebook, `sf.models.list()` shows a widget with a text box "Filter models…"
  (`packages/screamingface/src/screamingface/_ui/catalog.py:94-100,135`).
- The filter keeps a model if the text is a part of "`<id> <provider>`". It ignores the letter
  case (`_ui/catalog.py:120-121,137-138`).
- The text is one string. The query `claude 5.5` finds nothing, because no id contains that
  exact string.
- Outside a notebook there is no search function. The list is a Python sequence.

### 2.4 What does not use the list

The run path does not read the list. The Engine admits an OpenRouter model that is not declared
before it schedules the run (`rest/routes.py:314-354,397`). Thus a model that is not in the list
continues to run.

## 3. Goal

1. The list has the current models of the large labs.
2. A person can find the missing models and the dead models with one command.
3. The newest OpenRouter models are first in the list.
4. The user can search the list with more than one word.
5. The public docs are correct.

## 4. Non-goals

- A change to the Engine listing rule, a switch, or an author filter.
- A release date or a popularity value in the row or in `ModelInfo`.
- One order for all providers. Only OpenRouter gives a release date (§5.2).
- A search that accepts spelling errors (§7).
- New models for the direct provider lists (`anthropic/…`, `codex/…`, `gemini-cli/…`). Their ids
  were not verified (§11, Q5).
- The removal of a model from the list (§11, Q2).

## 5. Design

### 5.1 Unit 1: refresh the curated list

Add 49 OpenRouter models to the gateway seed list and to the Engine copy, in one PR. The list of
the 49 models is in Appendix A.3.

Selection rule:

1. The author is one of 14 labs: `anthropic`, `openai`, `google`, `qwen`, `mistralai`,
   `deepseek`, `x-ai`, `meta`, `moonshotai`, `z-ai`, `tencent`, `minimax`, `xiaomi`,
   `stepfun`. All but `stepfun` are already in the list. `stepfun` has rank 7 of the most used
   models.
2. The id is plain (no `:variant`, no `~`).
3. OpenRouter released the model in the last 110 days. This period starts before the last large
   update of the list.
4. The output is text only.
5. The model is a general chat model. Appendix A.4 gives the 11 models that this rule removes.

Verification: each new id must be in the live OpenRouter catalogue on the day of the PR. This is
the same standard as `OME-816`. No paid call is necessary.

Effects in the code:

- Gateway: 49 lines in `_default_model_slugs()`, with a dated comment.
- Engine: the same 49 lines in `seeds/openrouter.py`.
- Tests: the exact list in `test_openrouter_settings.py`, and the counts in `test_model_seeds.py`
  (117 to 166 ids, 88 to 137 routable, 29 with a colon stay 29). These are edits to current
  tests. The plan uses the approved-test-change procedure if the gate asks for it.

### 5.2 Unit 2: the newest OpenRouter models first (optional)

The gateway sorts the discovered OpenRouter rows by release date, newest first. If two models
have the same date, or a model has no date, the id decides the order.

- The gateway reads `created` from each catalogue row in the same tolerant way as it reads the
  input types today (`live_models.py:154-178`). A missing or bad value does not fail the refresh.
- `live_listing_entries` uses the dates for the order (`live_models.py:242-279`).
- The row content does not change. The Engine and the Client need no change, because they keep
  the gateway order (§2.2).
- A model with no date comes after the models with a date, in the order of the id. Thus, if no
  row has a date, the order is the alphabetical order of today, and no current test must change.
- Estimated size: approximately 30 lines in two gateway files, plus tests.

Limits:

- The order is by date only in the OpenRouter group. The other providers keep the order of their
  seed files, and the groups stay one after the other.
- If the gateway has no live snapshot, the order is the order of the seed file.
- Studio sorts the models by id (`apps/screamingface-studio/frontend/src/lib/model-store.ts:64-115`),
  so Studio does not show this order.

### 5.3 Unit 3: search with more than one word

Change `_Catalog._matches` so that the query is divided at the spaces, and a model matches if
each word is a part of its search text (`packages/screamingface/src/screamingface/_ui/catalog.py:120-121`).

| Query | Today | After the change |
|---|---|---|
| `claude` | All Claude models | The same |
| `claude 5.5` | Nothing | `claude-opus-5.5`, `claude-sonnet-5.5`, `claude-haiku-5.5` |
| `openrouter flash` | Nothing | All OpenRouter models with `flash` in the id |

- Size: approximately 3 lines, plus tests. The benchmark catalogue uses the same function, so it
  gets the same behaviour.
- No new public function. For a script, the docs show one line of Python:
  `[m for m in sf.models.list() if "claude" in m.id]`.

### 5.4 Unit 4: a command that finds the changes (optional)

A small script in `apps/aigateway/scripts/` that reads the public OpenRouter catalogue and
prints:

1. The seeds that are not in the catalogue.
2. The plain text models of the 14 labs that are newer than the newest seed and are not seeds.

- A person runs it before each release. It is not a CI gate, because it uses the network
  (`.claude/sdlc.local.md` keeps such checks out of the gates).
- It does not change a file. A person decides which models to add.
- Estimated size: approximately 60 lines, with no new dependency.

### 5.5 Unit 5: public docs

- `public-docs/src/pages/sf-client/guides/ModelsPage.vue:36,176-179`: remove the exact counts
  ("110 entries", "112 against 110"). They are incorrect after each refresh.
- `ModelsPage.vue:185-187`: replace "The catalogue is fixed … a model missing from the list can't
  be added from the Client". State that the list is curated, and that an OpenRouter model that is
  not in the list runs through `openrouter/<author>/<model>`.
- `public-docs/src/pages/sf-client/api/ModelsCatalogPage.vue:157-160,174`: "every addressable
  route" becomes "the curated routes".
- Add the filter box, the search with more than one word, and the one line of Python for scripts.

## 6. What does not change

- `GET /v1/models` in the Engine: the rule, the row content, the cache, and the ETag logic.
- The admission of OpenRouter models on demand.
- The Client public surface (`tests/public_surface_snapshot.json`).

## 7. Alternatives that this spec does not use

| Alternative | Why not |
|---|---|
| List all the models that the Engine can admit | Owner decision 2026-11-17: the list stays curated. |
| List the models of a set of authors, with a setting | Owner decision 2026-11-17: no switch. |
| Put the release date in the row and in `ModelInfo` | It changes the gateway row contract, the Client public surface, and the docs. Too large. |
| Sort in the Client | The Client has no date to sort on. |
| A search that accepts spelling errors | It needs a score for each model and a rule for the order of the results. The words rule of §5.3 gives most of the value with 3 lines. |
| A new function `sf.models.search()` | It adds public API, a snapshot change, and docs. One line of Python gives the same result. |
| Read the OpenRouter ranking page to select models | The page has no stable API. `openrouter.ai/api/frontend/models/find?order=top-weekly` answered 404 on 2026-11-17. |

## 8. Units and landings

| Unit | Landing | Necessary | Size |
|---|---|---|---|
| 1. Refresh the list | `aigateway` and `screamingface-engine`, one PR (`OME-1955`) | Yes | 98 list lines, 2 tests |
| 2. Newest first | `aigateway` | Optional | Approximately 30 lines, tests |
| 3. Search with words | `client-sf` | Yes | Approximately 3 lines, tests |
| 4. The command | `aigateway` | Optional | Approximately 60 lines |
| 5. Public docs | Public docs | Yes | 2 pages |

Units 2 to 5 get their tickets when their PRs open.

## 9. Tests (write them first; they must fail before the change)

Unit 1:

1. The gateway default list is the new exact list (`test_openrouter_settings.py`).
2. The Engine world has 166 ids, 137 routable ids, and 29 ids with a colon (`test_model_seeds.py`).
3. `test_declared_models_match_aigateway.py` passes with no edit.
4. Each id that was in the list before the change is in the list after the change.

Unit 2:

5. With dates, the discovered rows are in the order newest first.
6. Two rows with the same date are in the order of the id.
7. A row with no date, or with a bad date, comes after the rows with a date, and the refresh does
   not fail.
8. Operator entries stay first, as today.
9. The row content is the same as today.

Unit 3:

10. A query with two words matches a model that contains the two words in a different order.
11. A query with one word gives the same result as today.
12. A query with only spaces shows all the models.
13. The benchmark catalogue filters with words in the same way.

Unit 4:

14. With a fixed catalogue file, the script prints the dead seeds and the new models, and it does
    not use the network in the test.

## 10. Risks and limits

- **The list is out of date again if no person runs the command.** Unit 4 makes the check one
  command, but it does not make the check automatic.
- **A new model is not tested with a paid call.** The check is "the id is in the live catalogue".
  A model can be in the catalogue and fail for a different reason.
- **The Scoreboard does not know the new models.** A route that is not in
  `apps/scoreboard/src/scoreboard/classification/open_weights.py` counts as closed or unknown.
  This is the behaviour of today for each model that is not in that file.
- **The order is not one order.** It is by date only in the OpenRouter group (§5.2).
- **Not measured:** the list of the hosted Engine. This spec used the lists in the code and the
  public OpenRouter catalogue.

## 11. Open questions for the owner

| # | Question | Recommendation |
|---|---|---|
| Q1 | Are the 49 models of Appendix A.3 the correct set? | **Decided 2026-11-17: yes.** |
| Q2 | Four models in the list are not in the OpenRouter catalogue (Appendix A.5). Must they leave the list? | No. A saved url4 that names one of them can still replay from the cache. Decision 4 also says that no model leaves the list. |
| Q3 | Are units 2 and 4 in scope? | Yes for the two. They are small and separate, and each one can be dropped with no effect on the others. |
| Q4 | `OME-1955` has the label `screamingface-engine`. Unit 1 changes the gateway list first. Must the label be `aigateway`, as `OME-816`? | Yes. The ticket title and text must also change, because they describe the earlier design. |
| Q5 | Must the direct provider lists (Anthropic, Codex, Gemini CLI) get their new models? | A different ticket. Their ids are not OpenRouter ids and were not verified. |
| Q6 | Which label does the public docs ticket get? | `client-sf`, as `OME-1936` and `OME-1937`. |

## 12. Acceptance

- The 49 models are in `sf.models.list()` on an Engine with the new gateway and the new Engine.
- Each model that was in the list before the change is in the list after the change.
- With a healthy gateway snapshot, the first OpenRouter row is the newest OpenRouter model in the
  list (unit 2).
- The query `claude 5.5` in the notebook filter shows the three Claude 5.5 models (unit 3).
- The gateway gates, the Engine gates, and the Client gates are green, and the tests of §9 failed
  before the change.
- The public docs agree with the behaviour.

## Appendix A. Measurement of 2026-11-17

Sources: the public OpenRouter catalogue (`https://openrouter.ai/api/v1/models?output_modalities=text`),
the OpenRouter weekly ranking page (usage data through 2026-11-16), and the Engine seed file.

### A.1 The gap

| Item | Value |
|---|---|
| OpenRouter text models | 474 |
| Plain ids (no `:variant`, no `~`) | 354 |
| OpenRouter models in the curated list | 74 (69 plain, 5 with a colon) |
| Plain OpenRouter models that are not in the list | 288 |
| Of these, released in the last 30 days | 28 |
| Of these, released in the last 90 days | 98 |
| Newest model in the list | 82 days old |

### A.2 The ten most used models (trailing 7 days to 2026-11-16)

| Rank | Model | In the list today | In the list after unit 1 |
|---|---|---|---|
| 1 | `deepseek/deepseek-v4.1-flash-1017` | No | Yes |
| 2 | `tencent/hy4` | No | Yes |
| 3 | `deepseek/deepseek-v4.1-flash` | No | Yes |
| 4 | `z-ai/glm-5.3-flash` | Yes | Yes |
| 5 | `openai/gpt-6-luna` | No | Yes |
| 6 | `anthropic/claude-opus-5.5` | No | Yes |
| 7 | `stepfun/step-5-preview` | No | Yes |
| 8 | `xiaomi/mimo-v2.6-flash` | No | Yes |
| 9 | `z-ai/glm-5.3` | No | Yes |
| 10 | `openai/gpt-6.1-sol` | No | Yes |

### A.3 The 49 models to add

The number in parentheses is the age in days on 2026-11-17. Each id has the prefix
`openrouter/<author>/`.

| Author | Count | Models |
|---|---|---|
| `anthropic` | 5 | `claude-fable-5.2` (7 d), `claude-opus-5.5` (55 d), `claude-sonnet-5.5` (49 d), `claude-haiku-5.5` (40 d), `claude-fable-5.1` (76 d) |
| `openai` | 14 | `gpt-6.2-astra` (0 d), `gpt-6.2-astra-pro` (0 d), `gpt-6.2-sol` (0 d), `gpt-6.2-sol-pro` (0 d), `gpt-6.1-terra` (21 d), `gpt-6.1-terra-pro` (21 d), `gpt-6.1-sol` (48 d), `gpt-6.1-sol-pro` (48 d), `gpt-6-luna` (55 d), `gpt-6-luna-pro` (55 d), `gpt-6-sol` (55 d), `gpt-6-sol-pro` (55 d), `gpt-6-astra` (73 d), `gpt-6-astra-pro` (73 d) |
| `google` | 5 | `gemini-4-hydrogen` (4 d), `gemini-4-carbon` (6 d), `gemini-4-argon` (34 d), `gemini-3.8-flash` (75 d), `gemini-3.7-flash` (95 d) |
| `qwen` | 6 | `qwen4-max` (1 d), `qwen3.8-max-prime` (54 d), `qwen3.8-omni-flash` (57 d), `qwen3.8-max-0902` (74 d), `qwen3.8-flash` (82 d), `qwen3.8-27b` (94 d) |
| `mistralai` | 1 | `mistral-large-4-0` (41 d) |
| `deepseek` | 2 | `deepseek-v4.1-flash-1017` (31 d), `deepseek-v4.1-flash` (68 d) |
| `x-ai` | 1 | `grok-4.7` (56 d) |
| `meta` | 4 | `muse-ember` (7 d), `muse-spark-open` (32 d), `muse-wonder` (35 d), `muse-spark-1.3` (75 d) |
| `moonshotai` | 1 | `kimi-k3.1-pro` (24 d) |
| `z-ai` | 3 | `glm-5.3-prime` (54 d), `glm-5.3-flashx` (59 d), `glm-5.3` (90 d) |
| `tencent` | 2 | `hy4-flash` (0 d), `hy4` (13 d) |
| `minimax` | 1 | `minimax-m3.1-flash` (29 d) |
| `xiaomi` | 3 | `mimo-v2.6-pro` (56 d), `mimo-v2.6-flash` (56 d), `mimo-v2.6-pro-ultraspeed` (56 d) |
| `stepfun` | 1 | `step-5-preview` (39 d) |
| **Total** | **49** | |

### A.4 Models of the 14 labs that the selection rule removes

| Model | Reason |
|---|---|
| `google/gemini-omni-1.2-flash`, `google/gemini-omni-1.1-flash` | The output is text and video |
| `google/gemini-nano-banana-2.1` | The output is image and text |
| `tencent/hy-mt2-1.8b`, `tencent/hy-mt2-7b`, `tencent/hy-mt2-30b-a3b` | Translation models |
| `tencent/hy4-preview` | `hy4` replaces it |
| `deepseek/deepseek-v4-flash-vision-exp` | An experimental model |
| `meta/muse-spark-1.3-contributor`, `meta/muse-spark-1.2-contributor` | A special price tier of a model that is in the list |
| `z-ai/glm-5.3-flashx-legal` | A model for one domain |

### A.5 Models in the list that are not in the OpenRouter text catalogue

`qwen/qwen3.8-max`, `anthropic/claude-opus-5-fast`, `nex-agi/nex-n2-mini`, and the colon variant
`liquid/lfm-2.5-2.6b:free`.
