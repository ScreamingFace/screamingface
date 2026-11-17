---
id: OME-1957
linear_url: https://linear.app/openmined/issue/OME-1957/match-each-word-in-the-catalogue-filter-and-correct-the-model-list
status: in_review
type: feature
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1955
created: 2026-11-17
closed:
---

# Match each word in the catalogue filter and correct the model list docs

The notebook filter of `sf.models.list()` matched one string, so the query `claude 5.5` found
nothing. The filter now matches each word of the query. The public docs now describe the curated
list, say that an OpenRouter model that is not in the list still runs, and describe the search.

- Spec and plan: `docs/spec/2026-11-17-OME-1955-refresh-curated-model-list.md` §5.3 and §5.5, and
  `docs/plan/2026-11-17-OME-1955-refresh-curated-model-list.md` §4 (in the PR of `OME-1955`).
- Ledger: `docs/work/2026-11-17-catalogue-filter-words.md`
