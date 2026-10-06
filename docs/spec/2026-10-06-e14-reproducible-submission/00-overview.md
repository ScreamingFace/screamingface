# E14 — Each leaderboard submission is a reproducible research artifact (rebuild spec)

**Epic:** OME-1307 · **Status:** draft for owner approval · **Date:** 2026-10-06
**Base:** `origin/main` at `4d81004e1` (every `[existing …]` anchor is on this commit)

## 1. Summary

A leaderboard submission becomes a citeable, reproducible artifact in two ways:

1. **Metadata you own.** The submitter sets a paper link when they submit, and can later edit the
   authors and the paper link. Each edit goes into an edit log that only the owner and operators
   can read.
2. **A cache version for each submission.** The AI Gateway's global cache is already
   content-addressed (no user in the key), write-once and without expiry. So one request always maps
   to one stored response. A submission's cache version is therefore named by
   **url4 + benchmark revision + answer seed + cache revision**. The submission stores only the
   **cache revision** label and a **`reproducible`** status. `sf.reproduce(score)` replays the run
   with `only-if-cached`, which costs no provider spend. An exact replay is recorded on the score.

This rebuild drops the first build's freeze copy, signed receipts, replay grants, GitHub release
publishing, clustering and system naming. The first build was 24 PRs (#1158–#1181), closed on
2026-10-06.

## 2. Subsystems and ownership

| Subsystem | What E14 changes | PRs | Linear leaf |
|---|---|---|---|
| `apps/scoreboard` | `paper_url`, PATCH + edit log, cache-version columns, reproductions | A1, A2, B5 | OME-1433 |
| `apps/aigateway` | cache revision label, registry, `only-if-cached` / `cache-revision`, revisions read | B1, B2 | OME-1434 |
| `apps/screamingface-engine` | Tavily cache wiring (OME-1045), capture of revision + status, replay mode | B3, B4 | OME-1045 (B3), OME-1435 (B4) |
| `packages/screamingface` | `paper_url`, `edit`, `metadata_events`, cache-version fields, `reproduce` | A3, B6 | OME-1436 |
| `public-docs`, `CONTEXT.md` | the user guide and the glossary | C1 | filed at PR-open |
| `packages/url4` | nothing (the first build's fingerprint is not needed) | — | OME-1437 → cancel |

## 3. Source tags

Each requirement carries one tag: `[stated prompt]` (the OME-1307 epic text), `[stated ans:Qn]`
(the interview, §5), `[existing <path>:<line>]` (code on the base commit), `[implied]` (a necessary
consequence), or `[proposed]` (an engineering choice that needs sign-off with this spec).

## 4. Documents and reading order

1. `00-overview.md` — this file: the summary, the interview, the PR plan.
2. `erd.md` — the data model (scoreboard columns and tables, the gateway registry).
3. `prd/gateway-cache-revision.md` — the component that the capture and replay flows use.
4. `prd/metadata-ownership.md` — flow: paper link, edit, edit log (Stack A).
5. `prd/cache-version-capture.md` — flow: a run records its cache version, and the submission
   stores it.
6. `prd/reproduce.md` — flow: `sf.reproduce`, and recording a reproduction.
7. `contracts.md` — each connection (K1–K10).
8. `test-plan.md` — ground rules, the risk register, the levels.

Related existing specs: `docs/spec/2026-08-05-url4-cache-policy-spec.md` (E14 replaces its §8.3
`only-if-cached` rejection, for replay only), `docs/spec/2026-08-31-OME-1043-tavily-retrieval-cache.md`
(the Tavily cache that B3 wires).

## 5. Interview ledger

| Id | Question | Answer (verbatim) |
|---|---|---|
| Q1 | When a cache-key revision changes, how do old submissions replay? | "let`s go with the accept breakage + storing the cache version with each submission. So, if the cache version or method changes, old submissions could still be replayed using the old caching approach, etc." → clarified as two designs; chosen: "Keep old key functions (Recommended)" |
| Q2 | Keep the `only-if-cached` control? | "Regarding the only-if-cached, keep it." |
| Q3 | Store a key list and digest, or is url4 enough? | "but for item 2 and 3 wouldn`t url4 expression be enough?" → "yes, update the design" |
| Q4 | Web search through Tavily is not cached. What should E14 do? | "There`s a tavily caching mechanism already developed in the aigatewya (take a look at it), so this shouldn`t be a problem (let me know if you verify it and it`s not there, or if it doesn`t solve the problem)" → follow-up: "isn`t the OME-1045 already implemented/merged in the remote main branch?" (checked: it is not; see §7 item 1) |
| Q5 | Who can edit a score's authors and paper link? | "Verified submitter only (Recommended)" |
| Q6 | Should `sf.reproduce` send anything to the leaderboard? | "Record a reproduction" |
| Q7 | Keep a history of metadata edits? | "Keep an edit log" |
| Q8 | Which replays are recorded? | "Only exact replays (Recommended)" |
| Q9 | Who can record a reproduction, and how is spam stopped? | "Verified identity, multiple times (no limit of cap)" |
| Q10 | Who can see the edit log? | "Owner and operators only" |

## 6. PR plan — what each PR contributes and how

Two stacks that run in parallel. Each PR touches one component. The test numbers are in the PRDs.

```
Stack A:  A1 ──► A2 ──► A3
Stack B:  B1 ──► B2 ──┐
          B3 ─────────┴─► B4 ──► B5* ──► B6
          (* B5 stacks on A2: the scoreboard migrations are numbered in order)
Last:     C1 (after A3 and B6)
```

### Stack A — metadata you own

**A1 · scoreboard · paper link** (OME-1433)
- *Contributes:* the "link to a paper" field at submit time, which the epic asks for.
- *How:*
  - Migration `0019` adds `paper_url` and `metadata_updated_at`.
  - `ScoreSubmission` and `ScoreSchema` gain `paper_url` (`http` or `https`, at most 2048
    characters).
  - `paper_url` joins `_REPLAY_FIELDS` with "replace when given" semantics, so the existing
    same-owner resubmit can also correct it.
  - The portal shows the link through `httpUrlOrNull`.
- *Tests:* md #1, #3–#6.

**A2 · scoreboard · edit + edit log** (OME-1433)
- *Contributes:* "edit those fields later", for the verified submitter only, with an edit log that
  only the owner can read.
- *How:*
  - Extract `VerifiedIdentity` from `_resolve_submitter`, as the AIDEV-NOTE asks.
  - Migration `0020` adds `score_metadata_events`.
  - `PATCH /v1/scores/{id}` locks the row, updates it and writes one event, in one transaction.
  - The resubmit path also writes events.
  - `GET /v1/scores/{id}/metadata-events` is owner-only.
- *Tests:* md #2, #7–#18.

**A3 · SDK · metadata** (OME-1436)
- *Contributes:* the user surface for Stack A.
- *How:* `submit(..., paper_url=)`, `leaderboards.edit(score_id, authors=, paper_url=)`,
  `leaderboards.metadata_events(score_id)` (sync and async), and the new fields on
  `LeaderboardScore`.
- *Tests:* md #19–#22.

### Stack B — a cache version for each submission

**B1 · gateway · cache revision label + registry** (OME-1434)
- *Contributes:* a name for "which key function produced this row", and the guarantee that every
  old name stays computable.
- *How:*
  - All four providers register their adapter revisions.
  - The label is `cr-` + 12 hex over all the revision constants, computed at startup.
  - `revision_registry.py` holds the entries, and each entry has golden vectors.
  - `cache_key_for(label, …)` keys with any entry.
  - The header `X-AIGW-Cache-Revision` is on chat and Tavily lookup responses.
  - CI fails when the current label is not registered.
- *Tests:* gw #1–#8, #17.

**B2 · gateway · replay controls** (OME-1434)
- *Contributes:* a replay that can never pay a provider, and that can name an old revision.
- *How:*
  - `only-if-cached` and `cache-revision` in the `cache` object. They fail closed: a miss or
    bypass returns `504`, and a bad control returns `400`.
  - An old label is read-only.
  - The Tavily lookup takes `cache_revision`.
  - `GET /v1/cache/revisions`.
- *Tests:* gw #9–#16, #18–#21.

**B3 · engine · Tavily through the gateway cache** (OME-1045, a prerequisite; see §7 item 1)
- *Contributes:* web-search runs become cacheable, and therefore replayable.
- *How:* build OME-1045 as it is specified. Lookup before each Tavily call, fill after a success,
  and reuse the gateway HTTP client. The Tavily credential stays in the engine.
- *Tests:* the OME-1045 list.

**B4 · engine · capture + replay mode** (OME-1435)
- *Contributes:* each run knows its cache revision and whether it can be replayed. A replay run
  sends the controls on every call.
- *How:*
  - The readback parses `X-AIGW-Cache-Write` and `X-AIGW-Cache-Revision`.
  - `RunCacheCounters` adds `cache.revision`, `cache.reproducible` and the `cache.partial.*`
    counts.
  - `X-Cache-Replay` sets replay mode. Replay mode means: the controls on every chat body, no
    `max-age` re-issue, no Tavily call on a miss, a K10 check at start, and the ack in the start
    response.
  - A replay miss fails the case with `replay_cache_miss`.
- *Tests:* cv #1, #2, #4–#13; rp #2–#6, #23.

**B5 · scoreboard · cache version + reproductions** (OME-1433)
- *Contributes:* "a submission records the cache version that belongs to it", and the record of
  exact reproductions.
- *How:*
  - Migration `0021` adds `cache_revision`, `reproducible` and `answer_seed` (fill-only on
    resubmit), and the `score_reproductions` table.
  - `POST /v1/scores/{id}/reproductions` (verified identity, no cap, exact numbers only).
  - `reproduction_count` and `last_reproduced_at` on `ScoreSchema`.
  - The portal count.
- *Tests:* cv #16–#18; rp #7–#14.

**B6 · SDK · capture + reproduce** (OME-1436)
- *Contributes:* the user-facing replay.
- *How:*
  - `CandidateResult` gains `cache_revision` and `reproducible`.
  - `submit` sends them and `answer_seed`.
  - `sf.reproduce(score, *, record=True)` checks the status, then runs
    `evaluate(score.url4, answer_seed=…)` with `X-Cache-Replay`, sorts the result into exact,
    failed or not reproducible, and records an exact replay.
- *Tests:* cv #14, #15; rp #15–#22.

**C1 · docs · guide + glossary** (a leaf is filed at PR-open)
- *Contributes:* users can find the feature and trust it.
- *How:*
  - `public-docs` caching and leaderboards guides: edit authors and the paper later, the edit log,
    `sf.reproduce`, what `partial` means, and why a different SDK or engine version can fail a
    replay.
  - `CONTEXT.md` gains the terms Cache Revision, Reproducible, and Reproduction.
- *Tests:* docs build.

**Size:** Stack A is about 3 days. Stack B is about 7 days, including B3. In total, about 10 working
days, which matches the owner's L estimate on the epic. The edit log, the reproductions and B3 were
added after the first M estimate.

## 7. Deferred questions (each with a recommended default)

1. **B3 (OME-1045) in E14.** The owner expected the Tavily cache to be complete (`ans:Q4`). Only the
   gateway half is merged (PR #782). The engine half, OME-1045, is in Backlog and unassigned, and no
   code calls the lookup route (checked on `4d81004e1`). **Default:** build OME-1045 as B3, under
   its own ticket, as a blocker of B4. Without it, every run that uses the engine's web search is
   `partial`.

## 8. Global assumptions

- Production runs the scoreboard in `cloudflare_headers` identity mode. `disabled` mode is for dev
  and test only. `[existing apps/scoreboard/src/scoreboard/routes/scores.py:87]`
- The gateway is deployed before the engine for each release. If not, the K10 check and the ack
  refuse a replay. They never let it pay. `[proposed]`
- Grading is deterministic when the model and tool answers are the same. LLM judges go through the
  gateway, so they are cached too. `[implied]`
- The global cache stays without expiry. If eviction is ever added, the stored labels and the
  `reproducible` status show which runs depend on the rows. That is a future decision. `[proposed]`
