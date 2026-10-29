---
ticket: OME-1780
stack: aigateway
status: done
started: 2026-10-29
finished: 2026-10-29
---

# stage-e-operator-docs — document the Stage E rollback floor and upgrade path for operators

## Intent

Close-out leaf L10 of epic `OME-1138` (findings OPS-3, OPS-1, P-F6, OPS-4, critic-4). Stage E
retired the Profile credential storage, but the gateway's operator docs say nothing about what that
means for a running install: which images may still run after the E5b purge, how an install that
still holds Profile rows gets past E5c now that E5c deleted the backfill and purge commands, and
what the 410 `legacy_profile_api_retired` answers mean. Three docs also still describe Profile-era
behaviour or promise a rename that will not happen. This unit writes everything that is true on
`origin/main` today. Docs only.

Governing artifacts (landing via another PR):

- spec `docs/spec/2026-10-29-ome-1138-closeout.md` §4.10 and §8;
- plan `docs/plan/2026-10-29-ome-1138-closeout.md` §2 and §3 "L10".

Owner decision: L10 runs in parallel now, with everything that is true today. Spec §4.10 item 4
(the L4c `0016` downgrade floor) lands with L4c. Nothing here describes L4a/L4c behaviour, since
the `quarantined` state and the `X-Profile` compatibility path still exist on main.

## Planned changes

- `apps/aigateway/DEPLOYMENT.md`: a Stage E section under "Migrations", after the `0010` note,
  with (1) the rollback floor after the E5b purge (no image older than E4b `f7e54869b`),
  (2) the upgrade path for an install that still holds Profile rows (an E5b-era image such as
  `main-1ccf80a` runs `migrate_profiles` then `purge_profile_history`, then an image built from
  `7cb093014` or later), and (3) the meaning of the 410 `legacy_profile_api_retired` routes.
  Sources cited: `docs/spec/2026-10-21-OME-1715-e5-history-cleanup.md:141-143` (C6) and
  `:216-217` (Q5), and the header of `apps/aigateway/src/aigateway/purge_profile_history.py` at
  `1ccf80a89`.
- `apps/aigateway/charts/aigateway/README.md`: the "encrypted profile-default index" sentence
  (key construction has read no stored default since OME-1323).
- `apps/aigateway/README.md`: "OAuth profiles created in this mode" (auth-disabled mode).
- `docs/diagrams/gateway-identity.md`: the `profile_not_found` "retained until Stage E" prose;
  R3 keeps the code, so the promised rename goes.

## Test plan

Docs only, no RED. Verification instead:

- Every factual statement checked against `origin/main` code, the git history and the dev-build
  workflow: the two SHAs (`git cat-file`, `git log`), the image tag scheme
  (`.github/workflows/dev-build-aigateway.yml`), the dev build of `1ccf80a89` succeeded, E5c
  deleted both commands, the CLI flags at `1ccf80a89`, the 410 route table and envelope, the
  cache-key construction path, the anonymous-account ownership, the `profile_not_found` emitter
  and decoder.
- Every path cited in the touched text exists.
- `uv run .claude/scripts/run_gates.py aigateway` and `uv run .claude/scripts/run_gates.py repo`
  green; `uv run --no-project --with pyyaml python .github/scripts/verify_chart_wiring.py` green
  (the chart README is touched).
- No Cyrillic in the staged diff.
- Independent read-only review of the diff before PR.

## Acceptance

- DEPLOYMENT.md carries the Stage E section with items 1–3 of spec §4.10, each with its source.
- The three wording fixes are in, and each new statement matches `origin/main`.
- Gates green; review findings fixed or reported.

## Outcome

- **Actual files:** the four planned docs, this ledger and the mirror
  `docs/tasks/2026-10-29-OME-1780-stage-e-operator-docs.md`. No code, no test.
- **Commits:**
  - `8788c1be6` `docs(aigateway): document the Stage E rollback floor and upgrade path`;
  - `f9cb59432` `docs(aigateway): apply the review decisions to the Stage E operator docs`;
  - `docs(aigateway): name the E5c boundary by commit and fix the Google OAuth note` (see the PR).
