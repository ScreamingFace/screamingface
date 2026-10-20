---
id: OME-1649
linear_url: https://linear.app/openmined/issue/OME-1649/fix-cloudflare-access-authentication-blocking-leaderboard-score
status: in_review
type: bug
priority: 3
labels: [bug, client-sf, agentic, autonomous]
created: 2026-10-18
closed:
---

# OME-1649 — Fix Cloudflare Access authentication blocking leaderboard score submissions

`sf.leaderboards.submit()` could not publish to `leaderboard.screamingface.ai`. Since 2026-10-07,
staging and production protect the leaderboard with a separate Access application that covers
only `/v1/scores`; `/` is public. After a challenge, the SDK browser login returned to the origin
root, Access never transferred the token, and the login timed out after 300 s on the public
dashboard.

Infra keeps the two Access applications (Stephen, 2026-10-20). Fix (RC-1): the login returns to
the challenged path. ADR 0001 now describes the hosted Access topology correctly. Out of scope:
RC-2 (proactive scoreboard login before a long run). Still open after merge: one live submit on
staging, then one on production, reported on the issue.

Spec: ../spec/2026-10-20-OME-1649-access-login-challenged-path.md
Ledger: ../work/2026-10-20-OME-1649-access-login-challenged-path.md
Related: `OME-1650` (anonymous `/v1/public/scores` read).
