---
id: OME-391
linear_url: https://linear.app/openmined/issue/OME-391/sf-324-protect-scoreboard-writes-and-deduplicate-submissions
status: in_progress
type: task
priority: P1
labels: [scoreboard, autonomous, agentic]
created: 2026-07-13
closed:
---

SF-324: Protect scoreboard writes and deduplicate submissions. Two grouped findings:

* C2: public score submission accepts unauthenticated writes.
* C28: duplicate submissions only dedupe via an optional client-supplied
  `Idempotency-Key` header.

Working as two steps within this one ticket (see the 2026-07-13 comment on the
issue):

1. **Now**: server-enforced dedup by recipe content hash (C28) — no product decision
   needed. Ledger: `docs/work/2026-07-13-OME-391-scoreboard-submission-dedup.md`.
2. **Blocked**: write-path authentication/attribution (C2) — needs a product decision
   on uncredentialed-submission policy, and depends on OME-326 (OpenMined identity
   provider), which doesn't exist yet.
