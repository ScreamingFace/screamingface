---
id: OME-1507
linear_url: https://linear.app/openmined/issue/OME-1507/sdk-tests-fail-at-random-when-a-servers-retry-time-lands-just-under
status: done
type: bug
priority: medium
labels: [bug, client-sf, agentic, autonomous]
created: 2026-10-07
closed: 2026-10-07
---

# SDK tests fail at random when a server's retry time lands just under four seconds

Two Retry-After tests built "now + 5s" as an HTTP-date, which drops fractions of a second, so the
parsed wait could be 3.9996s and miss the 5 ± 1 window (failed CI on #1258 and #1268). Fixed in
the tests by starting from now rounded down plus 6s. No SDK behaviour changes.

Ledger: `docs/work/2026-10-07-retry-after-test-flake.md`.
