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
parsed wait could be 3.9996s and miss the 5 ± 1 window (failed CI on #1258 and #1268). Fixed by
giving the SDK's Retry-After parser a clock seam (`now=`, default real UTC time) so the test's
fake server and the parser read one clock and the wait is asserted exactly; the same seam fixes
the third test of this shape in `test_admission_retry.py`. Production defaults are unchanged.

Ledger: `docs/work/2026-10-07-retry-after-test-flake.md`.
