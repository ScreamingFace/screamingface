# PRD: Metadata you own (paper link, edit, edit log)

**Source:** prompt / ans:Q5, ans:Q7, ans:Q10 · **Priority:** P0 (Stack A, low risk, ships first)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned · **Landing:** `apps/scoreboard`, `packages/screamingface` · **PRs:** A1, A2, A3

## 1. Summary and user story

As a researcher who submits a result before the paper exists, I want to add the paper link and fix
the author list later, so that the score can be cited with the correct paper and authors.
`[stated prompt]`

## 2. Background and constraints

- "When you submit, you can set authors and a link to a paper you have already published."
  `[stated prompt]`
- "On any submission under you, you can edit those fields later: add authors, change the paper URL,
  and update the rest of that metadata." `[stated prompt]`
- "Checking that the paper URL is real, or that the named authors wrote that paper" is not this
  epic. `[stated prompt]`
- Who can edit: "Verified submitter only." `[stated ans:Q5]`
- "Keep an edit log." `[stated ans:Q7]` Who can read it: "Owner and operators only."
  `[stated ans:Q10]`

### 2.1 Current behavior

- `Score.authors` is a nullable JSON list
  `[existing apps/scoreboard/src/scoreboard/scores/models/score.py:22]`. On submit it is a list of
  email-like strings, at least 1 and at most 10 distinct, and at most 4096 bytes
  `[existing apps/scoreboard/src/scoreboard/scores/schemas.py:324]`
  `[existing apps/scoreboard/src/scoreboard/scores/schemas.py:384]`. A read derives
  `[submitted_by]` when `authors` is NULL
  `[existing apps/scoreboard/src/scoreboard/scores/store.py:324]`.
- There is no paper field. There is no PATCH or PUT route anywhere in the scoreboard.
- A **same-owner resubmit** of the same recipe can already replace `authors` and `metadata`.
  `None` means "not given" (OME-1054)
  `[existing apps/scoreboard/src/scoreboard/scores/store.py:235]`. The allowlist is
  `_REPLAY_FIELDS` (`store.py:221`).
- Identity: in `cloudflare_headers` mode, `X-User-Email` after a peer-network check. In `disabled`
  mode (dev and test), the free-text `submitted_by` from the body
  `[existing apps/scoreboard/src/scoreboard/routes/scores.py:87]`. The AIDEV-NOTE there says that a
  second authenticated write route must extract this check into a `Depends()` (`scores.py:101`).
- Private-board reads are owner-only: `score.submitted_by != identity` gives 404
  `[existing apps/scoreboard/src/scoreboard/routes/scores.py:334]`.
- The scoreboard has no admin or operator role (`apps/scoreboard/src/scoreboard/routes/`), so
  operators read through the database.
- The portal shows authors with `formatAuthors` and makes safe links with `httpUrlOrNull` and
  `link` `[existing apps/scoreboard/portal/main.js:97]` `[existing apps/scoreboard/portal/main.js:110]`
  `[existing apps/scoreboard/portal/main.js:187]`.
- The SDK's `submit(candidate_result, *, authors=None)` builds the payload in `_submission`
  `[existing packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:90]`
  `[existing packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:470]`.

### 2.2 Delta

- **A1 (scoreboard):** add `paper_url` to `Score`, to `ScoreSubmission` and to `ScoreSchema`. Add
  `paper_url` to `_REPLAY_FIELDS` with "replace when given" semantics, like `authors`. Show the link
  in the portal.
- **A2 (scoreboard):**
  - Extract a `VerifiedIdentity` dependency from `_resolve_submitter`. It runs the peer check and
    reads the header in `cloudflare_headers` mode. In `disabled` mode it trusts `X-User-Email`.
  - Add `PATCH /v1/scores/{id}`, the `score_metadata_events` table, an event on each change (from
    PATCH and from resubmit), `metadata_updated_at`, and `GET /v1/scores/{id}/metadata-events`
    (owner only).
- **A3 (SDK):** add `submit(..., paper_url=)`, `leaderboards.edit(...)`,
  `leaderboards.metadata_events(...)`, and the new fields on `LeaderboardScore`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **M1.** Given a valid `paper_url`, when the submitter posts a score, then the score stores it and
  `GET` returns it. `[stated prompt]`
