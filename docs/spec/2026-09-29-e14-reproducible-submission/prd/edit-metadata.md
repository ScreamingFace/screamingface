# PRD: Edit submission metadata — authors and paper URL (E14a)

**Source:** ticket §1 · Irina answer 2 · ans:Q1, Q16 · **Priority:** P0. It can ship first,
with no dependency on the other PRDs.
**Lifecycle:** existing (characterize, then the delta)
**Owner:** unassigned

## 1. Summary and user story

As a researcher who submitted a result before the paper existed, I want to add authors and a
paper link to my submission later, so that the leaderboard entry can be cited.

## 2. Background and constraints

- "When you submit, you can set authors and a link to a paper you have already published."
  `[stated prompt]`
- "On any submission under you, you can edit those fields later: add authors, change the paper
  URL […]" `[stated prompt]`
- Editable fields are `authors` and `paper_url` only, plus an edit history `[stated ans:Q16]`.
- "Submitter can list anyone, even if not registered […] no confirmation is needed. I think
  this is ok for now that only 1 of the authors are responsible to change the submission."
  `[stated prompt]` (Irina answer 2). So the only editor is the head owner (`Score.submitted_by`).
- Not this epic: checking that the paper URL is real, or that the authors wrote the paper
  `[stated prompt]`.
- Entities: `Score` (`paper_url`, `metadata_revision`, `metadata_updated_at`) and
  `ScoreMetadataEvent` (`erd.md` §2.1, §2.5).

### 2.1 Current behavior

- `authors` is an optional list of email addresses on submit. Up to 10 distinct people and
  up to 4,096 bytes serialized
  `[existing apps/scoreboard/src/scoreboard/scores/schemas.py:247-248]`,
  `[existing apps/scoreboard/src/scoreboard/scores/schemas.py:382]`.
- A resubmit of the same recipe returns the original row. The scoreboard ignores the new
  `authors` (content-hash dedup)
  `[existing apps/scoreboard/src/scoreboard/scores/store.py:199]`. So an author list can never
  change after the first submit.
- The public JSON strips author domains (local part only), and keeps the full address only
  when two local parts collide
  `[existing apps/scoreboard/src/scoreboard/scores/schemas.py:276-317]`.
- Routes: `POST /v1/scores`, `GET /v1/scores/{id}`. No `PATCH` exists
  `[existing apps/scoreboard/src/scoreboard/routes/scores.py:177-288]`.
- The submitter is trusted from the `X-User-Email` header only in `cloudflare_headers` mode
  `[existing apps/scoreboard/src/scoreboard/routes/scores.py:76-118]`.
- The SDK has `submit(candidate_result, *, authors=None)` and no update method
  `[existing packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:90-112]`.
- There is no `paper_url` field anywhere.

**Delta.**
- Add `paper_url` to the submit payload and to `Score`.
- Add `PATCH /v1/scores/{score_id}` for `authors` and `paper_url`, with an owner check and
  `If-Match` concurrency.
- Add `GET /v1/scores/{score_id}/metadata-history`.
- Add SDK `update_submission(...)`.
- Show the paper link on the portal.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**MD-H1** `[stated prompt]` — set the paper URL on submit.
Given a verified submitter,
when she submits with `paper_url="https://arxiv.org/abs/2609.01234"`,
then `GET /v1/scores/{id}` returns that `paper_url`, and `metadata_revision` is 1.

**MD-H2** `[stated prompt]` — add authors later.
Given Ana's head has `authors=["ana@x.org"]` and `metadata_revision=1`,
when Ana sends `PATCH /v1/scores/{id}` with
`{"authors": ["ana@x.org", "bruno@y.org"]}` and `If-Match: "1"`,
then the response is `200` with the new authors, `metadata_revision=2`, and an `ETag: "2"`.

**MD-H3** `[stated prompt]` — change the paper URL.
When Ana sends a `PATCH` with only `{"paper_url": "https://doi.org/10.1234/abc"}`,
then `paper_url` changes, and `authors` does not (a partial update).

**MD-H4** `[stated ans:Q16]` — the edit history.
Then `GET /v1/scores/{id}/metadata-history` lists one event per edit (actor, time, the
revision from and to, the fields before and after), newest first.

**MD-H5** `[stated prompt]` — an unregistered co-author.
When Ana adds `carol@z.org`, who has no account, then the scoreboard accepts it with no
confirmation (Irina answer 2).

