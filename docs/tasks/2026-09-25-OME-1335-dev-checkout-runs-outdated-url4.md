---
id: OME-1335
linear_url: https://linear.app/openmined/issue/OME-1335/screamingface-up-in-a-dev-checkout-runs-an-outdated-url4-and-crashes
status: in_review   # Linear: Triage (bug, awaiting triage review)
type: bug
priority: High
labels: [bug, client-sf, agentic, autonomous]
created: 2026-09-25
closed:
---

# `screamingface up` in a dev checkout runs an outdated url4 and crashes at boot

The editable dev install copied url4 and the three apps into the venv at build time. `import
screamingface` loads that copy before checkout activation can run, so a Sep 18 url4 copy served
Sep 22 Engine code and boot crashed on `No module named 'url4.cli._config'`. Fix: editable builds
ship a `.pth` pointing at the live source directories, never copies. The boot check now counts a
module as live only under those directories, and prints the reinstall command otherwise. The Studio
sidecar spec resolves its resources through the runtime's own lookups. Ledger:
`docs/work/2026-09-25-fix-stale-runtime-sources.md`.
