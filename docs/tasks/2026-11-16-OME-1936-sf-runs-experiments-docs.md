---
id: OME-1936
linear_url: https://linear.app/openmined/issue/OME-1936/document-sfruns-and-add-a-managing-experiments-guide-in-public-docs
status: In Progress
type: task
priority: 3
labels: [client-sf, agentic, autonomous]
parent: OME-1294
created: 2026-11-16
closed:
---

# Document sf.runs and add a "Managing experiments" guide in public-docs

Mirror of [OME-1936](https://linear.app/openmined/issue/OME-1936/document-sfruns-and-add-a-managing-experiments-guide-in-public-docs),
a leaf under the E5 epic [OME-1294](https://linear.app/openmined/issue/OME-1294/e5-improve-managing-runs-in-sf-client-epic).

Public documentation for the E5 P1 `sf.runs` module (shipped on `main` in `d63c353a7c`):

- **Reference** `api/RunsPage.vue` → `/sf-client/api/runs` — the `sf.runs` module (`list`/`get`
  + async twins) and the `Run`, `CandidateRun`, `RunProgress` values, under Results & grading.
- **How-to guide** `guides/ExperimentsPage.vue` → `/sf-client/guides/managing-experiments` —
  launch, find, follow, reopen and cancel runs, for a researcher on the hosted engine or their
  own stack. Mirrors the eng "Find and manage your Runs" notebook.

Plus router + nav wiring, cross-links from `ModulesPage` and `EvaluationPage`, and the
`public-docs/CLAUDE.md` route table.

Ledger: `docs/work/2026-11-16-sf-runs-docs.md`.