**MD-H6** `[stated prompt]` — the SDK round trip.
When a user calls `client.leaderboards.update_submission(score_id, authors=[...],
paper_url=..., expected_revision=1)`,
then the SDK sends the `PATCH` with `If-Match: "1"` and returns the updated
`LeaderboardScore`.

### 3.2 Error paths

**MD-E1** `[stated prompt]` — a non-owner edits.
Given Bruno is not `Score.submitted_by`,
when Bruno sends a `PATCH`,
then the response is `403 not_submission_owner`, and nothing changes. On a **private** board,
the response is `404`, the same as for an unknown score. This keeps the OME-894 rule of no
existence leak `[existing apps/scoreboard/src/scoreboard/routes/scores.py:54]`.

**MD-E2** `[proposed]` — an unverified identity.
When the scoreboard runs in an auth mode that cannot verify the caller
(`identity_is_verified()` is false) and the auth mode is not `disabled`,
then a `PATCH` fails with `401 identity_not_verified`. In `disabled` mode (local, single user),
edits are allowed.

**MD-E3** `[proposed — gap §per-connection/data]` — a stale revision.
Given `metadata_revision=3`,
when a `PATCH` sends `If-Match: "2"`,
then the response is `412 metadata_revision_conflict`, with the current revision and the
current values in the body. Nothing changes.

**MD-E4** `[proposed]` — no `If-Match`.
When a `PATCH` has no `If-Match`, then the response is `428 precondition_required`. This
blocks lost updates from two tabs.

**MD-E5** `[proposed]` — an invalid paper URL.
When `paper_url` is not an absolute `https` or `http` URL, is longer than 2,048 chars, or has a
`javascript:` or `data:` scheme or embedded credentials (`user:pass@`),
then the response is `422` with the field error. Nothing changes.

**MD-E6** `[existing apps/scoreboard/src/scoreboard/scores/schemas.py:551-562]` — invalid authors.
When `authors` breaks the submit rules (more than 10 distinct people, more than 4,096 bytes,
a malformed email, or an empty list), then the response is `422` with the same messages as on
submit. The submit and the `PATCH` share one validator.

**MD-E7** `[proposed]` — clearing a field.
When a `PATCH` sends `"paper_url": null`, then the paper URL is removed.
When a `PATCH` sends `"authors": null`, then `authors` falls back to today's default: the
submitter `[existing apps/scoreboard/src/scoreboard/scores/store.py:283]`.

**MD-E8** `[proposed]` — unknown or immutable fields.
When a `PATCH` sends another field (for example `score` or `url4_expression`), then the
response is `422 field_not_editable`, and nothing changes.

### 3.3 Derived scenarios (risk order)

**MD-D1 — an edit never changes the ranking or the recipe identity** `[implied]` · H×M
When any metadata edit succeeds, then `content_hash`, `score`, `spec_id` and the rank do not
change (I-S2, I-S3).

**MD-D2 — two concurrent edits** `[proposed — gap §concurrency]` · H×M
When two `PATCH` requests with `If-Match: "1"` commit at the same time,
then exactly one succeeds (revision 2), and the other gets `412`. Enforce it with
`UPDATE … WHERE id=$1 AND metadata_revision=$2`, and check the affected row count.

**MD-D3 — the history and the row stay consistent** `[proposed — gap §per-element/store]` · H×L
The row update and the `ScoreMetadataEvent` insert happen in one transaction. A failure of
either rolls back both.

**MD-D4 — an idempotent resend** `[proposed — gap §per-flow/repeat]` · M×M
When the SDK retries a `PATCH` after a lost response, and the stored values already equal the
requested values, then the response is `200` with the current state, even though `If-Match`
is now stale. No new event is written.

**MD-D5 — the edit shows on read and on the leaderboard** `[implied]` · M×H
After an edit, `GET /v1/scores/{id}`, `GET /v1/leaderboard/{benchmark}` and the portal show the
new authors (with the published local-part form) and a paper link.

**MD-D6 — XSS through the paper URL** `[proposed — gap §security]` · H×L
The portal renders `paper_url` as an `<a href>` only after a scheme check. It sets
`rel="noopener noreferrer nofollow"` and never uses `innerHTML` with the value.

