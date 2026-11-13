---
id: OME-1922
linear_url: https://linear.app/openmined/issue/OME-1922/refuse-an-e4c-recipe-before-the-first-paid-call-on-an-engine-without
status: backlog
type: feature
priority: 3
labels: [client-sf, agentic, autonomous, blocked]
created: 2026-11-13
closed:
---

# Refuse an E4c recipe before the first paid call on an Engine without E4c

Mirror of OME-1922 (parent epic OME-1291, E4c). Blocked by OME-1921.

A follow-up of the PR #1733 review (sergio-bershadsky, S1, round 3). Not part of #1733. Blocked by the Engine capability issue.

**Problem.** A new SDK on an Engine without E4c pays every member, then fails each Case on `phase=decide`.

**This issue (SDK side).** Before the first paid call, the SDK reads the Engine capability. If the recipe holds a Gate, Cascade or budget and the Engine does not support E4c, the SDK refuses the run.

**Test (from the review).** A Gate-with-fallback recipe on a fake Engine without the capability raises `EngineCapabilityError` and records zero model calls.

Ledger: `docs/work/2026-10-22-e4c-routers-cascades.md` (2026-11-13 review round 3).
