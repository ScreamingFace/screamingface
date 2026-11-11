---
ticket: OME-1309
stack: scoreboard
status: done
started: 2026-11-11
finished: 2026-11-11
---

# Make source DNS checks cancellable through command shutdown

## Intent
Fix the independent review's P2: a timed-out getaddrinfo thread keeps asyncio.run alive and retains worker resources. User authorized the fix.

## Planned changes
- Resolve hostnames in a short-lived, isolated Python subprocess using the same system resolver; kill and reap it on timeout/cancellation.
- Keep numeric IPs direct, the existing deadline, public-address checks, pinned connections, and UI unchanged. No new dependency.
- Append regression tests covering total asyncio.run duration, worker cleanup, success, resolver errors, and explicit cancellation. Update runbook.

## Test plan
First reproduce the shutdown delay in a child command with a blocking fake getaddrinfo. Then verify both prompt return and subprocess cleanup, including direct task cancellation. Run existing source checks and full scoreboard gates.

## Acceptance
A stalled DNS lookup cannot delay command shutdown after its deadline or survive a cancelled check. Existing transport, ranking, storage, and UI behavior stay intact.

## Outcome
- **Changes:** added `source_dns.py`, moved the default resolver out of `source_probe.py`, appended `test_source_dns.py`, and documented process cleanup in the runbook. No schema, UI, or dependency changes.
- **Regression:** before the fix, a 200 ms deadline returned from asyncio.run after 5.008 seconds; after the fix, 0.204 seconds with no live resolver worker. Tests assert whole-command elapsed time and that the worker is gone, not only probe return time.
- **Validation:** 42 focused DNS/probe/CLI checks passed. Full scoreboard gate runner (lint, format, types, Python suite/coverage, registered portal tests) passed against the history parent. Real published SAD page responded successfully through the new resolver; no status was saved.
- **Commit:** `fix(scoreboard): stop DNS workers when source checks time out` (this commit).
- **Wisdom review:** argv data never becomes shell/code; isolated stdlib child retains system DNS settings; cancellation kills and drains/reaps the worker, including full-pipe cases. Numeric addresses bypass lookup and remain subject to the transport's public-address check. Existing tests remain unchanged.
- **Deviations:** none. No live database, Linear, or UI changes.

