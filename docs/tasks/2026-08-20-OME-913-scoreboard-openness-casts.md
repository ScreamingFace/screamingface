---
id: OME-913
linear_url: https://linear.app/openmined/issue/OME-913/scoreboard-cast-tortoise-charfield-reads-at-the-openness-literal
status: Done
type: Task
priority: High
labels: [scoreboard, agentic, autonomous, task]
created: 2026-08-20
closed: 2026-08-20
---

# scoreboard: cast Tortoise CharField reads at the Openness Literal boundaries

`tortoise-orm 1.1.8` types `fields.CharField(...)` as `str | None`, so `openness_override`
stops satisfying the schema's `Literal["open","closed"] | None`. Two sites; landing the casts
ahead of the bump lets Dependabot `#637` deliver 1.1.8 unmodified.

Verified green under both 1.1.7 and 1.1.8 — that pairing is what makes it safe to land first.

Canonical artifacts:

- Ledger: `docs/work/2026-08-20-OME-913-scoreboard-openness-casts.md`
- PR: #661 (merged)
