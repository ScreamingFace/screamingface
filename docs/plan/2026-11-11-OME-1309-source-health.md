# Source-health implementation plan

1. Add failing network and storage/API tests, then implement the guarded probe, separate model, migration, store, and board-scoped CLI.
2. Add rendering tests, then show a concise unchecked notice below Source. Preserve existing UI and ranking.
3. Exercise concurrency on PostgreSQL and populated migrations; run registered gates.
4. Preview representative healthy, unchecked, and never-successful rows locally in both themes and mobile/desktop sizes. Document run/rollout instructions; keep Linear unchanged.
