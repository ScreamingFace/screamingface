---
id: OME-1176
linear_url: https://linear.app/openmined/issue/OME-1176/combining-two-bless-modes-silently-runs-only-one-of-them
status: done
type: fix
priority: 3
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-10
closed: 2026-09-11
---

# Combining two bless modes silently runs only one of them

Post-merge review findings on PR #870 (OME-1098 goldens): `--refresh-golden
--dump-fresh` silently ignores the fresh recording (boolean flags dodge the
`is not None` exclusion guard); golden field policing is one-directional
(fusion fields ride a loop golden as dead weight); three logic blocks in the
bless tool exist as near-verbatim copies. Fix the two bugs loudly, fold each
copy into one authority.

Full spec: the Linear issue. Ledger:
`docs/work/2026-09-10-OME-1176-bless-mode-exclusivity.md`.
