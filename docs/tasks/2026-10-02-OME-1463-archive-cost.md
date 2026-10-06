---
id: OME-1463
linear_url: https://linear.app/openmined/issue/OME-1463/send-the-archive-cache-saving-and-submit-a-cached-run-as-complete-when
status: done
type: task
priority: high
labels: [client-sf, agentic, autonomous]
parent: OME-1251
created: 2026-10-02
closed: 2026-10-05
---

# Send the archive cache saving and submit a cached run as complete when every hit is priced

SDK half of decision D7 on `OME-1251` (reverses D3). Board half: `OME-1382` (PR #1227).

Ledger: `docs/work/2026-10-02-OME-1463-archive-cost.md`.
Spec: `docs/spec/2026-10-02-OME-1463-archive-cost.md`. Plan: `docs/plan/2026-10-02-OME-1463-archive-cost.md`.

**Ships second.** Merges only after #1227's D7 change is live on dev (`ScoreSubmission` is
`extra="forbid"`).

- 2026-10-02: filed, built, all screamingface gates green; PR opened as draft.
- 2026-10-05: review round 1 fixed (summary is the authority for the money), rebased, merged via #1229 (`64f064d2`); closed in Linear with the close comment. Release note: the SDK release must follow a scoreboard production release with #1227 and #1244.
