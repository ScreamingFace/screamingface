---
ticket: OME-1798
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-29
finished: 2026-10-30
---

# OME-1798 dead-code-and-test-debt — OME-1138 close-out L4b: dead code, stale comments, guards, test debt

## Intent

Leaf L4b of the OME-1138 close-out (spec `docs/spec/2026-10-29-ome-1138-closeout.md` §4.4, plan
section "L4b"; both accepted by the owner 2026-10-29). Stage E retired the Profile machinery, but
the review of 2026-10-29 confirmed dead Profile-era code, comments that describe retired
behaviour, guards that pass vacuously, and test debt in the gateway. This unit removes the dead
symbols, corrects the comments in Connection terms, tightens the guards, and clears the test debt.
Nothing a request can observe changes; the full suite is the proof. Built stacked on L4a
(`OME-1784-retire-quarantine-and-x-profile`, PR #1614), which sat on L1 (PR #1610). Both merged
first, and the branch was rebased onto `main` before the push.

## Planned changes

Gateway src (`apps/aigateway/src/aigateway/`):

- `core/errors.py`: remove `ProfileNotFoundError`, `ProfilePendingAuthError` (RT-06, P-F5).
- `core/provider_access/pair_authority.py`: remove `PairAuthorityStore.providers()` (critic-2).
- `core/credential_blob/store.py`: remove `ORMStore.mutate`, the `mutate` member of the
  `CredentialBlobStore` protocol, `CredentialBlobMutationConflict` and the retry helpers only
  `mutate` used (k1/K1); `core/frozen_copy/headers.py:3` docstring.
- `core/credential_names.py`: deleted; `credential_name_for` moves to the test helper
  `tests/credential_names.py` (RT-07, T-F6, P-F14).
- Comments (RT-13, RT-08, critic-1): `core/request_cache/global_eligibility.py`,
  `routes/chat.py`, `core/oauth/store.py` (`credential_locator` docstrings), `unhandled_errors.py`.
- Profile-era wording the lead added: `routes/model_parameters.py`,
  `core/chat_parameters/__init__.py`, `core/chat_parameters/_types.py`,
  `core/chat_parameters/_algebra.py`, `core/plugin_base/_contract.py`,
  `core/model_capabilities.py`, `core/provider_access/types.py`,
  `routes/provider_access_http.py` (comments only; no runtime identifier, log field or message).

Gateway tests (`apps/aigateway/tests/`), the spec §6 L4b manifest only:

- New `tests/credential_names.py`; the importers of `credential_name_for` change their import
  line only.
- Guards: `unit/core/provider_access/test_provider_access_import_boundary.py` (T-F4, P-F7),
  `unit/test_profile_index_offline_only.py` (T-F13 + `credential_names`),
  `unit/core/test_neutral_credential_vocabulary.py`, `unit/test_profile_conflict_arms_retired.py`.
- Test debt table §4.4: T-F1, T-F2, T-F3, T-F5, T-F8/K6, T-F9, T-F10, T-F11, T-F12, K4, critic-3.

No schema or model change, so no migration (S1 not triggered).

## Test plan

RED first, guards before GREEN:

- `test_every_owner_exemption_names_a_real_file_and_a_reason` also asserts that every exempted
  path imports at least one banned name: RED on `routes/admin.py`, `core/admin_schemas.py`,
  `migrations/`.
- `_RETIRED_MODULES` gains `connection_facade`, `connection_oauth` and
  `aigateway.core.credential_names`: RED on `credential_names` until the module moves.
- K4: the forbidden literals become reachable — the test seeds Connections that carry them and
  asserts each is present in the stored state before asserting it is absent from the body: RED
  while the test seeds nothing.
- T-F5: the inventory's read log must be empty (no `aigateway:index` allowance), with a positive
  control proving the spy sits on the read path; mutation-checked against an injected read the
  old guard let through.
- `test_profile_conflict_arms_retired.py`: `ORMStore` and the protocol have no `mutate` and the
  conflict class is gone: RED until the removal.
- `test_neutral_credential_vocabulary.py`: the locator shape is pinned on the test helper, and
  `aigateway.core.credential_names` no longer exists: RED until the move.
- GREEN: full `aigateway` suite (`run_gates.py aigateway`), then the `needs_postgres` lane.

## Acceptance

- None of `ProfileNotFoundError`, `ProfilePendingAuthError`, `CredentialBlobMutationConflict`,
  `credential_name_for`, `PairAuthorityStore.providers`, `ORMStore.mutate` remains in gateway src.
- Every new or tightened guard was seen RED for the stated reason.
- `run_gates.py aigateway --base OME-1784-retire-quarantine-and-x-profile` green; the PG lane
  green; every changed prior test is in `.claude/test-change-approvals/OME-N.json`.

## Outcome

- **Actual files (71 under `apps/aigateway`, plus this ledger, the mirror and the manifest):**
  - src (19): the planned removals in `core/errors.py`, `core/provider_access/pair_authority.py`,
    `core/credential_blob/store.py` and `core/credential_names.py` (deleted); comment and
    docstring edits in the planned sites, plus `core/frozen_copy/headers.py`,
    `core/request_cache/global_plan.py` and `plugins/openai_provider/plugin.py`.
  - tests (52): the new helper `tests/credential_names.py`; 30 files import it, 26 of which
    change only the import line; the guards; the §4.4 test-debt sites; the three owner-approved
    off-manifest edits below.
- **Commits:** one, `refactor(aigateway): remove Profile-era dead code and clear the close-out
  test debt` (sha in the PR).
- **RED seen:** the import-boundary owner check (on `routes/admin.py`, `core/admin_schemas.py`,
  `migrations/`); `_RETIRED_MODULES` (`credential_names` still importable); the AST guard (found
  `core/credential_names.py`); K4 (identifying values absent from the stored rows); the
  vocabulary test (helper missing); the dead-symbol tests (3, with `errors.py` restored);
  `test_the_blob_store_has_no_mutation_path` (`ORMStore.mutate` present). T-F5 was
  mutation-checked twice: a read through `app.state.credential_store` and, after the review, a
  read through a fresh `ORMStore()` in `pair_inventory` both fail it.
- **Gates:**
  - Stacked base (`run_gates.py aigateway --base origin/OME-1784-retire-quarantine-and-x-profile`,
    2026-10-30):
    - Append-only passed, with the 19 OME-1798 approvals.
    - ruff, format, pyright and the no-enterprise check passed.
    - pytest: 7341 passed, 107 skipped, coverage 94%.
  - Load-sensitive timing tests, not failures of this diff: three wall-clock tests failed in that
    run, which took 9:55 at a 15-minute load average of 7.7. Rerun alone, all 10 cases passed.
    This diff does not touch them:
    - `auth/test_login.py::test_unknown_user_timing_close_to_wrong_password`
    - `core/test_data_uri_envelope.py::test_a_pathological_value_is_rejected_in_linear_time[bad-length]`
    - `core/test_data_uri_envelope.py::test_a_cap_sized_valid_payload_parses_in_linear_time`
  - `needs_postgres` lane: 67 passed.
  - Push: the pre-push hook diffs against the main merge base, where `OME-1784`'s branch-bound
    approvals fail closed. The team lead chose to rebase onto `main` once #1614 merges, then re-run the
    gate with `--base origin/main` and push.
- **Review:** sf-code-review, no blocking findings; should-fix 1-4 and minor 1-6 applied.
- **Deviations:**
  - T-F2: `_AsyncCredentialBlobProbe` stays (used by `unit/auth/test_jwt_secret.py` and
    `test_writer_floor_refresh.py`); only its dead `mutate` is removed.
  - Three prior tests outside the §6 L4b row change, approved by the owner on 2026-10-30 as
    direct consequences of §4.4 k1/K1: `unit/test_credential_blob_store.py` (two `mutate` tests
    deleted, tombstone), `unit/test_credential_blob_operational_outcomes.py`
    (`test_credential_mutation_resets_the_operational_register` deleted, tombstone),
    `unit/core/provider_access/test_availability_follows_resolve.py` (`"mutate"` dropped from the
    forbidden-method tuple).
  - Importers: 30 files import `tests.credential_names` and 26 change only the import line; the
    spec estimated 34.
  - Extra comment sites with the same stale claim as the listed ones:
    `core/plugin_base/_contract.py` (a second "caller-independent"),
    `core/request_cache/global_plan.py` and `plugins/openai_provider/plugin.py` (the retired
    Profile-default merge), `core/frozen_copy/headers.py`.
  - T-F12 "other suite docstrings": `openai/test_openai_route_global_cache.py`,
    `openai/test_openai_route_global_cache_modifier.py` and `openai/test_openai_keyed_max_tokens.py`
    (one comment in a test body, in the manifest).
  - K4 drops the Profile-default literals: no Connection can carry them.
- **Follow-ups (not in this unit):**
  - Five test doubles still define a `mutate` nothing calls: `unit/test_api_key_strategy.py`,
    `unit/remote_endpoint/test_plugin.py`, `unit/remote_endpoint/test_origin_binding.py`,
    `unit/gemini/test_gemini_auth.py`, `unit/codex/test_codex_auth.py`.
  - No committed test pins the chat cache hit with unreadable marker and Connection stores
    (`routes/chat.py` Stage 1 WHY).
