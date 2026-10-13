---
id: OME-1594
linear_url: https://linear.app/openmined/issue/OME-1594/jupyterlab-opens-to-a-blank-page-in-the-sdk-dev-environment
status: done
type: bug
priority: medium
labels: [bug, client-sf, agentic, autonomous]
created: 2026-10-13
closed: 2026-10-13
---

# JupyterLab opens to a blank page in the SDK dev environment

Dependabot's tornado 6.5.9 bump (`1dfed1971`) broke static files under jupyter-server 2.20.0
(`AttributeError: 'FileFindHandler' object has no attribute 'allowed_symlink_directory'`).
The fix upgrades jupyter-server to 2.21.1 in `packages/screamingface/uv.lock`. It is a dev-group
dependency only.

- Ledger: `docs/work/2026-10-13-bump-jupyter-server.md`
