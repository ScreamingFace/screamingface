# PRD: Publish a cache version to GitHub, and admin takedown

**Source:** ticket §2 and Irina's "pinned or published repo" comment · ans:Q2, Q5, Q6, Q9, Q10 · **Priority:** P1
(E14's P0 value, a reproducible replay, works without publishing. Publishing makes the
artifact external and citable.)
**Lifecycle:** planned
**Owner:** unassigned

## 1. Summary and user story

As the reporter of a result on a public board, I want to publish its frozen cache version to
a public repo when my paper ships, so that anyone can download and cite the exact cache that
produced my score. As a platform admin, I want to take a published version down for a license
or legal reason, without deleting the leaderboard result.

## 2. Background and constraints

- Irina: "Likely should pull cached results to a 'pinned' or 'published' repo rather than
  continuing to use the cache for their storage." `[stated prompt]`
- Published versions go to a public published repo `[stated ans:Q2]` on GitHub (one release
  per version) `[stated ans:Q5]`.
- Private-board and gated-benchmark versions never go to the public repo. They stay in the
  private bucket, owner-only `[stated ans:Q6]`.
- Publishing is an owner opt-in. A version is frozen privately at submit time, and the owner
  runs a publish action later `[stated ans:Q9]`.
- A published version is immutable for its owner. Only an admin can take it down, and the
  result row keeps a "withdrawn" marker `[stated ans:Q10]`.
- Entities: `CacheVersionPublication` with its state table (`erd.md` §2.6), `VersionArchive`
  (`erd.md` §3.5), `PublishedRelease` (`erd.md` §4). `Benchmark.redistributable` (`erd.md` §2.7).

### 2.1 Current behavior

- There is no publish path and no GitHub integration in the scoreboard.
- The scoreboard has no admin role. The gateway has one: an email allowlist plus an audit log
  on `/v1/admin` `[existing apps/aigateway/src/aigateway/routes/admin.py:75-94]`. This PRD
  copies that pattern.
- The weekly cache snapshot is an operator backup, not a per-submission artifact
  `[existing apps/aigateway/src/aigateway/core/snapshot_scheduler.py:40-52]`.

**Delta.**
- A publish route and worker in the scoreboard.
- A GitHub App integration.
- Read-only bucket access for the scoreboard.
- A scoreboard admin allowlist and a withdraw route.
- The SDK method `publish_cache_version`.
- A portal "Published" link and a "Withdrawn" marker.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**PB-H1** `[stated ans:Q9]` — the owner opts in.
Given Ana's result X on a public, redistributable board has version V, with publication
state `private`,
when Ana calls `client.leaderboards.publish_cache_version(result_id=X)` (or uses the portal
button),
then `POST /v1/results/{X}/publish` returns `202`, with `state=requested`.

**PB-H2** `[stated ans:Q5]` — the worker publishes.
Given state `requested`,
then the worker:
1. leases the row;
2. reads `cache-versions/<V>/entries.jsonl.gz` and `manifest.json` from the bucket;
3. checks that the bytes hash to `ReportedResult.cache_version_sha256`;
4. creates release `cv-<V>` in `ScreamingFace/screamingface-cache-versions`, with both files
   as assets;
5. sets `state=published`, `release_url` and `published_at`.

**PB-H3** `[proposed]` — what the release shows.
The release body states:
- the system name and revision, the benchmark id and revision;
- the score, the reporter and the authors (published local-part form, the same as the portal
  `[existing apps/scoreboard/src/scoreboard/scores/schemas.py:276-317]`);
- `paper_url`, the scoreboard link, the entry count, the coverage, and `archive_sha256`;
- the line "Metadata as of <published_at>. The current metadata is on the scoreboard page."

The asset bytes equal the bucket archive (the same digest).

**PB-H4** `[stated ans:Q10]` — the admin takes it down.
Given X is `published`,
when an admin calls `POST /v1/admin/results/{X}/withdraw {"reason": "license: <text>"}`,
then:
1. the state becomes `withdrawn`, with `withdrawn_at`, `withdrawn_by` and `withdrawn_reason`;
2. the worker deletes the GitHub release and its tag;
3. the result row stays on the leaderboard with a "Withdrawn" marker;
4. non-owners can no longer get a replay grant (RP-E3).

### 3.2 Error paths

**PB-E1** `[stated ans:Q6]` — not eligible.
When the board is private, or `redistributable=false`, or the result has no version, then
the publish route returns `409 not_publishable`, with a `reason` of
`private_board|not_redistributable|no_cache_version`.