- **M2.** Given a score that the caller submitted (verified identity = `submitted_by`), when the
  caller sends `PATCH /v1/scores/{id}` with `{"paper_url": "https://arxiv.org/abs/…"}`, then the
  response is `200` with the new value. `metadata_updated_at` is set, and one event records the old
  and new values. `[stated prompt]` `[stated ans:Q7]`
- **M3.** Given the same owner, when the owner sends `{"authors": [a, b, c]}`, then `authors` is
  replaced by that exact list and one event is written. `[stated prompt]`
- **M4.** Given the owner, when the owner calls `GET /v1/scores/{id}/metadata-events`, then the
  response lists the events, newest first. `[stated ans:Q10]`
- **M5.** Given the SDK, when a user calls `sf.leaderboards.edit(score_id, paper_url=…)`, then the
  SDK sends the PATCH and returns the updated `LeaderboardScore`. `[stated prompt]`

### 3.2 Error paths

- **M6.** Given a verified caller who is not `submitted_by`, then PATCH returns `403` with code
  `not_score_owner`. Nothing changes and no event is written. `[stated ans:Q5]`
- **M7.** Given no identity, then PATCH returns `401`. Given an untrusted peer, then it returns
  `403`. This is the same as the POST rules. `[existing scores.py:87]`
- **M8.** Given a private-board score and a caller who is not the owner, then PATCH and the events
  read return `404`. They do not return `403`, so the score's existence does not leak. `[existing scores.py:334]`
- **M9.** Given a caller who is not the owner, then the events read returns `403`
  (or `404` on a private board). `[stated ans:Q10]`
- **M10.** Given an invalid `paper_url` (not `http` or `https`, over 2048 characters, or with
  control characters), then POST and PATCH return `422`. `[proposed]`
- **M11.** Given invalid `authors` (empty list, more than 10, not email-like, or over 4096 bytes),
  then PATCH returns `422` with the same rules as POST. `[existing schemas.py:384]`
- **M12.** Given a PATCH body with no known field, or with an unknown field, then the response is
  `422`. `[proposed]`
- **M13.** Given a score id that does not exist, then the response is `404`. `[implied]`

### 3.3 Derived scenarios (risk-ordered)

- **M14. Two PATCHes at the same time** `[proposed]` — Impact M × Likelihood L. Given two owner
  PATCHes in parallel, then both apply in some order (the row is locked with `SELECT … FOR UPDATE`).
  The last one wins, and the log has two events whose old/new values chain without a gap.
- **M15. A resubmit changes authors** `[proposed]` — M×M. Given a same-owner resubmit with new
  `authors` or `paper_url`, then the change is applied (as today for authors) **and** one event is
  written with `source = "resubmit"`. A resubmit that changes nothing writes no event.
