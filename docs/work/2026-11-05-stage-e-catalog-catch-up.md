---
ticket: OME-1839
stack: repo
status: done   # planned | in_progress | done | blocked
started: 2026-11-05
finished: 2026-11-07
---

# stage-e-catalog-catch-up — Retire the Profile-era models from the AIGateway catalog

## Intent

The AIGateway solution catalog in `screamingface-design` was last projected from gateway source at
`d35a46537` (2026-09-29), before Stage E of `OME-1138` deleted the Profile models (E3, E5c). Ten
of its fifteen generated Profile-era cards are not `deprecated` (`OME-1413` deprecated the other
five), authored cards still cite deleted modules as live code, and the local projection tools can
no longer run against `main`: the exporter imports
`Profile`/`ProfileIndex`, the projector pins them as extra schemas, and the version step raises on
the fifteen models that left the source. This unit makes the tools run against `main` again, retires
those cards as `deprecated` through a closed retirement list, re-projects the rest, and corrects the
authored cards, in one reviewed catalog change.

## Planned changes

- Local tools (`solutions/_tools/`, untracked, never committed): `export_contracts.py`,
  `project_models.py`, `project_model_versions.py`, `project_model_labels.json`, and their tests.
- Catalog (`screamingface-design`, `solutions/screamingface/product/aigateway/...`): the 17 cards
  on the retirement list (status only; the 15 Profile-era cards and the 2 predecessors of the
  successor swap), the 2 successor cards, the re-projected live cards, the 8 new `draft` cards,
  both `openapi.yaml` exports, `datamodel/profile-defaults`, the `config` datamodel, the authored
  cards that cite deleted code, solution `protocol/completions`, and a provenance paragraph in
  `solutions/README.md`.
- This repository: this ledger, `docs/spec/2026-11-05-stage-e-catalog-catch-up.md`,
  `docs/plan/2026-11-05-stage-e-catalog-catch-up.md`, and the `docs/tasks/` mirror at PR-open.

## Test plan

- Tool suite (`python -B -m unittest discover -s solutions/_tools -p 'test_*.py'`), RED first:
  - the extra-schema inventory is `{"usage_accounting"}` and the `$defs` walk over the Profile
    schemas is gone; a model in both the OpenAPI and the extra inventory raises;
  - the exporter imports no Profile model module, in any import form;
  - retirement list: a listed and absent slug is kept, set `deprecated`, version unchanged; a
    listed card missing either file, or its directory, raises; an unlisted disappearance raises; a
    listed slug that is generated again raises;
  - the successor list is closed, and only a successor card carries `relations: supersedes`;
  - in a Git checkout whose `HEAD` tracks no generated card while the working tree holds some,
    `--check` and `--write` refuse and nothing on disk changes.
- Existing tool tests change only within the owner-approved scope listed below.

## Acceptance

- `project_models.py --check` on `main`, in a copy without `.git`, reports no difference after the
  write; in a Git checkout where the catalog is untracked it refuses before any write. The export
  runs against `main` without importing a Profile model module.
- The 17 cards on the retirement list are `deprecated` with version and body unchanged: twelve
  change status only and the five already deprecated do not change. `profile-defaults` is
  `deprecated` and advances exactly once.
- The 32 re-projected live cards advance exactly once; the 2 successor cards enter at v1
  `approved` with `relations: supersedes`; the 8 new cards enter at v1 `draft`.
- Every changed authored entity advances exactly once relative to design `main`.
- No card outside the deprecated set cites a deleted Profile-era module as live code.
- Catalog check: no errors beyond design `main`; `--since origin/main` lists exactly the changed
  entities, each existing one version-bumped or changed in status only.

## Baseline reconciliation work list

Baseline check at `d35a46537`, run 2026-11-05 against design `main` `63d41f7`.

- **The exporter cannot run as is.** Since `79a949e11` (2026-09-11) `aigateway/tracing.py` imports
  the OTLP HTTP exporter, which imports `requests` and `urllib3`; urllib3 binds `::1` at import to
  probe IPv6, and the worker's I/O guard records the `socket.bind`. With the worker's
  `socket.has_ipv6` set to false before the application import, extraction is clean (0 denied
  attempts) at `d35a46537` (48 operations, 42 schemas) and at `main` (105 operations, 41 schemas).
