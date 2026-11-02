---
ticket: OME-1647
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-18
finished: 2026-10-18
---

# e2a-neutral-types — move the credential vocabulary out of `profile_models.py`

## Intent

Landing E2a of Stage E (`OME-1209`, spec `docs/spec/2026-10-14-OME-1209-retire-legacy-profiles.md`
§3, plan §3 E2a). `AuthType`, `AuthMode`, `credential_name_for` and `profile_id_for` are core
credential vocabulary, but they live in the legacy Profile module, so every plugin, the chat
parameter algebra and the Connection store import `profile_models`. Moving them to neutral modules
leaves `profile_models.py` with only the Profile row (`ProfileState`, `ProfileDefaults`, `Profile`,
`ProfileIndex`), so E4/E5 can delete it without touching the rest of the gateway. No behaviour
changes.

## Planned changes

Under `apps/aigateway/src/aigateway/`:

- New `core/auth_types.py`: `AuthType`, `AuthMode` (with their invariant comment).
- New `core/credential_names.py`: `credential_name_for`, `profile_id_for` (the second keeps its
  name: it computes the stored locator of a migrated blob, which E5 still needs).
- `core/profile_models.py`: drop the four names; `Profile.auth_type` imports `AuthType` from
  `auth_types`.
- Every source importer of the four names moves to the new modules.

Under `apps/aigateway/tests/`:

- Every test importer of the four names moves to the new modules (import lines only, all at
  module level, so no test-change manifest).
- `tests/unit/core/provider_access/test_provider_access_import_boundary.py`: one new test.

## Test plan

- RED: a new boundary test — outside the documented Profile owners (`_OWNERS`), no module under
  `src/aigateway/` imports `profile_models` at all, under any spelling. It fails today on the
  plugins, the chat parameter modules and the Connection schemas.
- A second new test pins that `profile_models` no longer defines the four neutral names, and that
  the new modules do.
- Proof of no behaviour change: the full suite is green with only import lines changed in prior
  tests; OpenAPI byte-identical to the base.

## Acceptance

- `uv run .claude/scripts/run_gates.py aigateway --base origin/main` green with no test-change
  manifest.
- `git grep -n profile_models -- apps/aigateway/src` lists only `_OWNERS` modules.
- OpenAPI byte-identical to `origin/main`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. New `core/auth_types.py`, `core/credential_names.py`; trimmed
  `core/profile_models.py`; import lines in 141 source and test files. New tests
  `tests/unit/core/test_neutral_credential_vocabulary.py` and one boundary test appended to
  `test_provider_access_import_boundary.py` (its docstring updated). Also closes the OME-1645
  mirror (`status: done`).
- **Commits:** one squash-ready commit on `OME-1647-move-credential-vocabulary-out-of-profile-models`.
- **Gates:** `run_gates.py aigateway --base origin/main` all green (append-only with 2 approved
  transitions, ruff, format, pyright, no-enterprise, pytest with coverage >= 80). RED: the
  boundary test listed 29 non-owner importers and the vocabulary test failed to import the new
  modules. Full suite 6164 passed, 120 skipped (PostgreSQL and integration lanes). OpenAPI
  byte-identical to `origin/main`.
- **Deviations:** the plan expected no manifest. Three `profile_id_for` imports sit inside functions
  in `test_auth_applicability_contract.py` and `test_contract_source_revision_identity.py`, so their
  import-line edits go under the owner-approved `.claude/test-change-approvals/OME-1647.json`.
