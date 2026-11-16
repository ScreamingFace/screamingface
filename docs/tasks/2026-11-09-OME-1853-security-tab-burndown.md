---
id: OME-1853
linear_url: https://linear.app/openmined/issue/OME-1853/burn-the-security-tab-back-down-to-real-alerts-2026-11-sweep-392
status: done
type: task
priority: medium
labels: [repo-dev-processes, agentic, autonomous, task]
parent: OME-733
created: 2026-11-09
closed: 2026-11-09
---

# Burn the Security tab back down to real alerts (2026-11 sweep: 392 Dependabot + 14 CodeQL)

On 2026-11-06 the Security tab showed 392 Dependabot and 14 CodeQL alerts. 131 point at
`apps/server` and `apps/url4-cloud`, deleted from `main`; 67 repeat Engine pins in the Studio
runtime lock; 7 green security PRs sat unmerged; 4 CodeQL alerts are in the legacy desktop
build output.

One PR (owner's call, 2026-11-09): every fixable alert on the 11 live lock files, the three
Benchmarks whose Cases the Pillow and pypdf bumps change re-sealed with their published ids
held, the two desktop build artifacts deleted. Ledger:
`docs/work/2026-11-09-security-tab-burndown.md`.

Left for the owner, no code: dismiss the 131 ghost alerts, dismiss the 9 url4 regex CodeQL
alerts (timed at under 0.5 ms on 16 KiB), decide the HuggingFace log-line alert, and let
Dependabot close its superseded PRs after merge.