- **OpenAPI.** Design `http-api/openapi.yaml` equals the `d35a46537` export except one availability
  route description (the 2026-10-12 refresh at `5e1d30cc`). Design `cache-snapshots/openapi.yaml`
  predates `d35a46537` (it still carries the five `defaults` fields and lacks the availability DTOs).
- **Generated cards, 7 of 49 differ.**
  - Five `OME-1413` successors (`patch-profile-metadata-request`,
    `patch-admin-profile-metadata-request`, `set-profile-api-key-request`,
    `set-admin-profile-api-key-request`, `start-profile-auth-request`): slug alias, summary and note
    text, and `relations: supersedes`, all edited outside the projector. Their models are gone on
    `main`, so the retirement list keeps these cards as they are.
  - `provider-access-availability` and `provider-access-availability-row`: no label entry (the
    projector stops on missing labels).
  - `usage-accounting`: cites `5e1d30cc`; its note text (`provider_guaranteed_zero`, attempt schema
    v2) is not in the labels file.
- **Versioning.** In a Git worktree the version step finds the `.git` marker, reads the catalog
  bucket from the code repository's `HEAD` (where it is untracked), and so treats every card as new
  at version 1. Projection must run in a root without a `.git` marker (file-only mode). Since the
  2026-11-06 review the projector refuses that configuration before any write instead.
- **`main` beyond `d35a46537`.** 57 operations added (48 under `/admin`, 12 in OpenAPI), none
  removed; 8 new models with no card or label (`AdminConnectionConflictOut`, `AdminConnectionList`,
  `AdminConnectionOut`, `OAuthConnectionListRow`, `Provenance`, `SealRequest`, `ToolLookupRequest`,
  `ToolResultRequest`). Of the 34 live cards, the substantive changes are
  `oauth-connection-list-response` (rows become `OAuthConnectionListRow`), `usage-accounting`,
  `http-validation-error`, `validation-error` and `oauth-connection-response` (operation lists);
  the rest change only the source revision and class line numbers.
- **Pre-existing gate failures.** `check_coverage.py --check` already fails at `d35a46537` (stale
  reviewed snapshot: 78 entity changed, 49 source changed, 27 entity added, 26 missing citations,
  `GET /v1/provider-access` undocumented). The tool suite fails one existing test at the baseline,
  `test_catalog_config` (the config card has 84 properties; the test pins 76).

## Owner decisions (2026-11-05, after the baseline check)

1. Exporter: the worker sets `socket.has_ipv6` to false before the application import; the guard
   itself is unchanged.
2. The eight new models get generated cards (`draft`, version 1) with labels written from source;
   no relation edges or feature prose.
3. `check_coverage.py` is not an L3 gate. Its stale reviewed snapshot and the 57 new operations go
   to a separate follow-up issue.
4. The five `OME-1413` successor cards are not ported into the tools (no aliases, texts or
   `supersedes` preservation); the retirement list keeps them as they are. The plan's
   "`supersedes` survives `--write`" test is dropped. The `test_catalog_config` pin moves from 76
   to 84 properties.
5. The authored config card (`chat-api/datamodel/config`) is corrected in this change. Its source
   revision stays at `5e1d30cc`, because the rest of the card (three Settings fields added since)
   is not re-audited here. The first draft removed the two inputs Stage E stopped reading and
   moved the `test_catalog_config` pin to 82; the catalog check in the design repository refused
   the removal (`E_DM_NOT_ADDITIVE`: a datamodel version only adds), so the decision is applied by
   keeping both properties and table rows marked `deprecated`, and the pin stays at 84.
6. Successor swap for the two generated models that narrowed since `d35a46537`, which the same
   check refused as in-place changes: `OAuthConnectionListResponse` (rows became
   `OAuthConnectionListRow` with a required `effective`, `6e998fa4d`) and `usage_accounting` (two
   keys became required, `OME-1686`). A closed `SUPERSEDES` list in the projector maps the new
   slugs `oauth-connection-listing` and `chat-usage-accounting` to their predecessors; each
   successor card carries `relations: supersedes` and enters at v1 `approved`, like the card it
   replaces; the predecessors join the retirement list and become `deprecated` with their body and
   version as on design `main`. Relation edges stay on the old slugs; moving them is a follow-up.