**MD-D7 — a clustered head** `[stated prompt]` · M×M
Given a head has reported results from other users,
then only the head owner can edit, and the reporters cannot (Irina: "the claim belongs to
Ana").

**MD-D8 — a legacy row** `[proposed]` · M×M
Given a row from before migration 0017 (`metadata_revision` defaults to 1),
then its owner can edit it like any other row.

**Not applicable:** a multi-step cancel (a single request). Empty state: MD-E7 covers an
empty `authors`.

## 4. Non-functional requirements

- A `PATCH` finishes in ≤ 100 ms p99 (one conditional update plus one insert) `[proposed]`.
- The metadata-history list pages by 50 `[proposed]`.
- Observability `[proposed]`: `scoreboard_metadata_edits_total{result=ok|conflict|forbidden|invalid}`.
  Log each edit with the actor and the score id, but never the full author emails (they are
  PII; log the count).
- Security: the owner check happens at the data owner (the scoreboard), on the verified
  identity only. Authors are PII: the public JSON keeps today's local-part rule.

## 5. Out of scope

- Title, abstract, code URL and other fields (`ans:Q16`).
- Co-author confirmation, or edit rights for co-authors (Irina answer 2).
- Checking the paper URL, DOI minting and BibTeX (ticket, "Not this epic").
- Editing the metadata of a `ReportedResult` (the metadata belongs to the head).

## 6. Open questions

None.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: characterization first, then the authorization and integrity core, then the
validation, then the SDK and the portal. Outside-in: route tests drive the store.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| MD-1 | CHAR `resubmit_same_recipe_ignores_new_authors` | integration | [existing store.py:199] | H×L | none |
| MD-2 | CHAR `public_json_strips_author_domains` | unit | [existing schemas.py:276] | M×L | none |
| MD-3 | `patch_by_non_owner_is_403_public_404_private_no_change` | integration | [stated prompt] MD-E1 | H×M | owner check on the verified identity |
| MD-4 | `patch_unverified_identity_401_except_disabled_mode` | integration | [proposed] MD-E2 | H×M | reuse `identity_is_verified` |
| MD-5 | `patch_owner_adds_authors_bumps_revision_and_etag` | integration | [stated prompt] MD-H2 | H×H | conditional update |
| MD-6 | `concurrent_patches_one_wins_one_412` | integration | [proposed] MD-D2 | H×M | `WHERE metadata_revision=$2` |
| MD-7 | `stale_if_match_412_with_current_state` | integration | [proposed] MD-E3 | H×M | |
| MD-8 | `missing_if_match_428` | unit | [proposed] MD-E4 | M×M | |
| MD-9 | `edit_does_not_change_content_hash_score_or_rank` | integration | [implied] MD-D1 | H×M | edit only the two fields |
| MD-10 | `history_event_written_in_same_transaction` (the insert fails, so the row rolls back) | integration | [proposed] MD-D3 | H×L | one transaction |
| MD-11 | `paper_url_rules` (table: https ok; ftp, javascript:, data:, user:pass@, 2,049 chars rejected) | unit | [proposed] MD-E5 | H×L | one validator |
| MD-12 | `patch_authors_uses_submit_validator` (11 people, 4,097 bytes, bad email) | unit | [existing schemas.py:551] MD-E6 | M×M | share the validator |
| MD-13 | `patch_null_clears_paper_url_and_resets_authors_default` | unit | [proposed] MD-E7 | M×M | |
| MD-14 | `patch_immutable_field_422` | unit | [proposed] MD-E8 | M×L | `extra="forbid"` |
| MD-15 | `idempotent_resend_same_values_200_no_event` | integration | [proposed] MD-D4 | M×M | compare before the update |
| MD-16 | `submit_accepts_paper_url` | integration | [stated prompt] MD-H1 | M×H | schema field |
| MD-17 | `metadata_history_lists_newest_first_paged` | integration | [stated ans:Q16] MD-H4 | M×M | |
| MD-18 | `reporter_of_cluster_cannot_edit_head` | integration | [stated prompt] MD-D7 | M×M | owner = `Score.submitted_by` |
| MD-19 | `sdk_update_submission_sends_if_match_and_parses` | unit (`httpx.MockTransport`) | [stated prompt] MD-H6 | M×M | new SDK method, sync and async |
| MD-20 | `portal_renders_paper_link_safely` (JS unit: scheme check, rel, textContent) | unit (portal) | [proposed] MD-D6 | H×L | |
| MD-21 | E2E `submit_then_edit_then_read_on_leaderboard` | E2E | [implied] MD-D5 | M×H | the spine |
