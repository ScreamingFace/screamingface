---
id: OME-1994
linear_url: https://linear.app/openmined/issue/OME-1994/show-detaching-a-run-and-picking-it-up-later-in-the-runs-notebook
status: in_progress
type: docs
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1837
created: 2026-11-20
closed:
---

# Show detaching a Run and picking it up later in the Runs notebook

The Runs demo notebook (`examples/21_runs.ipynb`, from `OME-1910`) gains section 7, "Detach and
come back later": start a Run with `detach=True` (paid, off by default), then pick it up in a
fresh kernel or on another machine with `sf.runs.get(run_id).wait()`. It is what Product tries in
the E5 P2 handover.

- 2026-11-20: filed at PR-open.
- Ledger: `docs/work/2026-11-20-e5-p2-runs-notebook.md`