7. Two prior assertions in `test_project_models.py` change only their expected slug to
   `chat-usage-accounting` (see below).
8. Review of the tools (2026-11-06). The projector refuses three more cases: a listed card missing
   either file or its directory, which it used to drop silently; a model in both the OpenAPI and
   the extra inventory, even when identical; and a Git checkout whose `HEAD` tracks no generated
   card while the working tree holds some, which used to restart every card at version 1. The
   owner chose to require the retired cards unconditionally, with the prior-test fixtures changed
   to match, and approved changing the one prior test that pinned the version restart (see below).

## Prior tool tests changed (owner approval 2026-11-05 and 2026-11-06)

16 existing tests of the local tool suite changed or went on 2026-11-05: 14 that encoded the
Profile models or the `d35a46537` census, plus the two unit tests of `project_models.semantic()`,
deleted with the function because only the Profile-equivalence check called it. The owner approved
this scope on 2026-11-05: update the census tests to the current authoritative counts, signed with
the revisions they come from; remove only the Profile branches from the mixed tests or move their
check to `usage_accounting`; delete the Profile-only tests and `semantic()`. The tools are local
and never committed, so this ledger is their audit trail.

Census tests, updated:

- `test_catalog_config.py` `test_server_and_proxy_inputs...`: 76 (43 + 15 + 18) properties to 84,
  the config card at design `main` `63d41f7` and after this change (61 Settings environment names
  plus 23 direct/ambient inputs, two of them deprecated).
- `test_export_contracts.py` `test_actual_census_and_worktree_origin`: registrations 47 to 105 at
  `24d979a5e` (against `802bed9ae`), of which 47 are in OpenAPI and 58 hidden (45 administrative
  Connection method guards and trailing-slash redirects, 13 retired Profile routes); the equality
  is against the published operations; no hidden registration sets `include_in_schema`;
  infrastructure routes 8 to 14; the provider inventory gains `local`.
- `test_export_contracts.py` `test_original_schemas_local_refs_and_admin_security`: the extra
  schemas are `{"usage_accounting"}`; the `ProfileIndex` `$defs` assertion is gone.
- `test_project_model_sources.py` `test_all_labels...`: 43 labels to 42.
- `test_project_models.py` `test_full_census...`: 40 native models to 41; the projected set is
  the native models plus `usage_accounting`, 43 to 42.

Mixed tests, Profile branches removed or moved to `usage_accounting`:

- `test_extra_definitions_lift...`: the Profile loop goes; the usage `$defs` count is 15 to 16
  (attempt schema v2, `OME-1446`).
- `test_real_constraints...`: the `ProfileDefaults` and `Profile` cases go.
- `test_slug_collisions...`: the duplicate is now triggered by a native `usage_accounting` schema.
- `test_unsupported_constructs...`: the nested `$id` now sits in `usage_accounting`
  `$defs.direct_cost`.
- `test_english_cards...`: the `profile`, `profile-index` and `set-api-key-request` assertions go;
  the usage `$id` is `aigw-usage-accounting.v2.json`.

Slug only (owner decision 7):

- `test_full_census...`: the expected slug of `usage_accounting` is `chat-usage-accounting`.
- `test_english_cards...`: the three `card("usage-accounting")` lookups read
  `card("chat-usage-accounting")`; the asserted texts are unchanged.

Deleted:

- `test_project_models.py`: `test_profile_equivalence_checks_constraints_but_ignores_annotations_and_nullable_form`,
  `test_profile_identity_mismatch_is_never_accepted_or_repaired`.
- `test_project_model_regressions.py`: `test_authored_profile_schema_symlink_is_rejected_before_json_read`,
  `test_profile_reuse_rejects_sibling_type_that_removes_null`, and the class `TestMeaning`
  (`test_sibling_type_restricts_nullable_anyof_and_must_survive_normalization`,
  `test_existing_nullable_forms_remain_equivalent_without_losing_constraints`), which tested
  `semantic()` only.

