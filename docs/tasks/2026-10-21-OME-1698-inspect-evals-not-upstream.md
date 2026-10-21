---
id: OME-1698
linear_url: https://linear.app/openmined/issue/OME-1698/say-inspect-evals-or-the-benchmark-authors-instead-of-a-bare-upstream
status: done
type: task
priority: low
labels: [screamingface-engine, agentic, autonomous, task]
parent: OME-1299
created: 2026-10-21
closed: 2026-10-21
---

# Say inspect_evals or the benchmark authors instead of a bare "upstream" in the engine's benchmark code

The engine's inspect code used "upstream" 389 times, for four different things: the inspect_evals
library, the benchmark authors' own code or data, the AI gateway's model provider, and our git
remote (literally named `upstream`). This change makes each mention name its source:
- where it means inspect_evals, it now says inspect_evals (`upstream_case_count` becomes
  `inspect_evals_case_count`);
- where it means the benchmark authors, it now says the authors' code or dataset;
- the provider and git senses keep the word.

All 83 Benchmark revisions are unchanged.

- 2026-10-21: owner decisions in session:
  - Skip the `.py` files under `local_tasks/<name>/`, because their bytes feed the revision.
    Their 46 lines wait until published IDs are hand-set (`OME-1610`). Their READMEs are reworded.
  - Reword the authors' sense too, linking a source where one is already pinned.
  - `CONTEXT.md` says inspect_evals outright in the Imported Benchmark, Named Deviation and
    Inverted Grade entries.
- Ledger: `docs/work/2026-10-21-inspect-evals-not-upstream.md`.
