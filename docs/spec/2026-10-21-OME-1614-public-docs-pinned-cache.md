# OME-1614 — public docs for pinned-cache replays and submission metadata

Status: implementation authorized by the owner (2026-10-22: "let's now move on to the docs then").

## Goal

The public docs (`public-docs/`, deployed by `deploy-public-docs.yml`) describe the SDK release that
contains OME-1613 (planned as 0.1.7; verify the release before publishing): replay a published run with
`sf.evaluate(pinned_cache=…)`, and attach author and paper metadata. No page teaches the removed
`sf.reproduce` or the renamed `frozen_copy_id` attribute, except one upgrade note.

## What the SDK does (source: approved OME-1613 spec, PR #1519)

- `sf.evaluate(pinned_cache="<id>")` / `score_id="<id>"`; `CandidateResult.reproduction` is a
  `Reproduction | None` value; its `.outcome` is `exact` / `failed`, with `reason` and
  `missed_cases`; recorded on an exact verdict, the
  leaderboard login asked for only then; `record_reproduction=False`.
- `url4=` must be the same parsed recipe; `answer_seed` must equal the captured one; a capture with
  no seed replays with none. `limit=n` replays the first n cases, never judged or recorded.
- A capture never submitted replays with `url4=` (and `answer_seed=` if it had one); no verdict.
- A replay that cannot start raises `sf.ReproductionError` (`not_reproducible`, `replay_unsupported`).
- `pinned_cache` replaces `frozen_copy_id` on `CandidateResult` and `LeaderboardScore`; the report
  JSON and the wire keep `frozen_copy_id`.
- `submit(..., authors_metadata=, paper_metadata=)`, `leaderboards.edit(...)` (omitted keeps, `None`
  clears, an object replaces); `LeaderboardScore.authors_metadata` / `.paper_metadata`.
- The Reproduce button on the leaderboard copies `sf.evaluate(pinned_cache="<id>")` (OME-1655).

## Term

The user-facing term is **pinned cache** everywhere. "Frozen copy" stays only where a page names
the wire field (`frozen_copy_id` in report JSON or the board API) or the upgrade note.

## Pages (every current mention, 2026-10-21)

| Page | Change |
|---|---|
| `learn/CachingPage.vue` | Rename the concept; "Make a pinned cache"; replace the `sf.reproduce` paragraphs with the `evaluate(pinned_cache=…)` flow, the seed rules and `limit=n`. |
| `learn/LeaderboardPage.vue` | One paragraph: the Reproduce button and `sf.evaluate(pinned_cache=…)`. |
| `sf-client/guides/LeaderboardsPage.vue` | Rewrite the reproduce section (snippets, table row, verdicts, recording, private scores with `score_id=`); add `authors_metadata` / `paper_metadata` to the submit and edit snippets and the table. |
| `sf-client/guides/EvaluationPage.vue` | The `evaluate` signature gains the replay keywords; "pinned cache" wording. |
| `sf-client/guides/Url4Page.vue` | The "check a published score" line points to `evaluate(pinned_cache=…)`. |
| `sf-client/api/ClientsPage.vue` | Remove `reproduce()`; document the two replay forms of `evaluate()` and `ReproductionError`. |
| `sf-client/api/ModulesPage.vue` | Remove `sf.reproduce()`; the module `sf.evaluate` takes the replay forms. |
| `sf-client/api/CandidateResultPage.vue` | `frozen_copy_id` → `pinned_cache`; new `reproduction` field. |
| `sf-client/api/LeaderboardsPage.vue` | `LeaderboardScore.pinned_cache`, `authors_metadata`, `paper_metadata`; `Reproduction` without `result`; where it comes from (`CandidateResult.reproduction`, `ReproductionError`). |
| `sf-client/api/ErrorsPage.vue` | Add `ReproductionError` and its two codes. |
| `navigation/sf-client.ts` | Point the source baseline at the merged SDK; switch to the released version after verification. |
| `CONTEXT.md` (glossary) | "Frozen Copy" becomes **Pinned Cache** (one line on the internal name); "Reproduction" updated; new "Partial replay". |

One **upgrade note**, on the Leaderboards guide: what changed in which release (`sf.reproduce` →
`sf.evaluate(score_id=…)`, `record=` → `record_reproduction=`, `frozen_copy_id` → `pinned_cache`,
`Reproduction.result` gone, the report JSON key unchanged).

## Checks

- `npm run build` and `npm run lint` in `public-docs` pass (the project has no test runner).
- Check changed executable Python snippets against the merged SDK with fake transports (no live
  submissions, recording or provider calls), and syntax-check the remaining examples. Check live replay
  again against the released SDK before merge (ticket acceptance). For that check, use staging
  score `5fc68454-338c-4645-bc10-a58b3e3a74e4` (pinned cache
  `69a76841-73fc-47e8-8e6f-03796f6128c3`); the public docs show placeholders.
- A search of `public-docs/src` and `CONTEXT.md` for `sf.reproduce`, `.reproduce(` and the
  `frozen_copy_id` attribute finds only the upgrade note and the wire-field mentions (a review aid,
  listed in the PR; not a test).

## Release

Owner requested ready-for-review on 2026-10-22. Merge only after the SDK release containing
#1519 is on PyPI, the snippets pass against it, and the portal snippet update (#1522) is deployed.

Source reconciliation (2026-10-22): public author identifiers normally omit email domains, but
the scoreboard retains full addresses when local parts collide. Document that actual rule.
`paper_metadata` replaces the whole object, including the link: omitting `url` clears
`paper_url`; document this explicitly along with object size limits.