- **Evidence for each statement** (all at `origin/main` `a7e5d8577`):
  - SHAs: `f7e54869b` E4b (#1516), `b66f94f08` E4a (#1491, "Profile-only credentials no longer
    resolve"), `1ccf80a89` E5b (#1573), `7cb093014` E5c (#1596, deletes `migrate_profiles.py` and
    `purge_profile_history.py`), `08f534317` E3 (#1464). The 0.2.0 (`0f40ca250`) and 0.2.1
    (`fe1b65561`) release commits are ancestors of `f7e54869b`.
  - Image tag: `.github/workflows/dev-build-aigateway.yml` tags `main-${GITHUB_SHA::7}`, amd64 only;
    its run for `1ccf80a89` concluded `success`. No release version is named: release PR #512 is
    settled only when it regenerates after #1607, so the docs name the E5c commit instead.
  - CLI flags and exit codes from `git show 1ccf80a89:` of both commands, `backfill_apply.py` and
    `history_purge.py` (purge `--apply` needs `--journal`; backfill exits 3 on a lost race; purge
    exits 4 on a skip, a kept legacy row or unproven rows; `unmigrated_document` skip).
  - 410: `routes/legacy_profiles_retired.py` (13 routes, `detail` envelope, `Cache-Control`,
    `include_in_schema=False`) and `tests/unit/test_legacy_profile_routes_retired.py`.
  - Cache key: `core/request_cache/global_keys.py`, `routes/chat_cache_stage.py`, `routes/chat.py`
    stage 1 (no stored default read since OME-1323).
  - Auth-disabled Connections: `core/oauth/store.py` `ensure_anonymous_account`.
  - `profile_not_found`: `routes/provider_access_http.py` `render_refusal`; SDK decoder
    `packages/screamingface/src/screamingface/_engine/catalog.py:341`; spec OME-1209 R3 and Q2.
  - Second round (lead decisions on two independent reviews):
    - Chart unchanged and no migration added: `git diff --stat 1ccf80a89 origin/main --
      apps/aigateway/charts` and `-- apps/aigateway/src/aigateway/migrations` are both empty. The
      chart's `job-migrate.yaml` is a `pre-install,pre-upgrade` hook on the same image, and
      `image.tag` overrides `Chart.AppVersion`.
    - Purge precondition: spec `docs/spec/2026-10-21-OME-1715-e5-history-cleanup.md:153` (E5a or
      later on every replica) and `:156-160` (why). E5a is `8cb1e54e0` (#1541), an ancestor of
      `1ccf80a89`.
    - Exit 2: both commands' `main()` at `1ccf80a89` return `EXIT_USAGE` (2) on `NoMasterKey`.
      Exit 4: `PurgeReport.refused()` = a skipped account, `legacy_index` starting `kept_`, or
      `kept_unproven_rows > 0`.
    - Backfill dispositions `migrated` / `quarantined` / `none` with a per-pair `category`
      (`backfill_classify.py`, `backfill_apply.py` `PairRecord`).
    - Resolution on main: `connection_authority.migrated_target` (revoked or gone → 404
      `profile_not_found`, pending → 409 `profile_pending_auth`, error → 401 `auth_required` with
      `reauth_url`); `connection_backed.resolve` refuses a `quarantined` pair with
      `PairNotManageable("unresolved")`, rendered as 409 `credential_pair_unresolved`; an unmigrated
      pair is served only from a single active row (`_active_connection`); `main.py` wires
      `SelectorPolicy.REJECT_EXPLICIT`.
    - 0.2.0 (`aigateway-v0.2.0`): `core/credential_store.py` wraps the OS secret manager (macOS
      `security`, Linux `secret-tool`, Windows `keyring`); the Profile index lived there, not in the
      database. 0.2.1 (`fe1b65561`) already used `credential_blobs`.
  - Third round, Google OAuth 401/403 (`apps/aigateway/README.md:142-144`): `gemini_provider` and
    `antigravity_provider` return `status_code in (401, 403)` from
    `should_mark_credential_error_on_dispatch_status`, and their `_is_expired` treats a missing
    `expires_at_ms` as not expired. Neither defines `classify_dispatch_operational_outcome`, and
    `connection_backed.begin_dispatch` returns no observation for a non-API-key target, so
    `routes/chat_dispatch.py` `_dispatch_failure_response` takes `record_dispatch_failure`, not
    the operational-outcome path. That marks the Connection through
    `OAuthConnectionStore.mark_error` (`record_dispatch_failure_migrated` for a migrated pair,
    `mark_error_checked` otherwise, which skips the mark if the pair moved since it was
    observed): an `active` row becomes `error` with the message, and an OAuth row's label is
    parked under `error:<id>` so a re-authentication can create a fresh row.
- **Gates:**
  - `uv run .claude/scripts/run_gates.py repo --base origin/main`: ALL GATES GREEN (before each of
    the three commits).
  - `uv run --no-project --with pyyaml python .github/scripts/verify_chart_wiring.py`: 121/121.
  - `uv run .claude/scripts/run_gates.py aigateway --base origin/main`: attempt 1 red on one test,
    `tests/unit/auth/test_login.py::test_unknown_user_timing_close_to_wrong_password` (7272 passed,
    1 failed, 107 skipped, coverage 94.01%). It is a bcrypt timing comparison within 10%, and the
    host load average was 30-170 on 10 cores; in isolation it passed 1 of 3 runs. This diff
    touches no Python. Attempt 2: ALL GATES GREEN. The pre-push run of the first commit: ALL GATES
    GREEN. PR #1612 CI on the first commit: every check passed. The pre-push runs of the second
    and third commits: ALL GATES GREEN.
  - No Cyrillic in the diff; every cited path exists.
- **Review:** an independent read-only review verified every claim and raised one major and
  several minor points, all fixed before commit: 1.0.0 is not released yet (the first commit said
  "1.0.0 or any later image built from `7cb093014` onward"; later rounds name no version); the
  backfill does not move every pair (now "where it can"); "for good" overstated R3 (removed);
  Stage E shipped a purge rather than deleting the storage itself; the 410 envelope is cited to the
  route module; the purge's scope ("every account it can prove") and exit 4 are stated exactly;
  journals are copied out of the pod.
- **Second round, after the PR opened:** the lead's decisions on both reviews were applied in a
  second commit: the Stage B / Stage E opening sentence; the E5a-on-every-replica precondition and a
  Helm-only upgrade (this repository's chart, `--set image.tag=main-1ccf80a`, pre-upgrade migration
  Job, commands in that pod); a backup before each `--apply`; `kubectl cp` of the journals before a
  restart; the backfill's `quarantined` / `none` report; the three exit-4 cases and exit 2; local
  SQLite and 0.2.0 excluded; no release version named ("an image built from `7cb093014` or later");
  repo-root path for the route module; the closeout spec §7 for "permanent"; and the four
  credential-resolution refusals in `gateway-identity.md`.
- **Third round:** the lead's follow-up was applied in a third commit: the E5c boundary sentence is
  "No image built from `7cb093014` onward, including any release cut after it, …", and
  `apps/aigateway/README.md:144` now says a Google OAuth 401/403 marks the Connection `error` for
  re-authentication.
- **Deviations:**
  - Spec §4.10 item 4 (the L4c `0016` floor) is not written; it lands with L4c, per the owner.
  - The spec's "`apps/aigateway/README.md:92` and its '`profile_not_found` … retained until
    Stage E' wording": that wording lives only in `docs/diagrams/gateway-identity.md:232`, which
    is fixed; README:92 itself said "OAuth profiles", fixed.
  - Added on the lead's decision: `apps/aigateway/README.md:144` (Google OAuth expiry), outside the
    spec's list but gateway operator docs. It said "mark the profile or connection for
    re-authentication"; the code marks the Connection's lifecycle status `error` through
    `mark_error`, not an operational outcome, and the text now says so.
  - The decision messages disagreed on naming 1.0.0 ("the first release after E5c (1.0.0)" vs
    "don't name 1.0.0"); the final decision names commits only, because the release version is not
    settled until #512 regenerates after #1607.
  - Not written as asked: "those users reconnect the provider through the Connection API" holds
    only for a pair left `none`. On main a `quarantined` pair fails closed before any Connection is
    read, and a native create, OAuth start, key replacement or delete on it keeps the state
    (`connection_native.claim_native_write`, "no auto-promotion"), so a new Connection does not
    clear it; the code comment says only the offline backfill can settle such a pair, and E5c
    deleted it. The docs state exactly that and name no remedy. Open question for the owner.
  - `docs/spec/2026-10-29-ome-1138-closeout.md` is cited for "permanent" at the lead's request; it
    reaches main with PR #1607.