**PB-E2** `[proposed]` — not the owner.
When the caller is not the result's `reporter`, then the route returns `403 not_result_owner`.
It returns `404` if the result sits on a private board.

**PB-E3** `[stated ans:Q10]` — publish after a takedown.
When the state is `withdrawn`, then the route returns `409 withdrawn`.

**PB-E4** `[proposed]` — GitHub is down, or rate-limited (5xx, 429, a secondary-limit 403).
The worker keeps `state=requested`, increments `attempts`, and sets `next_attempt_at` with
exponential backoff and jitter (1 min base, 1 h cap). It honors `Retry-After`. After 8
attempts, the state becomes `failed`, with a sanitized `last_error`. The owner can publish
again, which resets the attempts.

**PB-E5** `[proposed — gap §data]` — the archive digest does not match, or the archive is
missing.
The worker sets `state=failed`, with `last_error=archive_mismatch|archive_missing`. It never
uploads, and it raises the alert `scoreboard_publish_integrity_failures_total > 0`. This
failure is not retryable by the owner. An operator must repair it.

**PB-E6** `[proposed]` — local mode, or no GitHub App configured.
The publish route returns `503 publish_unavailable`. The state does not change.

**PB-E7** `[proposed]` — a non-admin calls withdraw.
The route returns `403 admin_required`. The attempt is logged in the admin audit.

### 3.3 Derived scenarios (risk order)

**PB-D1 — a retried publish never makes two releases** `[proposed — gap §per-connection/sync]` · H×M
Given the worker created release `cv-<V>` but crashed before it set `published`,
when it retries,
then it finds the release by tag. If the release's `manifest.json` digest matches, it sets
`published` and uploads nothing. If the digest differs, it sets `failed` with
`release_conflict`, and alerts.

**PB-D2 — two workers, one job** `[proposed — gap §concurrency]` · H×M
When two scoreboard replicas poll at the same time, then only one leases a row
(`SELECT … FOR UPDATE SKIP LOCKED`, `lease_until = now + 10 min`). An expired lease can be
taken again.

**PB-D3 — a takedown during a publish** `[proposed — gap §concurrency]` · H×L
Given the worker holds a lease on X and an admin withdraws X,
then the withdraw commits `withdrawn`. The worker re-reads the state before its final write.
When it sees `withdrawn`, it deletes the release it just made, and it does not set
`published`.

**PB-D4 — the GitHub delete fails during a takedown** `[proposed]` · H×L
The state is `withdrawn` at once (the source of truth is the scoreboard). A cleanup flag
`release_delete_pending` is retried by the worker with the PB-E4 backoff until GitHub
returns `204` or `404`. The alert `scoreboard_withdraw_cleanup_pending` fires when it stays
pending for more than 1 h.

**PB-D5 — a double click** `[proposed — gap §per-flow/repeat]` · M×H
Publishing a row that is `requested` or `published` returns `202` or `200` with the current
state (no-op, the state table in `erd.md` §2.6).

**PB-D6 — a takedown of a never-published version** `[stated ans:Q10]` · M×L
An admin can withdraw a version in state `private`, for example for a legal claim on its
content. The effect is that non-owners cannot replay it. No GitHub call happens.

**PB-D7 — the GitHub credential scope** `[proposed — gap §external]` · H×L
The scoreboard uses a GitHub App installation token that can write contents only on the
cache-versions repo. The App private key comes from a Secret and is never logged. The token
lasts 1 h, and the worker mints one per job.

**PB-D8 — the scoreboard reads the bucket only** `[proposed]` · M×L
The scoreboard's bucket credentials are read-only, on the `cache-versions/` prefix. Only the
gateway writes the archives (`erd.md` §3.5).

**PB-D9 — content in the release is untrusted** `[proposed — gap §security]` · M×L
Model outputs in the assets can hold any text. The release body holds only fields that the
scoreboard generates (escaped Markdown), never raw model text.

## 4. Non-functional requirements

- A publish finishes in ≤ 5 min p95 after the request, when GitHub is healthy `[proposed]`.
- A 40 MB archive uploads within a 120 s timeout per asset `[proposed]`.
- Observability `[proposed]`:
  - `scoreboard_publish_jobs{state}` (a gauge)
  - `scoreboard_publish_attempts_total{result}`
  - `scoreboard_publish_integrity_failures_total`
  - `scoreboard_withdraw_cleanup_pending`
  - an admin audit log line for each withdraw attempt (actor, result id, reason, outcome)
