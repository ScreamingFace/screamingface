---
ticket: OME-1780
stack: aigateway
status: done
started: 2026-10-29
finished: 2026-11-02
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
(the L4c `0016` downgrade floor) lands with L4c. The first three rounds describe no L4a/L4c
behaviour, since the `quarantined` state and the `X-Profile` compatibility path still existed on
main. After L4a merged (`e915d8037`, #1614) the branch was rebased onto it and spec §4.10 item 5
(the `quarantined` precondition) was added.

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
- After L4a merges: spec §4.10 item 5 in `DEPLOYMENT.md` (the count, remediation and recount
  before an image that includes L4a, naming its merge commit), and the pre-L4a
  `409 credential_pair_unresolved` sentence leaves `DEPLOYMENT.md` and
  `docs/diagrams/gateway-identity.md`.

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

- DEPLOYMENT.md carries the Stage E section with items 1–3 and 5 of spec §4.10, each with its
  source.
- The three wording fixes are in, and each new statement matches `origin/main`.
- Gates green; review findings fixed or reported.

## Outcome

- **Actual files:** the four planned docs, this ledger and the mirror
  `docs/tasks/2026-10-29-OME-1780-stage-e-operator-docs.md`; in the fifth round also
  `docs/diagrams/gateway-identity-flow.{mmd,svg,png}` and `docs/spec/2026-10-29-ome-1138-closeout.md`
  §4.2. No code, no test.
- **Commits:**
  - PR #1612, squash-merged on 2026-11-02 as `969d4e303` from its branch head `ea5a19532`:
    `8788c1be6` `docs(aigateway): document the Stage E rollback floor and upgrade path`,
    `f9cb59432` `docs(aigateway): apply the review decisions to the Stage E operator docs` and
    `ea5a19532` `docs(aigateway): name the E5c boundary by commit and fix the Google OAuth note`.
  - The follow-up PR, branch `OME-1780-l4a-precondition-docs` from `969d4e303`:
    `aaeccd62a` `docs(aigateway): state the L4a quarantined precondition and drop the pre-L4a 409
    wording`, `dee09b5cb` `docs(aigateway): stop the gateway for the L4a remediation and scope the
    ambiguity rule`, and this record.

  #1612 merged before the rebased branch (onto `e915d8037`) and its fourth and fifth commits were
  pushed, so those two land in the follow-up PR. The files they touch were identical at
  `969d4e303` and at the rebased third commit, so both applied without conflict.
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
  - Fourth round, after the rebase onto `e915d8037`: `uv run .claude/scripts/run_gates.py repo
    --base origin/main`: ALL GATES GREEN. The diff touches no Python and no chart.
  - Fifth round: see that entry below.
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
- **Fourth round, after L4a merged (2026-10-30):** rebased onto `origin/main` `e915d8037`.
  - `DEPLOYMENT.md` gains "Before an image that includes L4a (`e915d8037`, #1614)": a backup, the
    two counts, the two `UPDATE` statements and the recount, as in spec
    `docs/spec/2026-10-29-ome-1138-closeout.md` §4.2 and §4.10 item 5, and what a pair set to
    `none` means (one active Connection serves it, two or more are `409 connection_ambiguous` and
    list `error`, none means the user connects again). The upgrade path's second step points to it.
    The step-1 paragraph on the backfill no longer says a `quarantined` pair answers `409`.
  - `docs/diagrams/gateway-identity.md`: the `409 credential_pair_unresolved` sentence is replaced
    by the two marker states and a pointer to `DEPLOYMENT.md`.
  - Evidence: table `provider_credential_slots` and columns `migration_state`, `migration_note`
    (`core/provider_access/models/provider_credential_slot.py`); a stored `quarantined` raises
    `PairAuthorityDataError`, so chat answers 500, the listing fails and the inventory raises
    `CredentialAuthorityUnavailable` (L4a, `pair_authority.py`).
  - The chart sentence was stale: `git log 1ccf80a89..e915d8037 -- apps/aigateway/charts/aigateway`
    lists one commit, `143d4bcf8` (#1606), which adds the opt-in `remoteEndpoints` block.
    `helm template` with default values renders the same at both commits except the randomly
    generated JWT secret and admin password. The text now says so and keeps the block unset for
    the E5b-era step.
- **Fifth round, review of the fourth commit (2026-11-02):** two findings, both confirmed in code.
  - Blocking: the remediation ran next to live pre-L4a writers. At `1ccf80a89` (and unchanged at
    `fed613da2`) `writer_floor.claim_pair` writes back the observed state, effective reference and
    note through `PairAuthorityStore.advance`, a compare-and-set on `generation`
    (`UPDATE … WHERE generation = expected`, then `expected + 1`). The documented `UPDATE`s leave
    `generation` alone, so a writer that observed `quarantined` before them still wins after them.
    The widest window is OAuth: the start claims and keeps the published pair in
    `PendingAuthEntry.observed_pair` (`routes/oauth_connections.py`, in memory, TTL 600 s), and the
    callback claims it again (`routes/auth.py:651`). Lead decision: stop every pre-L4a replica
    through Helm (`--set replicaCount=0`, then `kubectl wait --for=delete` on the gateway Pods), run
    the count, both updates and a `DO` check in one transaction with `lock_timeout` 5 s and
    `statement_timeout` 15 s under `psql -v ON_ERROR_STOP=1`, then upgrade to the L4a image with an
    explicit `replicaCount`. Scaling through Helm rather than `kubectl scale` keeps the replica
    count a release value, so the L4a upgrade sets it back without relying on how Helm merges a
    field changed out of band. The SQL block, cut from the doc, ran on a throwaway local PostgreSQL
    16: with 1 `quarantined` and 2 noted rows it committed and left both counts 0 with
    `generation` unchanged; with a trigger that keeps a note, the `DO` check raised, `psql` exited
    3 and nothing changed. The Deployment name and Pod labels come from `helm template aigw` of
    this chart (`aigw-aigateway`; `app.kubernetes.io/instance`, `app.kubernetes.io/component:
    gateway`). Spec §4.2 gains a dated amendment saying the same; the 2026-10-30 runs found no
    `quarantined` row before the change, so none could be written back there.
  - Accuracy: `gateway-identity.md` said any pair with several active Connections answers
    `409 connection_ambiguous`. `connection_backed.resolve` at `e915d8037` serves a migrated pair
    with an effective reference from that Connection (`_served_by_reference`); only a pair without
    one goes through label selection, where two or more active rows are ambiguous. The prose (which
    predates this PR on main) and the flow diagram's two `alt` branches now say so. The `.mmd`
    source, the inline block, the SVG and the 2x PNG were updated together, rendered with Mermaid
    CLI 12.0.0 as in the previous render, and the PNG was inspected.
  - Gate: `uv run .claude/scripts/run_gates.py repo --base origin/main`: ALL GATES GREEN.
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
    Settled 2026-10-30: the owner's remediation (spec §4.2) sets such a row to `none`, and the
    census found 0 `quarantined` rows in dev, stage and prod; the fourth round documents it per
    §4.10 item 5.
  - `docs/spec/2026-10-29-ome-1138-closeout.md` is cited for "permanent" at the lead's request; it
    reaches main with PR #1607.
  - Fifth round: the governing spec §4.2 is amended in this docs PR, on the lead's decision, so the
    runbook and the spec give the same procedure.
