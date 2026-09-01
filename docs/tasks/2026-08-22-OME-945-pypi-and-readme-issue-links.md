---
id: OME-945
linear_url: https://linear.app/openmined/issue/OME-945/finish-the-org-repoint-pypi-issue-urls-and-readme-issue-link
status: in_progress
type: task
priority: 2
labels: [repo, agentic, autonomous, task]
created: 2026-08-22
closed:
---

# Finish the org repoint: PyPI issue URLs and README issue link

Parent: `OME-935` (debugging & traceability roadmap — Phase 0 epic).

Reporters are misdirected today: PyPI metadata and the docs/portal links pointed at different
trackers. Two items:

1. Align `project.urls` in `packages/screamingface/pyproject.toml` and
   `packages/url4/pyproject.toml` to the canonical org.
2. Make the README's "just open an issue" sentence an actual link to the issues page.

Item 1 was found already satisfied on `main` — both files declare `Homepage`, `Repository`
and `Issues` under `ScreamingFace/…`, so the divergence the ticket describes was one-sided:
the docs half (`OME-914`) was the only stale side. Item 2 is the real change.

Executed together with `OME-914` on one branch — the two are halves of the same sweep.

- Ledger: `docs/work/2026-08-28-OME-914-org-repoint.md`
- Branch: `OME-914-org-repoint`
- Spec: `docs/spec/2026-08-22-observability-traceability-review.md`