- Security: the admin allowlist is `SCOREBOARD_ADMIN_EMAILS`, and it works only in the
  verified auth mode (the same rule as the gateway `[existing apps/aigateway/src/aigateway/routes/admin.py:75-94]`).
  In production, that mode is `cloudflare_headers` (`ans:Q22`), so the owner of a publish and
  the admin of a withdraw are the verified `X-User-Email` identity. In the `disabled` dev and
  local fallback, publish and withdraw answer `503`. The WIRING unit reuses this allowlist for
  the admin route that sets `Benchmark.redistributable` (`ans:Q23`, `contracts.md` C10).

## 5. Out of scope

- A DOI for each release (ticket, "Not this epic").
- Publishing to Hugging Face (rejected in `ans:Q5`).
- An owner withdraw (rejected in `ans:Q10`).
- Re-syncing the release body after a metadata edit (PB-H3 states the time).

## 6. Open questions

None.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: the eligibility and ownership rules (they block data exposure) first, then integrity
and idempotency, then concurrency, then the takedown, then the SDK and the portal. The GitHub
adapter sits behind a `ReleasePublisher` port. Use a fake for unit tests, and a recorded
contract fixture for the adapter.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| PB-1 | `publish_private_board_or_not_redistributable_409_reason` | integration | [stated ans:Q6] PB-E1 | H×M | eligibility check |
| PB-2 | `publish_by_non_reporter_403_private_404` | integration | [proposed] PB-E2 | H×M | owner = `reporter` |
| PB-3 | `archive_digest_mismatch_fails_without_upload_and_alerts` | unit | [proposed] PB-E5 | H×L | hash before upload |
| PB-4 | `retry_after_crash_finds_release_by_tag_no_duplicate` | unit (fake) | [proposed] PB-D1 | H×M | GET by tag first |
| PB-5 | `release_by_tag_with_other_digest_fails_release_conflict` | unit | [proposed] PB-D1 | H×L | |
| PB-6 | `owner_publish_202_requested` | integration | [stated ans:Q9] PB-H1 | H×H | state machine |
| PB-7 | `worker_publishes_assets_and_sets_published` | integration (fake) | [stated ans:Q5] PB-H2 | H×H | |
| PB-8 | `only_one_worker_leases_a_row` | integration (Postgres) | [proposed] PB-D2 | H×M | SKIP LOCKED |
| PB-9 | `withdraw_during_publish_deletes_new_release_no_published` | integration | [proposed] PB-D3 | H×L | re-read before the final write |
| PB-10 | `admin_withdraw_sets_withdrawn_deletes_release_keeps_row` | integration | [stated ans:Q10] PB-H4 | H×M | |
| PB-11 | `withdraw_github_delete_failure_marks_cleanup_pending_and_retries` | unit | [proposed] PB-D4 | H×L | |
| PB-12 | `non_admin_withdraw_403_and_audited` | integration | [proposed] PB-E7 | H×L | copy the gateway allowlist pattern |
| PB-13 | `publish_after_withdraw_409` | unit | [stated ans:Q10] PB-E3 | M×L | |
| PB-14 | `github_5xx_429_backoff_then_failed_after_8` | unit | [proposed] PB-E4 | M×M | honor `Retry-After` |
| PB-15 | `republish_from_failed_resets_attempts` | unit | [proposed] PB-E4 | M×L | |
| PB-16 | `double_publish_is_noop` | unit | [proposed] PB-D5 | M×H | |
| PB-17 | `withdraw_never_published_blocks_replay_no_github_call` | integration | [stated ans:Q10] PB-D6 | M×L | |
| PB-18 | `release_body_has_generated_fields_only_escaped` | unit | [proposed] PB-H3 PB-D9 | M×L | template |
| PB-19 | `publish_unavailable_503_without_app_config` | unit | [proposed] PB-E6 | M×L | |
| PB-20 | `github_adapter_contract` (recorded fixtures: create release, upload asset, get by tag, delete) | integration | [proposed] contracts C7 | M×M | adapter |
| PB-21 | `sdk_publish_cache_version_and_portal_links` | unit | [stated ans:Q9] | M×M | |
| PB-22 | E2E `submit_publish_download_asset_digest_matches_version` | E2E | [stated ans:Q5] | H×M | against a sandbox repo, run nightly |
