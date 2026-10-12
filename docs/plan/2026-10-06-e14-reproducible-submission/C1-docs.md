# C1 — public docs and glossary

- **Worktree:** `.claude/worktrees/e14-c1-docs` · **Branch:** `e14-c1-docs`
- **Base:** `e14-b5-sdk-reproduce` (the docs describe the final SDK surface) · **Stack:** none (docs);
  run the public-docs build. Rules: `00-common.md`.
- **Spec:** `00-overview.md` §6 (C1) and the four PRDs. Read the final code on this branch and on
  the other E14 branches for the exact names (`git show <branch>:<path>`).

## Files

| File | Change |
|---|---|
| `public-docs/src/pages/sf-client/guides/LeaderboardsPage.vue` | submit with `paper_url`; `sf.leaderboards.edit` and `metadata_events` (owner only); replace the "fresh paid replay" remix line with `sf.reproduce(score)` and its three outcomes; "Reproduced N times" |
| `public-docs/src/pages/learn/CachingPage.vue` | a short "Reproducing a submission" section: cache revision, `reproducible: partial` and why (bypass, race, web tool, error, mixed revisions), zero provider cost, older revisions stay replayable, a different SDK or engine version can make a replay fail |
| `public-docs/src/pages/sf-client/api/LeaderboardsPage.vue` | the new `LeaderboardScore` fields, `ScoreMetadataEvent`, `Reproduction` |
| `CONTEXT.md` | glossary: **Cache Revision**, **Reproducible** (complete/partial), **Reproduction** — same entry style as the existing terms |

## Decisions (pinned)

- Write in the style of the surrounding pages (short sentences; existing component and code-block
  patterns). No new Vue components.
- Do not document internal headers (`X-Cache-Replay`) or gateway controls on the client pages; the
  caching page may name `only-if-cached` once, as the reason a replay never pays a provider.

## Verify

The public-docs build and its lint/type checks (find the commands in `public-docs/package.json`;
use `npm ci` then the build script). Report the result lines.