Review of the tools, 2026-11-06 (owner decision 8). With every retired card required, a fixture
must hold them, and an artifact count includes them:

- Fixtures: the `setUp` of `TestArtifacts` (`test_project_models.py`), `TestGitVersions`
  (`test_project_model_versions.py`) and `TestInputs` (`test_project_model_regressions.py`) also
  copies the 17 retired cards, through the new helper `copy_retired` in `test_project_models.py`.
  The mocked Git `HEAD` of `TestGitVersions` tracks them, as a real catalog does.
- Counts: `test_english_cards...`, `test_ast_never_executes...` and
  `test_git_directory_marker...` expect 84 plus two files per retired card;
  `test_english_cards...` skips the retired cards in its per-card checks, which describe
  generated cards at the current revision.
- `test_new_git_entities_repair_inflated_versions_read_only_then_start_at_one`: with `HEAD`
  tracking the retired cards, a new entity in a tracked catalog still starts at version 1. History
  is now read for the tracked cards, so instead of asserting that no blob is read, the test
  asserts that only the tracked cards' blobs are read.
- `ruff.toml` names the tools' modules as first-party, so ruff sorts imports the same way from the
  repository root and from `solutions/_tools`.

The Stage E invariants are pinned separately in the new `test_stage_e_retirement.py`: the
exporter imports no Profile module, in any import form; the extra-schema inventory is
`usage_accounting` only; a model in both inventories fails, identical or not; an unlisted
disappearance fails; a listed disappearance keeps the card and makes it `deprecated` at its
version; a listed card missing either file or its directory fails, and a write then changes
nothing; a listed model generated again fails; a retired card keeps its authored body and
relations verbatim; the eight new models get `draft` cards; a write is followed by a clean
`--check`; the successor list is closed and each successor slug maps from its model; only a
successor card carries `relations: supersedes`; a retired card changes only its status; the
config card lists exactly `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE` and `USER` as deprecated. The
refusal in an untracked Git checkout is pinned in `test_project_model_versions.py`, next to the
mocked Git history it needs.

## Projection at `main`

Run in a root without a `.git` marker (see Baseline reconciliation work list), input revision
`24d979a5e850759e48a4d8c03c0a3f1ca4c5aa0e`: 42 models, 84 files, 17 retired.

- 32 live generated cards advance one version, status kept.
- 2 successor cards at v1 (`oauth-connection-listing`, `chat-usage-accounting`); the projector
  writes `draft`, and the status is then set to `approved` by hand, which later runs preserve.
- 12 retired cards become `deprecated`, version and body unchanged (the 10 Profile-era cards and
  the 2 predecessors); the 5 already `deprecated` are unchanged.
- 8 new cards at `draft` v1: `admin-connection-conflict-out`, `admin-connection-list`,
  `admin-connection-out`, `oauth-connection-list-row`, `provenance`, `seal-request`,
  `tool-lookup-request`, `tool-result-request`.
- Both `openapi.yaml` exports are replaced; write, check, write is idempotent.

## Authored cards: scope found by a full scan

The spec listed eight authored cards. A scan of every authored card for source paths, symbols and
plugin hooks that no longer exist at `24d979a5e`, and for retired routes described as live, found
the same defect in more entities: the renamed plugin hooks (E4c), the deleted Profile bootstrap
(E4b), the deleted chat shims and saved-defaults pipeline (E2b), the Profile-backed resolver
(E4a), the retired Profile routes in transports and workflows (E3), and the solution-level
`gateway-admin`, `model-catalog` and `completions` protocols and two journeys that still provision
or select through Profiles. All of them are in this change, each advancing once. The
`protocol/completions` link that names the shape of the accounting envelope points at the successor
`chat-usage-accounting`; edges and the `component/usage-accounting` prose stay on the predecessor
until the follow-up moves them.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - Local tools (never committed): `export_contracts.py`, `project_models.py`,
    `project_model_versions.py`, `project_model_labels.json`, `ruff.toml`, the six changed test
    modules listed above and the new `test_stage_e_retirement.py`; `_coverage/contracts.json`
    re-exported.
  - Catalog (`screamingface-design`): 91 entities. 10 new (the 8 `draft` cards and the 2
    successors), 13 `deprecated` (12 generated, status only, and `profile-defaults`, advanced
    once), 32 generated cards advanced once and 36 authored entities advanced once; both
    `openapi.yaml` exports; `solutions/README.md`.
  - This repository: this ledger, the spec, the plan, and the `docs/tasks/` mirror at PR-open.
