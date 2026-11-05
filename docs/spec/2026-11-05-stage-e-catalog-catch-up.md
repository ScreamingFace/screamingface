---
ticket: OME-1839
parent: OME-1138
status: accepted  # owner decisions 2026-10-29 and 2026-11-05 (§8)
created: 2026-10-29
---

# Stage E catalog catch-up — retire the Profile-era models from the AIGateway catalog (OME-1138)

Owner decisions taken 2026-10-29: retired cards become `deprecated`, not deleted; the exporter and
projector are edited locally; scope is the full catch-up (one leaf, one PR in
`screamingface-design`). The decisions taken after the baseline check on 2026-11-05 are in §8.

## 1. Problem

The AIGateway catalog in `screamingface-design` was last projected from gateway source at
`d35a46537` (2026-09-29), before Stage E. Since then E3 (`OME-1651`, #1464) retired the legacy Profile
routes and their request/response models, and E5c (`OME-1759`, #1596, `7cb093014`) deleted
`core/profile_models.py` and `core/profile_index.py`. The E5 spec (§6) and the epic spec (§10, §11
"Cleanup (E)") required the catalog change to ship with the class retirement; it did not.

Consequences on `main` today:

- `solutions/_tools/export_contracts.py:210` imports `Profile` and `ProfileIndex` from
  `aigateway.core.profile_models`; the export fails with `ImportError`.
- `solutions/_tools/project_models.py:130` pins the extra-schema inventory to
  `{"Profile", "ProfileIndex", "usage_accounting"}` and walks the `$defs` of `Profile` and
  `ProfileIndex`; with the export fixed it raises `ProjectionError("unsupported extra schema
  inventory")`.
- `solutions/_tools/project_model_versions.py:155` raises `generated entity disappeared from
  source` for every card owned by the projector whose model is no longer generated. Fifteen such
  cards exist (§3.2).
- Cards still present the deleted modules as live code: `ProfileIndexStore`,
  `python -m aigateway.migrate_profiles`, `backfill_classify.py`/`backfill_apply.py`, and source
  links to `core/profile_index.py` and `core/profile_models.py`.

The catalog therefore cannot be regenerated from `main`, and a reader of the catalog is told the
Profile store still exists.

## 2. Goal

Regenerate every projector-owned card and both exported OpenAPI artifacts from current `main`,
mark every model that Stage E removed as `deprecated` through an explicit retirement list, and
correct the authored cards that describe deleted code as live. After the change, `project_models.py
--check` and the contract export pass on `main`, and the catalog check reports no new errors.

## 3. Scope

### 3.1 Tools (local, `solutions/_tools/`, not committed to any repository)

- `export_contracts.py`: drop the `profile_models` import and the `Profile`/`ProfileIndex` extra
  schemas; `extra` carries only `usage_accounting`.
- `project_models.py`: the extra-schema inventory pin becomes `{"usage_accounting"}`; the `$defs`
  walk over `Profile`/`ProfileIndex` goes.
- Retirement list (epic spec §11: "tooling retirement list; disappearance guard still fails on an
  unlisted disappearance"): a closed, reviewed list of generated slugs whose model left the source.
  - A listed slug that the projector no longer generates is kept: its body stays as last projected
    (including `x-source-revision`, which then names the last revision where the model existed) and
    its status becomes `deprecated`. The version does not change: the catalog's `AGENTS.md` exempts
    status-only changes, and the five cards `OME-1413` deprecated kept `version: 1`.
  - An unlisted disappearance still raises.
  - A listed slug whose model is generated again raises, so the list cannot silently go stale.
- Reconcile the tools with the catalog before any write (superseded by §8, decision 4). The catalog commit `5f05b70` (2026-09-30,
  `OME-1413`) added `relations: supersedes` to generated cards (for example
  `patch-profile-metadata-request` supersedes `patch-profile-request`) and changed their summaries
  ("display label"). The local tools predate it: they were last modified 2026-09-22,
  `project_model_labels.json` still holds the old texts, and `project_models.py` emits no
  `relations`. A `--write` with the tools as they are reverts those edits. So:
  - First, a baseline check: run `--check` against the source revision the cards cite (`d35a46537`).
    Every difference it reports is a catalog edit made outside the projector.
  - Bring each such edit into the tools: label texts into `project_model_labels.json`, and the
    `supersedes` relation as a projector-preserved authored field (or a labels entry).
  - Repeat until the baseline check at `d35a46537` reports no difference. Only then project `main`.
- Tests first, in the tools' own suite (`test_project_models.py`, `test_project_model_versions.py`,
  `test_export_contracts*.py`): the three retirement-list rules above, the new inventory pin, an
  export that imports no Profile class, and a preserved `supersedes` relation.

### 3.2 Generated cards (`product/aigateway/datamodel/`)

Retired through the list, `deprecated` (12 from E3, 3 from E5c):

| Stage | Slugs | Model |
|---|---|---|
| E3 | `admin-profile-list`, `admin-profile-out` | `AdminProfileList`, `AdminProfileOut` |
| E3 | `patch-profile-request` (already deprecated), `patch-profile-metadata-request` | `PatchProfileRequest` |
| E3 | `patch-admin-profile-request` (already deprecated), `patch-admin-profile-metadata-request` | `PatchAdminProfileRequest` |
| E3 | `set-api-key-request` (already deprecated), `set-profile-api-key-request` | `SetApiKeyRequest` |
| E3 | `set-admin-api-key-request` (already deprecated), `set-admin-profile-api-key-request` | `SetAdminApiKeyRequest` |
| E3 | `start-auth-request` (already deprecated), `start-profile-auth-request` | `StartAuthRequest` |
| E5c | `profile`, `profile-state`, `profile-index` | `Profile`, `ProfileState`, `ProfileIndex` |

The remaining 34 generated cards are re-projected from `main`; any field change since `d35a46537`
bumps the version through the existing rule. `HTTPValidationError`, `ValidationError` and the
cache-snapshot upload body come from the OpenAPI document, not a source class, and stay generated.

### 3.3 Authored cards

The list below is what was known when this spec was drafted. A full scan before the edit (§8,
item 6) found the same defect in more entities; all of them are in scope under the same rule.

- `datamodel/profile-defaults` (authored, excluded from the projector): `deprecated`, plus a line
  naming its removal (saved defaults at Stage C, the class at E5c); that text change advances it
  once.
- `solutions/README.md`: a provenance paragraph for this refresh, as for `OME-1413` and the
  2026-10-12 refresh: the source revision it moves to, the entities that advance, the sixteen
  that become `deprecated`, and that no edge is removed.
- Cards that cite deleted code as live, each version-bumped and rewritten to state what replaced it
  (Connection-backed provider access) or that the item was removed and when:
  `component/credential-store`, `component/persistence`, `component/provider-access`,
  `protocol/provider-access`, `protocol/administration`, `protocol/provider-credential-admin`,
  `protocol/chat-processing/workflows/non-streaming.yaml`, and the `http-api` operation text that
  names `ProfileIndexStore`.
- Runtime error codes `profile_index_conflict` and `profile_conflict` are described as they are
  today: the gateway no longer emits either code (the last emitter went at E4b, the dead arms at
  E5a); the Admin UI still decodes `profile_index_conflict` for an older gateway.
- Carried over from `OME-1380`: solution `protocol/completions` still says saved defaults are read
  before the cache lookup, stale since Stage C.

### 3.4 Exported artifacts

`protocol/http-api/openapi.yaml` and `protocol/cache-snapshots/openapi.yaml` are re-exported from
`main`, which drops `ProfileState` and every schema only the retired routes used.

## 4. Out of scope

- Committing the tools to a repository or adding CI for them.
- Renaming the runtime error codes (Stage E R3) or the `aigateway-ui` decoder.
- Deleting deprecated cards or rewriting their history.
- Catalog changes for gateway features merged since `d35a46537` beyond what re-projection and
  re-export produce mechanically; authored prose for those features is a separate refresh.

## 5. Acceptance

- `project_models.py --check` on `main` reports no difference after the write; the export runs
  against `main` without importing a Profile class.
- The 15 listed cards are `deprecated` with their version unchanged (status-only);
  `profile-defaults` is `deprecated` and, because its text changes, advances exactly once.
- Every other changed entity advances exactly once relative to design `main`.
- An unlisted disappearance and a stale list entry each fail the projector (tests).
- No card outside the deprecated set cites `core/profile_index.py`, `core/profile_models.py`,
  `migrate_profiles`, `purge_profile_history`, `backfill_classify`, `backfill_apply`,
  `history_purge` or `history_references` as live code.
- Catalog check: no errors beyond those on design `main`; `--since origin/main` lists exactly the
  changed entities, each version-bumped.

## 6. Questions resolved (2026-10-29, read-only)

1. Retired models in the OpenAPI document: none. None of the twelve E3 classes, nor `Profile`,
   `ProfileState` or `ProfileIndex`, is defined anywhere under `apps/aigateway/src` on `main`. They
   cannot appear as OpenAPI components, so all fifteen stay on the retirement list.
2. The five cards already `deprecated`: they never passed through the projector in that state.
   `5f05b70` set them `deprecated` and added their `-metadata-` successors with `supersedes`
   outside the local tools. That is the reconciliation step in §3.1.

## 7. Open for the plan

- The size of the re-projection diff for the 34 live cards. If it is large, record it in the
  ledger rather than splitting the leaf (owner chose one leaf).
- Whether `5f05b70` is the only catalog edit made outside the projector; the baseline check in
  §3.1 answers this.

## 8. Decisions after the baseline check (2026-11-05)

Items 1 to 5, 7 and 8 are owner decisions. Item 6 applies the §3.3 rule to what the full scan
found and is open to review in the catalog PR.

1. The exporter worker sets `socket.has_ipv6` to false before the application import. Since
   `79a949e11` the OTLP trace exporter imports `requests` and `urllib3`, and urllib3 binds `::1` at
   import to probe IPv6; the I/O guard stays deny-all instead of allowing that bind.
2. The eight models merged after `d35a46537` get generated cards at `draft` v1 with labels written
   from source; no relation edges or feature prose.
3. `check_coverage.py` is not a gate for this leaf. Its reviewed snapshot is already stale at
   `d35a46537`; that and the operations added since go to a separate follow-up.
4. The five `OME-1413` successor cards are not ported into the tools (no aliases, texts or
   `supersedes` preservation): their models are gone, so the retirement list keeps those cards as
   they are. The "`supersedes` survives `--write`" test is dropped. The `test_catalog_config` pin
   moves from 76 to 84 properties.
5. Prior tool tests: census tests move to the current counts, signed with their revisions; mixed
   tests lose only their Profile branches or move to `usage_accounting`; Profile-only tests and
   `project_models.semantic()` with its two tests are deleted. The Stage E invariants are pinned by
   new tests. The ledger lists every changed and deleted test.
6. Authored-card scope is every entity that presents Stage E-deleted code, renamed hooks or retired
   routes as live, found by scanning all authored cards against source at `24d979a5e`, not only the
   eight listed in §3.3.
7. The authored `config` datamodel is corrected here. The two inputs Stage E stopped reading,
   `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE` and `USER`, stay in its schema and table marked
   `deprecated`, because a datamodel version only adds properties; the `test_catalog_config` pin
   stays at 84. Its source revision is unchanged.
8. Two live generated models narrowed since `d35a46537`, which the catalog's additive-evolution
   check refuses in place: `OAuthConnectionListResponse` (`6e998fa4d`) and `usage_accounting`
   (`OME-1686`). Each moves to a successor (`oauth-connection-listing`, `chat-usage-accounting`)
   through a closed successor list in the projector; a successor carries `relations: supersedes`
   and enters at v1 `approved`, and its predecessor joins the retirement list. This updates §3.2
   and §5: the list has 17 entries and 32 live cards advance once. Edges stay on the predecessors;
   moving them is a follow-up. Two prior tool assertions change only their expected slug.
