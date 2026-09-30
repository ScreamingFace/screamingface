# E14 reproducible submissions — plan index (OME-1307)

Spec (the rubric): `docs/spec/2026-09-29-e14-reproducible-submission/` (approved).
Plans: this directory, one file for each unit: `docs/plan/2026-09-29-e14-reproducible-submission/<ID>.md`.
Language: ASD-STE100. A Sonnet implementer builds each unit with the `sdlc-python` loop (the
stack card of the unit's component). The user decisions D1 to D7 (2026-09-29) and the wave 1
review decision D8 (2026-09-29) are binding. They override older plan text and spec text (§7).

## Status (2026-09-30)

**Done.** Every unit is built and merged into `e14-reproducible-submission-spec` (D1). The
final-check fixes are merged too. The table gives the merge commit of each unit (from
`git log --merges`).

| Wave | Unit | Merge commit |
|---|---|---|
| W1 | URL4-fp | `9ed2fb1f` |
| W1 | SB-schema | `dc09fc99` |
| W1 | GW-capture | `04cc7359` |
| W2 | ENG-freeze | `97f906c2` |
| W2 | SDK-meta | `c0dc7be5` |
| W2 | SB-meta | `a2bebf4e` |
| W2 | SB-registry | `1dd6e813` |
| W2 | GW-freeze | `6d553ff0` |
| W3 | ENG-replay | `893e1f0b` |
| W3 | SDK-submit | `75819093` |
| W3 | SB-submit | `9078d2bf` |
| W3 | GW-replay | `1ce4d93f` |
| W4 | SDK-replay | `b46c5a97` |
| W4 | SB-grants | `b28308bd` |
| W4 | SB-publish | `0f727708` |
| W5 | WIRING | `093330ec` |
| W5 | E2E | `86b0145b` |
| final | fixes `apps/screamingface-engine` (RP-X1) | `50b4950c` |
| final | fixes `packages/screamingface` (RP-X2) | `594ec5a4` |
| final | fixes `apps/scoreboard` (FS-1, X-SEC-1, MRA-1, MRA-2) | `0e2ab15f` |

**Final-check fixes (2026-09-30).** Each fix has a RED-first test in the owning component.

- **RP-X1 (engine).** A grant call that ends non-2xx (not `403 replay_grant_invalid`) now counts
  as a version miss. Before, no side counted it, so a failed replay could show "complete".
  Spec: `contracts.md` C12. Ledger: `docs/work/2026-09-30-e14-final-apps-screamingface-engine.md`.
- **RP-X2 (SDK).** The SDK reads the Engine refusal code from the top-level problem `code`
  first, and uses `type` only when `code` is absent. Spec: `contracts.md` "Error bodies".
  Ledger: `docs/work/2026-09-30-e14-final-packages-screamingface.md`.
- **FS-1 (scoreboard).** `reported_result.run_id` is `VARCHAR(255)`, as wide as
  `IdempotencyKey.key`. Before, a key of 129 to 255 characters gave a 500 with clustering on.
  Migration 0018 is changed in place (E14 is not released). Spec: `erd.md`.
- **X-SEC-1 (scoreboard).** A replay claim checks `pinned_baseline_result_id` with the same board
  and replay access rules as the result id. Spec: `contracts.md` C4 "Trust".
- **MRA-1 (scoreboard).** `cli.py` configures the `scoreboard` logger, so the admin audit line
  is written in production.
- **MRA-2 (scoreboard).** A successful admin action writes a second line, `admin_change`, with
  the before and after values. Spec: `contracts.md` C10 "Admin checks".
  Ledger (FS-1, X-SEC-1, MRA-1, MRA-2): `docs/work/2026-09-30-e14-final-apps-scoreboard.md`.

**Gates and E2E.**

- All 5 stacks (`scoreboard`, `aigateway`, `screamingface-engine`, `screamingface`, `url4`):
  `run_gates.py` ALL GATES GREEN against `origin/main`. The append-only check flags only the
  approved exceptions (below) and the drift of `main`.
- `verify_chart_wiring.py`: 128/128 checks pass.
- Docker E2E lane on the e14 branch: 15 passed, 1 skipped. PB-22 skips (nightly only). RP-22 is dropped (Q30).
- No paid provider call was made.

**Open items for the owner.** Each item has the question, the default that the code uses now,
and where it is recorded.

| # | Question | Default now in the code | Recorded in |
|---|---|---|---|
| ~~1~~ | ~~RP-22 needs a zero-spend fixture for a changed recipe (a paid owner run).~~ | **Dropped (owner, 2026-09-30, Q30):** no paid run is used as a test. The RP-22 test is removed. | `E2E.md` §9 OD-4; `docs/work/2026-09-29-e14-e2e.md` |
| 2 | PB-22 needs a sandbox GitHub repo, a GitHub App, the secrets `E14_SANDBOX_APP_ID`, `E14_SANDBOX_APP_PRIVATE_KEY`, `E14_SANDBOX_APP_INSTALLATION_ID`, and the variable `E14_SANDBOX_REPO`. | The test skips until they exist. | `E2E.md` §9 OD-5; E2E ledger D-7 and "Open items"; `tests/e2e/test_e14_publish_nightly.py` |
| 3 | D5 ops precondition: route the prod scoreboard host through the Cloudflare Access/Envoy edge before the `values-prod.yaml` `cloudflare_headers` switch ships. | Not code. The prod archive is `none` and publish is off until it is done. | `WIRING.md` §9 item 1; §8 "Ops" below; `apps/scoreboard/DEPLOYMENT.md` "E14 deploy wiring" |
| 4 | RP-X1: must a grant call with NO HTTP response (transport failure) also count as a version miss? | **Decided (user, 2026-09-30, Q26):** not counted. No code change. | `docs/work/2026-09-30-e14-final-apps-screamingface-engine.md` "Deviations" |
| 5 | X-SEC-1: enforce `pinned_baseline_result_id == replay.result_id` (strict)? The strict rule needs a rewrite of `test_replay_run_stores_provenance_and_label`. | **Decided (user, 2026-09-30, Q27):** keep it as is: same board and same replay access rules as the result id. No code change. | `docs/work/2026-09-30-e14-final-apps-scoreboard.md` "Deviations" (2); `contracts.md` C4 "Trust" |
| 6 | MRA-1/MRA-2: a durable `admin_audit_events` table instead of a log line? | **Decided (user, 2026-09-30, Q28):** a log line (`admin_action`, `admin_change`). No audit table. | `docs/work/2026-09-30-e14-final-apps-scoreboard.md` "Deviations" (5); `contracts.md` C10 "Admin checks" |
| 7 | RP-X2: must a coded `503 replay_unsupported` be `permanent=True` in the SDK? | **Decided (user, 2026-09-30, Q29):** transient (`status >= 500` rule). No code change. | `docs/work/2026-09-30-e14-final-packages-screamingface.md` "Deviations" |
| 8 | Linear: the leaf issue under OME-1307, the `docs/tasks/` mirror and the `OME-N` branch rename are not done. | Deferred by the user. Ledgers keep `ticket: unfiled`. | this section; `docs/work/2026-09-29-e14-reproducible-submission-spec.md` |
| 9 | Approved append-only exceptions to review in the PR: the visibility-exit guard rows, `public_surface_snapshot.json`, the pinned aigateway 0012 migration test, and the additive conftest / E2E harness / README edits. | Kept as approved. | `docs/work/2026-09-29-e14-sb-submit.md`, `-sb-publish.md` (guard rows); `-sdk-meta.md`, `-sdk-submit.md`, `-sdk-replay.md` (snapshot); `-gw-capture.md` (0012 test); `-e2e.md` (harness, README) |

The older open items of §8 stay as recorded there, with the defaults that the code uses.

## 1. Delivery model (D1)

- All units land on ONE branch: `e14-reproducible-submission-spec`.
- There is no PR for each unit, no Linear issue for each unit, and no CI merge gate for each unit.
- Build each unit in its own temporary worktree, on the branch `unit/<ID>`, made from the HEAD of
  the e14 branch at the start of the wave:
  `git checkout -B unit/<ID> e14-reproducible-submission-spec`.
- Commit on `unit/<ID>` only. Use conventional commits. Do not add a `Refs:` line. Do not add
  `Co-Authored-By`. Do not merge the unit branch yourself.
- Run the gates with the e14 branch as the base:
  `--base "$(git merge-base HEAD e14-reproducible-submission-spec)"`. The append-only test check
  must see only the changes of this unit.
- Each unit keeps its own work ledger in `docs/work/` (the plan names the file). Start it before
  the first RED.
- After each wave, the integrator merges the unit branches of that wave into the e14 branch, in
  the order of §2, and runs the gates of each merged unit on the e14 branch. The next wave starts
  from that HEAD.
- A later-wave unit always builds on the merged result of the earlier waves. It never waits for a
  unit of its own wave.

## 2. Wave table (D2)

| Wave | Units | Integration (merge) order inside the wave | Why |
|---|---|---|---|
| W1 | SB-schema, URL4-fp, GW-capture | any order (no shared file); recommended URL4-fp first, because it owns the one-line `apps/screamingface-engine/uv.lock` change | no code dependencies; three components |
| W2 | SB-meta, SB-registry, GW-freeze, ENG-freeze, SDK-meta | **SB-meta before SB-registry**; the others in any order | SB-meta and SB-registry need SB-schema; SB-registry needs URL4-fp; GW-freeze needs GW-capture; ENG-freeze and SDK-meta use fakes |
| W3 | SB-submit, GW-replay, ENG-replay, SDK-submit | any order (no shared file) | SB-submit needs SB-registry and SB-meta; GW-replay needs GW-freeze; SDK-submit needs SDK-meta; ENG-replay uses fakes |
| W4 | SB-grants, SB-publish, SDK-replay | **SB-grants before SB-publish**; SDK-replay in any place | SB-grants and SB-publish need SB-submit and SB-meta; SDK-replay needs SDK-submit |
| W5 | WIRING, E2E | **WIRING before E2E** | WIRING needs the settings and routes of W1 to W4; E2E needs all product units and WIRING (as built: direct import, no fallback) |

The scoreboard chain (SB-schema → SB-meta/SB-registry → SB-submit → SB-grants/SB-publish →
WIRING) is the critical path.

Check of the dependency lists (done in this pass): no `depends_on` of any plan points to a unit in
the same wave or a later wave. The same-wave items are merge-order notes only, not code
dependencies:

- SB-registry names SB-meta (W2) for merge order only (`SB-registry.md` §2).
- SB-publish names SB-grants (W4) for merge order only (`SB-publish.md` §2).
- E2E names WIRING (W5). As built, the integrator merged WIRING first, and the E2E review
  removed the planned fallback: the harness imports the WIRING hook directly (`E2E.md` §2).
- ENG-replay has no code dependency; ENG-freeze (W2) only touches the same `CHANGELOG.md`.

## 3. Units

| Unit | Wave | Component | Depends on (code, all in earlier waves) | Owned test ids | Plan |
|---|---|---|---|---|---|
| SB-schema | W1 | `apps/scoreboard` | — | SCH-1..SCH-13 (plan-local) | `SB-schema.md` |
| URL4-fp | W1 | `packages/url4` (+ one line of `apps/screamingface-engine/uv.lock`, X-25) | — | SR-2, SR-3, SR-4, SR-5 (url4 half); C11 row 1 purity (no id) | `URL4-fp.md` |
| GW-capture | W1 | `apps/aigateway` | — | CV-1..CV-6, CV-24, CV-26, CV-28; capture NFR (no id) | `GW-capture.md` |
| SB-meta | W2 | `apps/scoreboard` | SB-schema | MD-1..MD-18, MD-20 | `SB-meta.md` |
| SB-registry | W2 | `apps/scoreboard` | SB-schema, URL4-fp | SR-1, SR-6..SR-20; SR-5-SB, SR-H3-SB, BF-1..BF-7, C11-SB-1..3 (plan-local) | `SB-registry.md` |
| GW-freeze | W2 | `apps/aigateway` | GW-capture | CV-7..CV-15, CV-22, CV-23, CV-25, CV-27; freeze NFR (no id) | `GW-freeze.md` |
| ENG-freeze | W2 | `apps/screamingface-engine` (+ `.claude/scripts/check_layering.py`) | — | SC-21 (split SC-21a..l) | `ENG-freeze.md` |
| SDK-meta | W2 | `packages/screamingface` | — | MD-19 | `SDK-meta.md` |
| SB-submit | W3 | `apps/scoreboard` | SB-registry, SB-meta (and so SB-schema, URL4-fp) | SC-1..SC-17, SC-22; SC-17a results-list NFR (plan-local) | `SB-submit.md` |
| GW-replay | W3 | `apps/aigateway` | GW-freeze (and so GW-capture) | CV-16..CV-21, RP-5; replay NFR (no id) | `GW-replay.md` |
| ENG-replay | W3 | `apps/screamingface-engine` | — | RP-11..RP-15 | `ENG-replay.md` |
| SDK-submit | W3 | `packages/screamingface` | SDK-meta | SC-18, SC-19, SC-20 | `SDK-submit.md` |
| SB-grants | W4 | `apps/scoreboard` | SB-submit, SB-meta (and so SB-registry, SB-schema) | RP-1..RP-4, RP-6..RP-10 | `SB-grants.md` |
| SB-publish | W4 | `apps/scoreboard` | SB-submit, SB-meta (and so SB-schema) | PB-1..PB-20 | `SB-publish.md` |
| SDK-replay | W4 | `packages/screamingface` | SDK-submit (and so SDK-meta) | RP-16..RP-20, PB-21 | `SDK-replay.md` |
| WIRING | W5 | scoreboard + aigateway charts, `apps/scoreboard` admin route, `packages/screamingface/_runtime`, chart CI | SB-schema, SB-submit, SB-grants, SB-publish, GW-capture, GW-freeze, GW-replay, SDK-replay | WR-1..WR-9, KG-1..KG-7, LR-1..LR-6, CH-1..CH-15 (plan-local) | `WIRING.md` |
| E2E | W5 | `packages/screamingface/tests/e2e` + workflows | all W1..W4 units; WIRING (as built: direct import) | MD-21, SC-23, RP-21, PB-22 | `E2E.md` |

## 4. Test-id coverage

All 135 PRD ids have exactly one owner (RP-22 is dropped, Q30) (counted from the `prd/*.md` §7 tables):

| Prefix | PRD count | Owners |
|---|---|---|
| SR | 20 | URL4-fp 2-5 (4); SB-registry 1, 6-20 (16) |
| CV | 28 | GW-capture 1-6, 24, 26, 28 (9); GW-freeze 7-15, 22, 23, 25, 27 (13); GW-replay 16-21 (6) |
| MD | 21 | SB-meta 1-18, 20 (19); SDK-meta 19; E2E 21 |
| SC | 23 | SB-submit 1-17, 22 (18); SDK-submit 18-20 (3); ENG-freeze 21; E2E 23 |
| RP | 21 | SB-grants 1-4, 6-10 (9); GW-replay 5; ENG-replay 11-15 (5); SDK-replay 16-20 (5); E2E 21 |
| PB | 22 | SB-publish 1-20; SDK-replay 21; E2E 22 |

SR-5 has one owner (URL4-fp, the url4 half). The scoreboard half is the plan-local id SR-5-SB in
SB-registry. Both read the same frozen oracle
`packages/url4/tests/fixtures/fingerprint_vectors.json` (with `binding` and `exclude_bindings`, D3).

Plan-local ids (they own no PRD row):

- SB-schema: SCH-1..SCH-13.
- SB-registry: SR-5-SB, SR-H3-SB, BF-1..BF-7 (`backfill_systems`), C11-SB-1..3 (layering).
- SB-submit: SC-17a (results-list p99, PostgreSQL).
- WIRING: WR-1..WR-9 (admin route), KG-1..KG-7 (key helper), LR-1..LR-6 (local runtime hook),
  CH-1..CH-15 (charts and chart CI).
- Sub-split rows of one PRD id carry a letter suffix and belong to that id: SC-21a..l, RP-11a…,
  RP-13c, RP-14e, and the `disabled`-fallback rows MD-4a, MD-17a, SC-8a, SC-17b, RP-2a, PB-2a,
  PB-12a (D5).
- NFR and guard tests with no id: capture p99 (GW-capture), freeze of 5,000 entries (GW-freeze step
  15b), replay hit p99 (GW-replay step 12), C11 purity of `url4.fingerprint` (URL4-fp T7).

## 5. Migrations

| Service | Current head | New | Unit |
|---|---|---|---|
| scoreboard | `0016_score_enriched_at.py` | `0017_e14_score_metadata_columns.py`, `0018_e14_registry_and_results_tables.py` (includes `reported_result.replay_repeated_key_collapses`), `0019_e14_backfill_original_results.py` | SB-schema only |
| aigateway | `0012_provider_credential_slots.py` | `0013_cache_versions.py` (five tables) | GW-capture only |

No other unit adds a migration. Each consumer plan has a STOP rule: if `makemigrations` writes a
file, or a column is missing, stop and ask. All migrations are expand-only (safe for a rolling
rollout). The engine, the SDK and `packages/url4` have no database.
D8: every FK column has the Tortoise native name `<attr>_id`. No FK sets `source_field`, and no
migration has a `RunSQL` that renames a column. After each migration set, `makemigrations` (and the
aigateway autodetector test) must propose no change.

## 6. Integration notes (shared files and merge order)

The rule: a same-wave overlap is allowed only when both changes are additive. Each unit puts its
lines in its own block with a `FEATURE: OME-1307 (E14) …` comment, so the merge has no
overlapping hunk. The integrator keeps both blocks. A lock file is never merged by hand: keep both
`pyproject.toml` entries, run `uv lock` again in that project, then `uv lock --check`.

| Wave | Shared files | Order | Merge rule |
|---|---|---|---|
| W1 | none | URL4-fp first (recommended) | — |
| W2 | `apps/scoreboard/src/scoreboard/main.py`; `.github/workflows/scoreboard-tests.yml` (SB-meta, SB-registry). Possible: `apps/scoreboard/pyproject.toml`, `apps/scoreboard/uv.lock` if SB-meta adds a dependency | SB-meta, then SB-registry | keep both; the SB-registry `app.state.system_registry` line goes after the SB-meta lines; no duplicate path line in the workflow |
| W3 | none | any | — |
| W4 | `config.py`, `main.py`, `metrics.py`, `scores/schemas.py` (append at the END), `DEPLOYMENT.md` under `apps/scoreboard/` (SB-grants, SB-publish) | SB-grants, then SB-publish | keep both blocks; SB-publish block below the SB-grants block; if both add `app.state.clock`, keep one line |
| W5 | none expected (WIRING and E2E touch different files) | WIRING, then E2E | if an overlap shows, both changes are additive: keep both |

Files that one track changes across waves (no same-wave conflict; each later unit starts from the
merged HEAD and appends):

- aigateway: `core/cache_versions/ports.py`, `__init__.py`, `stats.py`, `config.py`, `main.py`,
  `routes/chat.py`, `DEPLOYMENT.md`, `tests/unit/cache_versions/conftest.py`
  (GW-capture W1 → GW-freeze W2 → GW-replay W3; WIRING W5 adds one `DEPLOYMENT.md` section).
- engine: `CHANGELOG.md` (ENG-freeze W2 → ENG-replay W3, one line each under `## Unreleased`);
  `apps/screamingface-engine/uv.lock` (URL4-fp W1 only).
- scoreboard: `.claude/sdlc.local.md` (SB-meta W2 → SB-submit W3, X-19); `scoreboard-tests.yml`
  (SB-schema W1 → SB-meta/SB-registry W2 → SB-submit W3 → SB-publish W4); `routes/admin.py`
  (SB-publish W4 → WIRING W5, audit line only); `scores/schemas.py`, `main.py`, `DEPLOYMENT.md`
  (every scoreboard unit appends).
- SDK: `leaderboard.py`, `_scoreboard/leaderboards.py`, `client.py`, `leaderboards.py`,
  `_core/ports.py`, `CHANGELOG.md`, `README.md`, `public_surface_snapshot.json`
  (SDK-meta W2 → SDK-submit W3 → SDK-replay W4); `_runtime/signing_keys.py` and
  `_runtime/server.py` (SDK-replay W4 → WIRING W5).

Cross-track contracts with no shared file (the plans use the same shapes; no merge order is
needed): GW-replay ↔ ENG-replay (`X-AIGW-Cache-Version`, `Cache-Status … key="<prefix>"`, the 403
body); ENG-replay ↔ SDK-replay (the start-request header and the counter frame, X-5, X-7);
SB-registry ↔ SDK-replay (the mirrored pin grammar, X-21); SB-submit ↔ SDK-submit (the C4 payload
keys).

### 6.1 Env var names (WIRING vs the consumer plans)

Checked in this pass. Every name in the WIRING §4.8.4 table is the name that the consumer plan's
settings class reads, and the SDK-replay §4.12 key table uses the same five key names:

| Owner (settings) | Names |
|---|---|
| GW-capture §4.1 | `AIGW_CACHE_VERSIONS_ENABLED` |
| GW-freeze §4.1 | `AIGATEWAY_RECEIPT_SIGNING_KEY`, `AIGW_CACHE_VERSION_ARCHIVE_BACKEND`, `AIGW_CACHE_VERSION_ARCHIVE_DIR`, `AIGW_CACHE_VERSION_S3_{ENDPOINT_URL,BUCKET,REGION,ACCESS_KEY,SECRET_KEY,TIMEOUT_S}`, `AIGW_CACHE_VERSION_{MAX_ENTRIES,MAX_ARCHIVE_BYTES,EXPORT_POLL_S}` |
| GW-replay §4.1 | `AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS`, `AIGW_REPLAY_GRANT_CACHE_TTL_S` |
| SB-submit §4.1 | `SCOREBOARD_CLUSTERING_ENABLED`, `SCOREBOARD_RECEIPT_PUBLIC_KEYS` |
| SB-grants §4.1 | `SCOREBOARD_REPLAY_GRANT_SIGNING_KEY`, `SCOREBOARD_REPLAY_GRANT_SIGNING_KID` |
| SB-publish §4.1 | `SCOREBOARD_ADMIN_EMAILS`, `SCOREBOARD_GITHUB_{APP_ID,APP_INSTALLATION_ID,APP_PRIVATE_KEY,REPO,API_URL}`, `SCOREBOARD_PUBLIC_BASE_URL`, `SCOREBOARD_ARCHIVE_{BACKEND,S3_ENDPOINT_URL,S3_BUCKET,S3_REGION,S3_ACCESS_KEY_ID,S3_SECRET_ACCESS_KEY,FS_ROOT}`, `SCOREBOARD_PUBLISH_{WORKER_ENABLED,POLL_INTERVAL_S}` |
| existing (D5) | `SCOREBOARD_AUTH_MODE`, `SCOREBOARD_ALLOWED_NETWORKS`, `FORWARDED_ALLOW_IPS`, `AIGW_AUTH_MODE`, `AIGW_ALLOWED_NETWORKS` |

There is no `AIGATEWAY_RECEIPT_SIGNING_KID`: the receipt kid is derived (X-4).

### 6.2 Small cross-plan fixes made in this pass

1. (Superseded as built: the E2E review removed the fallback; see `E2E.md` §2 and §4.1.)
   `E2E.md` §4.1: the placeholders `WIRING_HOOK_MODULE` / `WIRING_HOOK_FUNCTION` now hold the WIRING
   names (`screamingface._runtime.local_features`, `apply_local_e14_environment`). The fallback now
   also sets the two archive backends to `filesystem`, as the WIRING `ARCHIVE_ENV_GROUP` does
   (before, the fallback set only the two dirs, so the gateway backend stayed `none`). The
   archive-dir placeholders now name `AIGW_CACHE_VERSION_ARCHIVE_DIR` and
   `SCOREBOARD_ARCHIVE_FS_ROOT`. Step 1.2 checks the backends too.
2. `E2E.md` §4.3: the admin allowlist placeholder is now `SCOREBOARD_ADMIN_EMAILS`, and step 5 names
   the WIRING route `PUT /v1/admin/benchmarks/<board>/redistributable` with its body.
3. `SB-registry.md` §2.3: the `apps/scoreboard/DEPLOYMENT.md` row said that SB-meta adds a section.
   SB-meta does not change that file (SB-meta §3), so the row now says "no overlap in wave 2".

Older cross-plan fixes (still in the plans): the SB-submit ↔ SB-registry call shape
(`resolve_for_submit(...)`, `Resolution(...)`); `replay_repeated_key_collapses` in SB-schema 0018
(no `0020`); I-S1 `uidx_scores_public_head` in SB-grants; `trace_id` in the SDK-submit payload;
the derived receipt kid and raw base64 keys in SDK-replay and E2E; the `key="<prefix>"` member on a
GW-replay version hit.

## 7. Decisions record (D1 to D8, 2026-09-29)

| Decision | What | Closes |
|---|---|---|
| D1 | One branch, unit branches `unit/<ID>` from the e14 HEAD, integrator merges after each wave; no unit PR, Linear issue or merge gate | the per-unit PR / Linear wording; X-17 release-order part (all units ship together); X-25 sub-issue part; SDK-meta and SDK-submit "release order" |
| D2 | The five-wave map of §2, with the same-wave merge orders | X-1 |
| D3 | `system_fingerprint(linked, binding="candidate", exclude_bindings=frozenset({"_sf_recipe"}))`; a Candidate-declared seed stays in the hash; no binding hashes the whole canonical url4 | X-10 (URL4 OD-1, OD-2, OD-5; SR-H3) |
| D4 | Grant `exp = iat + 43,200 s`; no refresh; a grant that expires mid-run fails the run with the typed error (RP-14 path); A3 "[checked] false, accepted" | X-2 (SB-grants OD-1, GW-replay OD-R2, ENG-replay item 2, E2E OD-7) |
| D5 | Production identity is the existing `cloudflare_headers` mode (peer check, then `X-User-Email`) for scoreboard and gateway; `disabled` is dev/local only and keeps today's behaviour | X-11 (SB-submit OD-2, OD-5; SB-grants OD-2; SB-publish OD-2, OD-4; SB-registry OD-R10; SB-meta OD-M3; SB-schema OD-S3); X-24 parts (E2E OD-2, OD-6) |
| D6 | New WIRING unit (W5): admin `redistributable` route, both charts and Secrets, `charts.yml` / `verify_chart_wiring.py`, key helper, `screamingface up` flags and archive dir; ingress routing is an ops precondition | X-12, X-13, X-14 (GW OD-F6), E2E OD-3, OD-9 |
| D7 | Engineering defaults | X-3, X-4, X-5, X-6, X-7, X-8, X-15, X-16, X-18, X-19, X-20, X-21, X-22, X-23, X-25 |
| D8 | Wave 1 review (orchestrator, 2026-09-29; spec `00-overview.md` §4.2 Q25). (a) Every FK column uses the Tortoise native name `<attr>_id`; no custom FK `source_field` and no rename `RunSQL` anywhere in E14. `reported_result.head_id` (was `score_id`); FK attributes `replayed_from_result` / `pinned_baseline_result` with the columns `replayed_from_result_id` / `pinned_baseline_result_id`; `cache_version_entry.blob_id` (was `blob_sha256`). (b) The two replay FKs are `ON DELETE NO ACTION` (`fields.OnDelete.NO_ACTION`), not `RESTRICT`. (c) The url4 `exclude_bindings` removes only an inert source, else `ExcludedBindingError` → `422 invalid_url4` (as built in `packages/url4`). (d) One approved line edit in the aigateway 0012 migration test (GW-capture §7.2) | the root cause: Tortoise 1.1.8 overwrites an FK `source_field` with `<attr>_id` at init (`tortoise/apps.py:205`), so a custom FK column does not go through the migration state; SQLite checks `RESTRICT` row by row inside a `CASCADE`. Changes SB-schema §4.5, §5, §6, OD-S2; SB-submit; SB-grants; SB-registry; GW-capture §5, §6, §7.2; GW-freeze; GW-replay; URL4-fp; D3 |

D7 in detail: X-3/X-23 no new shared package (PyJWT EdDSA behind service-local ports; SigV4
copied); X-4 raw base64 keys, JSON `{kid: b64}` maps, receipt kid `sha256(raw public key)[:16]`,
grant kid from `SCOREBOARD_REPLAY_GRANT_SIGNING_KID`; X-5 the replay header rides `GET /?q=`; X-6
C11 row 3 = "no `jwt` import outside `screamingface_engine/auth/`"; X-7 the counter frame contract;
X-8 coded error body `{"detail": {"code", "message", ...}}`; X-15 counters stay in process; X-16
`archive_sha256` = sha256 of the gzip bytes (mtime 0, level 9); X-18 C11 by unit tests (ENG-freeze
still extends `check_layering.py`); X-19 editing `.claude/sdlc.local.md` is allowed; X-20
`httpx.MockTransport` in the SDK; X-21 the pin grammar is mirrored, and a time with no UTC offset is
refused on both sides; X-22 one url4 cap, 32,000 chars with 422; X-25 the engine `uv.lock` line
rides with URL4-fp. D3 amendment (D8 (c)): `exclude_bindings` removes a named source only when it
has a text value, the explicit weight `0.0`, and no `$name` reference in the rest of the system;
else `ExcludedBindingError` (a `Url4Error`, code `malformed_source`). Unit-local open decisions take the plan default and are marked
"decided (default)" in each plan.

## 8. Still open

Only these items are still open after D1 to D8. None blocks the start of W1. Each has the default
that the implementer uses if nobody answers.

| Item | Where | Question | Default if nobody answers |
|---|---|---|---|
| OD-M7 | SB-meta §9 (W2) | `LeaderboardEntry.paper_url` breaks the append-only guard `tests/unit/test_multiple_authors.py:225-250`. (a) approve a one-line fixture edit and one gate run with `--skip-append-only`, or (b) put `paper_url` only on `RankedLeaderboardEntry` and `HistorySubmission` | (b): it needs no gate bypass. The SB-meta plan still has a STOP at this point; the implementer asks first, and uses (b) only when there is no answer |
| X-17 | ENG-replay §11 item 5; WIRING §9 item 6 | Confirm the drained engine rollout: an old worker ignores the grant and runs live (no `CURRENT_SPEC_VERSION` bump) | drained rollout, as the existing rule says; no spec-version bump |
| G4 | SB-submit §9 | Backfill `0019` takes `run_id` from the raw `metadata.run_id`; on a private board the key should be the scoped `sfp-` token, so a pre-E14 private resend can make a duplicate result | keep `0019` as written; record the limit in the SB-submit ledger |
| OD-6 | SB-publish §9 | No unit adds `publication_state` to the leaderboard row or the portal "Published"/"Withdrawn" markers | not in E14: the state is in the results-list JSON (SB-submit) and the SDK return value (SDK-replay); no portal change |
| X-9 | URL4-fp, SDK-submit §9 | erd §2.3.2 says the SDK also calls the fingerprint; the SDK sends no fingerprint, so no SDK half of SR-5 exists | no SDK half; parity is url4 half + SR-5-SB on the shared vectors file |
| OD-4 (X-24) | E2E §9 | RP-22 needed a zero-spend fixture with a changed recipe | Dropped (owner, 2026-09-30, Q30): no paid run is used as a test |
| OD-5 (X-24) | E2E §9 | PB-22 needs a sandbox repo, a GitHub App and the secrets `E14_SANDBOX_APP_ID`, `E14_SANDBOX_APP_PRIVATE_KEY`, variable `E14_SANDBOX_REPO` | PB-22 skips cleanly until they exist |
| NFR | URL4-fp §1.2, SB-registry §1.2 | The fingerprint NFR (64 KB in ≤ 50 ms) has no test; the 32,000-char cap (X-22) makes a 64 KB input impossible | no timing test |
| Ops | WIRING §9 | Not code: route the prod scoreboard host through the Cloudflare Access/Envoy edge before the new `values-prod.yaml` (see `docs/work/2026-08-03-OME-404-authenticated-leaderboard-submissions.md:94-98`); keys, bucket, GitHub App, admins | the ops checklist in WIRING §9; production archive `none` and publish off until done (OD-W3) |
