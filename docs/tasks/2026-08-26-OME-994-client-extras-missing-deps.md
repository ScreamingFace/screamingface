---
id: OME-994
linear_url: https://linear.app/openmined/issue/OME-994/ship-the-missing-dependencies-so-a-fresh-install-works-first-try
status: backlog
type: bug
priority: 2
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-26
closed:
---

# Ship the missing dependencies so a fresh install works first try

From community GitHub issue
[#735](https://github.com/ScreamingFace/screamingface/issues/735): on a clean
machine, `pip install "screamingface[runtime,notebook]"` (0.1.1.post5) leaves
`screamingface up` crashing (missing `python-multipart` in `[runtime]`) and the
`[notebook]` extra without `jupyterlab`, both promised by the Installation docs.

Fix: declare both deps in the extras in `packages/screamingface`, add a test
that each documented extra imports what it promises, cut a post release.
