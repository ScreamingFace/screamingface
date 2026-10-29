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
still holds Profile rows reaches 1.0.0 now that E5c deleted the backfill and purge commands, and
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
  `main-1ccf80a` runs `migrate_profiles` then `purge_profile_history`, then 1.0.0), and (3) the
  meaning of the 410 `legacy_profile_api_retired` routes. Sources cited:
  `docs/spec/2026-10-21-OME-1715-e5-history-cleanup.md:141-143` (C6) and `:216-217` (Q5), and the
  header of `apps/aigateway/src/aigateway/purge_profile_history.py` at `1ccf80a89`.
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
- **Commits:** one commit, `docs(aigateway): document the Stage E rollback floor and upgrade path`;
  see the PR for its sha.
- **Evidence for each statement** (all at `origin/main` `a7e5d8577`):
  - SHAs: `f7e54869b` E4b (#1516), `b66f94f08` E4a (#1491, "Profile-only credentials no longer
    resolve"), `1ccf80a89` E5b (#1573), `7cb093014` E5c (#1596, deletes `migrate_profiles.py` and
    `purge_profile_history.py`), `08f534317` E3 (#1464). The 0.2.0 (`0f40ca250`) and 0.2.1
    (`fe1b65561`) release commits are ancestors of `f7e54869b`.
  - Image tag: `.github/workflows/dev-build-aigateway.yml` tags `main-${GITHUB_SHA::7}`, amd64 only;
    its run for `1ccf80a89` concluded `success`. Release PR #512 proposes aigateway 1.0.0.
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
- **Gates:**
  - `uv run .claude/scripts/run_gates.py repo --base origin/main`: ALL GATES GREEN.
  - `uv run --no-project --with pyyaml python .github/scripts/verify_chart_wiring.py`: 121/121.
  - `uv run .claude/scripts/run_gates.py aigateway --base origin/main`: attempt 1 red on one test,
    `tests/unit/auth/test_login.py::test_unknown_user_timing_close_to_wrong_password` (7272 passed,
    1 failed, 107 skipped, coverage 94.01%). It is a bcrypt timing comparison within 10%, and the
    host load average was 30-170 on 10 cores; in isolation it passed 1 of 3 runs. This diff
    touches no Python. Attempt 2: ALL GATES GREEN.
  - No Cyrillic in the diff; every cited path exists.
- **Review:** an independent read-only review verified every claim and raised one major and
  several minor points, all fixed before commit: 1.0.0 is not released yet (now "1.0.0 or any later
  image built from `7cb093014` onward"); the backfill does not move every pair (now "where it can");
  "for good" overstated R3 (removed); Stage E shipped a purge rather than deleting the storage
  itself; the 410 envelope is cited to the route module; the purge's scope ("every account it can
  prove") and exit 4 are stated exactly; journals are copied out of the pod.
- **Deviations:**
  - Spec §4.10 item 4 (the L4c `0016` floor) is not written; it lands with L4c, per the owner.
  - The spec's "`apps/aigateway/README.md:92` and its '`profile_not_found` … retained until
    Stage E' wording": that wording lives only in `docs/diagrams/gateway-identity.md:232`, which
    is fixed; README:92 itself said "OAuth profiles", fixed.
  - Not changed, reported instead: `apps/aigateway/README.md:144` still says "mark the profile or
    connection for re-authentication" (Google OAuth expiry). It is outside the spec's list.