- **M16. An older SDK resubmits without `paper_url`** `[existing store.py:235]` — H×M. Given a
  resubmit with no `paper_url` key, then the stored `paper_url` is not changed (`None` means "not
  given").
- **M17. Clearing the paper link** `[proposed]` — M×M. Given PATCH `{"paper_url": null}`, then the
  link is removed and an event is written. On PATCH, an absent key means "unchanged" and `null`
  means "clear". `authors: null` returns `422`. To go back to the derived `[submitted_by]`, send
  `authors: [submitted_by]`.
- **M18. A PATCH that changes nothing** `[proposed]` — L×M. Given values equal to the stored ones,
  then the response is `200`, no event is written, and `metadata_updated_at` does not change (I5).
- **M19. Editing does not move the frontier** `[existing store.py:232]` — H×L. Given any PATCH, then
  `enriched_at`, the ranking and `content_hash` do not change (I3, I4).
- **M20. A row with a free-text `submitted_by`** `[stated ans:Q5]` — L×M. Given a row stored in
  `disabled` mode, then in `cloudflare_headers` mode only a verified identity equal to that text can
  edit it. In practice, nobody can.
- **M21. A dangerous paper link in the portal** `[proposed]` — H×L. Given
  `paper_url = "javascript:…"` (stopped by M10 on write), then the portal still runs it through
  `httpUrlOrNull` and does not show it as a link.
- **Retry.** A PATCH is idempotent by value. A retry after a lost response writes no second event
  (M18). `[implied]`
- **Empty state.** A score with no events returns `[]` from the events read. `[implied]`

## 4. Non-functional requirements

- **Latency** `[proposed]`: PATCH is one locked read, one update and at most one insert in one
  transaction, under 50 ms p95 on the production database.
- **Security** `[proposed]`: the events read is not public (`[stated ans:Q10]`), because it holds
  author emails that the owner may have removed on purpose. The PATCH and events routes use the
  shared `VerifiedIdentity` dependency, so the peer check cannot be skipped
  (`scores.py:101` AIDEV-NOTE).
- **Observability** `[proposed]`: log each PATCH with the score id, the changed field names and the
  status. Never log the email values.
- **Capacity** `[proposed]`: events are rare (a few per score). There is no cap.

## 5. Out of scope

- Checking that the paper exists, or that the authors wrote it `[stated prompt]`.
- DOI minting, BibTeX, a bibliography manager `[stated prompt]`.
- Editing any field other than `authors` and `paper_url` (score, url4, cost, models).
  `[proposed]` "Update the rest of that metadata" `[stated prompt]` is already covered by the
  existing resubmit path for `metadata` (`store.py:235`).
- Co-author edit rights `[stated ans:Q5]`.
- A public edit history `[stated ans:Q10]`.

## 6. Open questions

None.

## 7. TDD plan

Build order: outside-in on the scoreboard (route tests first, which pull in the store), then the
SDK. Risk order inside each PR.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR same-owner resubmit replaces `authors`; a resubmit with `authors=None` keeps them | integration | `[existing store.py:235]` | H×L | passes today |
| 2 | CHAR a private-board read by a non-owner is `404` | integration | `[existing scores.py:334]` | H×L | passes today |
| 3 | `post_stores_and_returns_paper_url` | integration | M1 | M×M | column + schema + DTO (A1) |
| 4 | `post_rejects_non_http_paper_url` (table: `javascript:`, `ftp:`, 2049 chars, control char) | unit | M10 | H×M | validator in `schemas.py` |
| 5 | `resubmit_without_paper_url_keeps_it` | integration | M16 | H×M | `paper_url` in `_REPLAY_FIELDS`, `None` = not given |
| 6 | portal: `paper link renders only for http(s)` | unit (JS) | M21 | H×L | `link(…, httpUrlOrNull(paper_url), …)` |
| 7 | `patch_by_non_owner_is_403_and_writes_nothing` | integration | M6 | H×M | `VerifiedIdentity` + owner check (A2) |
| 8 | `patch_without_identity_is_401_untrusted_peer_403` | integration | M7 | H×M | shared dependency |
| 9 | `patch_private_score_by_non_owner_is_404` | integration | M8 | H×M | reuse the private rule |
| 10 | `patch_paper_url_updates_row_sets_metadata_updated_at_and_logs_one_event` | integration | M2 | H×M | one transaction, `FOR UPDATE` |
| 11 | `patch_authors_replaces_list_with_same_validation_as_post` | integration | M3, M11 | M×M | reuse `AuthorEmail` |
| 12 | `patch_unchanged_values_writes_no_event` | integration | M18 | M×M | compare before write |
| 13 | `patch_null_paper_url_clears_null_authors_422` | unit | M17 | M×M | absent vs null |
| 14 | `patch_unknown_or_empty_body_422` | unit | M12 | L×M | `extra="forbid"`, at least one field |
| 15 | `concurrent_patches_chain_old_new_values` | integration | M14 | M×L | row lock |
| 16 | `resubmit_change_logs_event_with_source_resubmit` | integration | M15 | M×M | event write in `_apply_replay_updates` |
| 17 | `patch_does_not_touch_enriched_at_or_ranking` | integration | M19 | H×L | display-only fields |
| 18 | `events_read_owner_only_newest_first` | integration | M4, M9 | H×M | new route |
| 19 | SDK `submit_sends_paper_url_only_when_given` | unit | M1 | M×M | `_submission` (A3) |
| 20 | SDK `edit_sends_patch_and_decodes_score` (MockTransport) | unit | M5 | M×M | new method, sync and async |
| 21 | SDK `edit_maps_403_404_422_to_typed_errors` | unit | M6, M8, M10 | M×M | reuse `_response_json` error mapping |
| 22 | SDK `metadata_events_decodes_list` | unit | M4 | L×M | new method |
