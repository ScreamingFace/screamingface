---
ticket: OME-1309
stack: scoreboard
status: done
started: 2026-11-11
finished: 2026-11-11
---

# External source availability

## Intent
Keep outside results visible when their source cannot be reached, and show the last successful availability check. User authorized implementation on November 11. No Linear writes authorized.

## Planned changes
- Separate source-health model and migration, keyed by the exact source URL; batched read projection into baseline responses.
- Operator command to probe unique sources for a selected board, with public-address-only connections, bounded redirects/time, and no downloaded page bodies.
- Small accessible notice under the existing Source button; preserve ranks, scores, comparison notes, and edit history.
- Tests for failures, recovery, URL replacement, concurrency, schema migration, HTTP limits, privacy, and rendering.
- Runbook with deployment and check commands. No scheduler or live environment changes in this unit.

## Test plan
Write failing tests before implementation. Verify success → failure → recovery, initial failure without invented dates, shared URLs checked once, stale concurrent results, unchanged edit history/ranking, SSRF/redirect protection and deadlines. Inspect desktop/mobile light/dark previews, then run scoreboard and repo gates.

## Acceptance
A failed check keeps every result and its rank, exposes availability/check dates only, and shows an accessible unchecked notice. Recovery removes that notice. Changing the source never inherits another URL's status. Reads never perform network requests.

## Outcome

- **Actual files:** source probe, board-scoped CLI, SourceHealth model and migration 0024, batched baseline read projection, Source notice, runbook, focused network/storage/CLI/migration/portal tests, CI and gate registration, strict public-field allowlist update. No dependencies added.
- **Commit:** `feat(scoreboard): retain results when source links cannot be checked` (this commit).
- **Gates:** scoreboard and repo gate runners pass against the parent history branch; 19 real PostgreSQL integration/migration/concurrency checks pass; 27 guarded network tests pass; 28 focused portal tests pass, with the four new UI tests also passing in UTC+14. The real published SAD page responded successfully through the guarded transport without any database write.
- **Visual check:** inspected 1440px and 390px layouts in light/dark themes, mixed four public community rows and two outside results. Verified initial failure, retained last-success date, and recovery. No page overflow; desktop table fits its container. Source links remain the same real published table. Simulated failures are preview-only, not statements about the publisher.
- **Deviations:** stacked on #1731 to preserve approved UI and history. User authorization for broken-source handling covers adding the public availability field; only that field is added to the strict privacy allowlist, with byte-pinned approval and explicit public/private-board tests. Existing actor/participant leak assertions remain. No Linear updates, scheduler changes, deployment, or live database writes.
- **Wisdom review:** health stays separate from score history and eligibility; read path makes one batched health lookup and no HTTP calls. Fixed-size URL keys avoid long-URL index limits. Row locks preserve newer outcomes and last successful checks. Request connections are pinned to public IPs, with TLS hostname retained, no proxy settings, bounded redirects, no body downloads, and explicit Azure platform-address refusal. The existing migration hook remains unchanged.
- **Remaining rollout:** review and merge #1731 first, rebase this branch, deploy migration/application, run the operator check and dev acceptance. Recurring execution is an explicit deployment follow-up.

## Decisions
- Separate branch stacked on #1731 to preserve the user's approved Source/history layout; worktree initially created from origin/main, then rebased onto #1731.
- A check establishes URL availability only, not whether a score is still published or correct. Non-success HTTP responses, DNS/TLS/timeouts, and disallowed destinations mean unchecked, not proof of permanent deletion.
- Health is shared only by identical URL, stored separately from score observations; no spurious edit-history versions.
- First version is an explicit operator command; recurring scheduling is a deployment follow-up, not enabled implicitly.
