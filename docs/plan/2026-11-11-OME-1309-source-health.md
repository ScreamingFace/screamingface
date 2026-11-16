# Source-health implementation plan

1. Add failing network and storage/API tests, then implement the guarded probe, separate model, migration, store, and board-scoped CLI.
2. Add rendering tests, then show a concise unchecked notice below Source. Preserve existing UI and ranking.
3. Exercise concurrency on PostgreSQL and populated migrations; run registered gates.
4. Preview representative healthy, unchecked, and never-successful rows locally in both themes and mobile/desktop sizes. Document run/rollout instructions; keep Linear unchanged.

Rebase validation (2026-11-16): replay only source-health commits onto main after #1731; retain the shared comparison-note helper and update the test harness to load it. Preserve prior approval records in the archive. Run full gates, PostgreSQL regressions and desktop/mobile theme checks before updating the PR.
