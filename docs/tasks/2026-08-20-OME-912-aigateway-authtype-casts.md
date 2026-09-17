---
id: OME-912
linear_url: https://linear.app/openmined/issue/OME-912/aigateway-cast-tortoise-charfield-reads-at-the-authtype-literal
status: In Review
type: Task
priority: High
labels: [aigateway, agentic, autonomous, task]
created: 2026-08-20
closed:
---

# aigateway: cast Tortoise CharField reads at the Literal alias boundaries

`tortoise-orm 1.1.8` types `fields.CharField(...)` as a real `str` where pyright previously
inferred `Any`, so values read off `OAuthConnection` stop satisfying `AuthType` and
`OAuthConnectionStatus`. Three sites; landing the casts ahead of the bump lets Dependabot
`#640` deliver 1.1.8 unmodified.

Sibling of `OME-913` (scoreboard) — split per D9, since one issue may carry only one landing
leaf.

Canonical artifacts:

- Ledger: `docs/work/2026-08-20-OME-912-aigateway-authtype-casts.md`
- PR: #662