- **Commits:** `screamingface-design` `b08b5ed` — docs(catalog): retire the Profile-era AIGateway
  models after Stage E, squash-merged as `01368cdab85cb925be3d0ccd0efa0472246d0be8` (#34) on
  2026-11-06.
  This repository: the docs commit carrying this ledger, the spec, the plan and the task mirror,
  squash-merged to `main` as `188246268ebf4b833e29bd78b38c3f2ef3a836af` (#1691) on 2026-11-06.
- **Tools at close (2026-11-07, plan step 11):** the shared checkout's `solutions/_tools/` and
  `_coverage/contracts.json` were replaced with the reviewed copy. The review patch has SHA-256
  `98f0c5e5817954b7de3fc41cdfb2f12ceaada2007222e8ac465a5553824f11d8`. The shared checkout's
  catalog copy predates design `main` and was left as it is, so the suite passes only against a
  catalog at design `main`: there the same files pass all 178 tests.
- **Gates:** tool suite 178 tests OK (173 before the 2026-11-06 review, which added five);
  `ruff check` and `ruff format --check` clean on `solutions/_tools`, run from the repository root
  and from `solutions/_tools`; export 105 operations, 41 OpenAPI schemas, 9 providers, 0 denied
  I/O attempts; `project_models.py --check` in the copy without `.git`: 42 models, 84 files,
  17 retired; in the Git worktree, `--write` refuses and the catalog files are unchanged. Catalog
  check in the design repository: 0 errors, 27 warnings, 133 entities; `--since origin/main`: 91
  entities, 81 existing ones changed, each version-bumped or status-only, and 10 new. The 19
  warnings beyond design `main` are all `W_REF_DEPRECATED`, from edges kept on deprecated
  datamodels. The review changed neither the exporter nor the catalog, so the export and both
  catalog checks stand as run on 2026-11-05.
- **Deviations:**
  - The ledger is dated 2026-11-05 (work start), not the plan's 2026-10-29 draft date.
  - Owner decisions 1 to 8 above; existing tool tests changed under the approved scope.
  - The evolution rule needs Git history, so only the check in the design repository sees it;
    the git-less projection root cannot. That check drove decisions 5 and 6.
- **Follow-up `OME-1840`** (`improvement-ideas`, Triage, filed 2026-11-05), "Refresh AIGateway
  catalog coverage, successor references, and drifted prose":
  - Coverage: refresh the reviewed operation-coverage snapshot (`check_coverage.py`, stale at
    `d35a46537`, and the `_coverage/aigateway.json` slugs), and give the operations added since
    then catalog citations and prose.
  - Successor references: move the edges and prose links on deprecated datamodels to their
    successors, or drop an edge whose datamodel has none: the `chat-api` `exposes` edges; the
    `credential-store`, `parameter-contracts` and `provider-access` edges to `profile`,
    `profile-index` and `profile-defaults`; `component/usage-accounting`, its edge and its prose
    link.
  - Post-baseline prose drift: the `aigateway-ui` card; the Engine card's Stage D target section;
    `persistence` packages and migrations 0014 and 0015; the `plugin-contract` hook list and
    adapter count; `model-discovery` per-grant model filtering; `application-lifecycle` shutdown
    closing remote endpoints; line references in `provider-access` and
    `provider-access-availability`.
  - Config: a full refresh of the `config` datamodel at a current source revision, including the
    three Settings fields added since `5e1d30cc`.
  - Not in `OME-1840`: Profile wording left in gateway source strings, a code change rather than a
    catalog one.
