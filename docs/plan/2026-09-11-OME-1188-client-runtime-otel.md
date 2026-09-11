# OME-1188 — Implementation plan

1. Reproduce the existing runtime dependency-parity failure before editing dependencies.
2. Add the two approved requirements to the runtime extra and refresh the lockfile.
3. Run the existing regression and full screamingface gate runner; inspect dependency churn.
4. Record validation, commit, push, and open a draft PR. Keep the issue open for review.
