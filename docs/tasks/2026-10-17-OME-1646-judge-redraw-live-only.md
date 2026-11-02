---
id: OME-1646
linear_url: https://linear.app/openmined/issue/OME-1646/a-recorded-judge-reply-is-final-redraw-only-after-a-live-reply
status: in_progress
type: fix
priority: high
labels: [screamingface-engine, design-session, agentic]
parent: OME-1642
created: 2026-10-17
closed:
---

# A recorded judge reply is final: redraw only after a live reply

Since PR #1395 the shared judge helper redraws every judge reply with no verdict outside the
gateway cache, also seed rows that record "no verdict" on purpose. A replay of the DRACO
reference run therefore makes paid live calls and its scores drift. Owner rule (2026-10-16): a
redraw happens only after a live reply; a reply from the gateway cache or a frozen-copy replay is
final. The connector records each reply's origin (`live`, `cache`, `replay`); the judge helper
reads it. The rule lives in the shared helper, so it applies to every judge benchmark, and no
published revision moves.

Spec: ../spec/2026-10-16-judge-redraw-live-only.md
Plan: ../plan/2026-10-16-judge-redraw-live-only.md
Ledger: ../work/2026-10-16-judge-redraw-live-only.md
