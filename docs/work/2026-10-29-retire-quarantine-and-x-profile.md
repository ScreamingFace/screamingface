---
ticket: OME-1784
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-29
finished:
---

# retire-quarantine-and-x-profile — retire the quarantined marker state and the X-Profile compatibility path (OME-1138 close-out, L4a)

## Intent

Stage E retired the Profile machinery, but the gateway still carries compatibility code that
nothing writes or needs: the `quarantined` marker state (no writer since E5c deleted the
backfill), the `SelectorPolicy.HONOUR` window policy with named `X-Profile` selection and its
`SelectorUnknown` refusal (production has run `REJECT_EXPLICIT` since Stage D), and the
`AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE` warning. This leaf removes them, stops reading and writing
`migration_note` (the column stays one more release; L4c drops it), and rewrites the marker
docstrings so `none` / absent read as Connection-owned. Close-out spec
`docs/spec/2026-10-29-ome-1138-closeout.md` §4.2, §6, §8, §9 Q1; plan
`docs/plan/2026-10-29-ome-1138-closeout.md` §2 and §3 "L4a" (both landing via PR #1607). Stacked
on L1 (OME-1778, `docs/spec/2026-10-29-availability-fold-in.md`), whose `_select_by_label` this
leaf reduces to the default case.

## Planned changes

Gateway paths under `apps/aigateway/src/aigateway/`:

- `core/provider_access/selector.py`: `SelectorPolicy` goes; `Selector.from_header` refuses every
  present value; `Selector` stays as the port's default-only value.
- `core/provider_access/__init__.py`: drop the `SelectorPolicy` and `SelectorUnknown` exports.
- `core/provider_access/types.py`: `SelectorUnknown` goes; `SelectorUnsupported` and
  `PairNotManageable` docstrings updated.
- `core/provider_access/connection_backed.py`: `_select_by_label` keeps the default case only;
  `_answers` and the `quarantined` resolve branch go; availability no longer skips `quarantined`.
- `core/provider_access/pair_authority.py`: `MigrationState` / `MIGRATION_STATES` lose
  `quarantined`; `migration_note` is neither read nor written; docstring rewritten.
- `core/provider_access/writer_floor.py`: `claim_pair` stops re-publishing the note; docstrings.
- `core/provider_access/pair_admin.py`: D18 row 4 goes; `pair_admin_writes.py` `_REFUSED_ROWS`
  keeps rows 3 and 11; docstrings.
- `core/provider_access/models/provider_credential_slot.py`: docstrings; the `migration_note`
  field stays with a `WHY:` naming L4c. No migration (the autodetector must propose nothing).
- `core/provider_access/connection_native.py`, `routes/oauth_connections.py`: marker docstrings.
- `routes/provider_access_http.py`: `selector_from_request` takes no policy; the `SelectorUnknown`
  404 row goes; the `PairNotManageable` comment names the remaining rows.
- `main.py`: the `SelectorPolicy` wiring and the bootstrap-flag warning go.

Tests under `apps/aigateway/tests/`: new RED tests, plus the prior tests spec §6 lists for L4a
(manifest at PR-open).

Docs, at merge time only (owner decision, 2026-10-30; no code change): the Stage E section of
`apps/aigateway/DEPLOYMENT.md` that #1612 (OME-1780, L10) adds. It is not edited now, because
the base does not have the section yet.

**Merge-time step.** If #1612 has merged by the time this branch is rebased onto `origin/main`,
this leaf adds a precondition to that section. The precondition applies before running an image
that includes OME-1784:

- Run `SELECT count(*) FROM provider_credential_slots WHERE migration_state = 'quarantined';`
- If the count is not zero (pairs the E5b backfill could not prove), run
  `UPDATE provider_credential_slots SET migration_state = 'none', migration_note = NULL WHERE migration_state = 'quarantined';`
- The pair is then served by its single active Connection, or the user reconnects. Profile rows
  left behind when the purge skips an account are inert.

The same edit replaces #1612's sentence "a quarantined pair is refused with 409
credential_pair_unresolved, and a new Connection does not clear it", which this leaf makes false.
Why: on main nothing settles a quarantined pair, and after this leaf the store refuses the whole
account. If #1614 merges first, L10 carries the step instead.

Raised with the owner on 2026-10-30 and not yet decided: #1612 also adds, in
`docs/diagrams/gateway-identity.md`, "A pair the Stage B backfill quarantined is refused with
`409 credential_pair_unresolved`", which this leaf also makes false.

## Test plan

RED first (plan §3 L4a):

- Any present `X-Profile` value (named, `default`, padded) raises `SelectorUnsupported`, and
  `from_header` takes no policy argument; absent or blank is the implicit default.
- `SelectorPolicy` and `SelectorUnknown` are no longer exported from
  `aigateway.core.provider_access`, and the composition root sets no selector policy.
- `MIGRATION_STATES == {"none", "migrated"}`; a stored `quarantined` is refused as unknown on
  `read` and on `list`, and `advance` refuses it.
- The marker view carries no `migration_note`, and no write sets it.
- The D18 disposition has no row 4.
- No module under `src/aigateway` reads `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE`.
- The fake witness agrees with the real backing for the default selector only.

## RED choice — the fake witness

`test_provider_access_availability.py::test_the_fake_witness_applies_the_same_precedence` is
RE-EXPRESSED in Connection terms, not removed: L1's agreement table
(`test_availability_follows_resolve.py`) runs over the real backing only, so it cannot subsume a
check on the fake. The replacement, `test_the_fake_witness_agrees_with_the_real_backing`, seeds
the same six default-selector situations into `FakeHarness` and `ConnectionBackedHarness`
(stored credential authenticated / pending / errored, errored beside an active row, one active
row, two active rows) and asserts both list the same status. `provider_access_fake.py` now models
"a stored credential" as the pair's effective Connection, as the real harness seeds it.

RED evidence: `tests/unit/core/provider_access/test_compatibility_paths_retired.py` — 31 failed,
3 passed before GREEN (each for the expected reason: a policy still read from `app.state`, the
named vocabulary still exported, the third state still known, row 4 still a conflict). The
absence check for the bootstrap flag is the re-expressed
`tests/unit/test_profile_index_offline_only.py::test_no_module_reads_the_retired_bootstrap_flag`,
red against `main.py` before GREEN.

## Owner approval (Dmitry Stebukov (owner), 2026-10-29)

Four prior test files outside the spec §6 list change as direct consequences of spec §4.2. The
owner approved all four; they join the manifest at PR-open.

- A `unit/core/provider_access/test_provider_access_http.py`: the `SelectorUnknown` import and its
  404 row go (mechanical).
- B `unit/core/provider_access/test_pair_admin_connection_only.py`: `PairAuthority` is built with
  five fields; the comment names the `unresolved` refusal (mechanical).
- C1 `unit/core/provider_access/test_connection_backed_resolve_contract.py`: the two twins of the
  contract's migrated-pair tests are deleted and `NOT_REIMPORTED` shrinks to the fake-only witness.
  Their assertions now run in the resolve contract on both witnesses; the module docstring is
  refreshed.
- D `unit/test_bootstrap.py`: a comment names the renamed bootstrap absence check (mechanical).

## Acceptance

- `uv run .claude/scripts/run_gates.py aigateway --base OME-1778-availability-fold-in` is green;
  every changed prior test is in the manifest.
- `AIGW_TEST_PG=1 uv run pytest -m needs_postgres` is green.
- Gateway src outside migrations `0012`–`0015` names none of `SelectorPolicy`, `HONOUR`,
  `SelectorUnknown`, `quarantined`, `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE`; `migration_note`
  remains only on the model field.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the 13 planned gateway src files (no others). Tests: the new
  `test_compatibility_paths_retired.py`; one test appended to
  `test_provider_access_authorize_contract.py` (a pure append, outside the manifest); 27 changed
  prior test files, all in `.claude/test-change-approvals/OME-1784.json` (the 23 spec §6 files and
  the four owner-approved ones). Also this ledger and the mirror
  `docs/tasks/2026-10-29-OME-1784-retire-quarantine-and-x-profile.md`. No migration: the
  autodetector proposes only the pinned "Alter field account on OAuthConnection", the same as on
  the L1 tip.
- **Commits:** pending: `refactor(aigateway): retire the quarantined state and the X-Profile compatibility path`.
- **Gates:** `run_gates.py aigateway --base OME-1778-availability-fold-in`: ALL GATES GREEN
  (append-only with the 21 flagged files approved by the OME-1784 manifest, ruff check, ruff
  format, pyright, check_no_enterprise, pytest with coverage ≥80; 7430 tests collected).
  `needs_postgres`: 67 passed. `check_mirror_status.py`: green. The src acceptance grep is
  clean: `migration_note` remains only as the model field (`provider_credential_slot.py:46`).
  RED before GREEN: 31 failed, 3 passed.
- **Deviations:**
  - Owner approval (2026-10-29) for the four out-of-list files A, B, C1 and D above.
  - Behaviour: a stored `quarantined` row now gets chat 500 (`PairAuthorityDataError`) instead of
    409 `unresolved`. The inventory refuses it with `CredentialAuthorityUnavailable`, and
    availability refuses the account. Accepted under spec §4.2; guarded by the owner-approved
    read-only count of `quarantined` and non-null `migration_note` rows (0 in dev, stage, prod)
    before merge. Stated in the PR body.
  - The in-list changes go beyond the plan's line hints. Deleted with the retired paths:
    `test_a_named_selector_on_a_migrated_pair_*` (2),
    `test_a_quarantined_pair_refuses_with_the_pair_code_and_reads_no_index`,
    `test_chat_and_model_parameters_answer_a_quarantined_pair_with_409_unresolved`,
    `test_availability_reports_a_non_migrated_pair_as_not_connected` (its last case was
    `quarantined`), `test_a_quarantined_pair_is_unresolved_and_its_note_never_surfaces`,
    `test_quarantine_keeps_legacy_authority_and_carries_the_report`,
    `test_a_claim_keeps_a_quarantined_state_and_its_note`,
    `test_a_claim_keeps_a_rollback_note_on_a_none_pair`,
    `test_a_lost_check_on_a_quarantined_pair_keeps_its_state_and_note`, the label and unknown-label
    resolve contract tests, and the five `SelectorPolicy` tests (replaced by
    `test_every_present_selector_is_refused`). Renamed to Connection terms: the routing locator
    test, the fake witness test, the writer-fence test, the D18 body test
    (`test_an_unresolved_pair_renders_one_body_on_the_legacy_and_successor_routes`), two resolve
    contract tests, and the bootstrap check (`test_no_module_reads_the_retired_bootstrap_flag`).
  - `test_pair_admin_review_fixes.py`: a raw-planted `quarantined` row on an unknown provider now
    expects `CredentialAuthorityUnavailable`.
  - Review (2026-10-29): `test_operational_outcome_boundaries.py` gains
    `test_dispatch_observation_refuses_a_row_the_marker_moved_away_from`. It fails when
    `connection_backed.py`'s observation check is weakened to `effective_connection_id is None`.
    The fake now touches `last_used` on every backing, pinned by the appended
    `test_a_successful_stored_credential_authorize_touches_its_connection_last_used`, which runs on
    both witnesses and was red on the fake first. Stale comments in `types.py`,
    `provider_access_http.py` and `test_profile_reader_removed.py` were reworded.
- **Follow-ups (not in this leaf):**
  - Fake fidelity for a missing or revoked effective row: no harness can build that state today.
  - Validation in `Selector.__post_init__`: unreachable, since only `from_header` builds a
    `Selector`.
  - A route test pinning the 500 for a stored `quarantined` row: the PR body states the accepted
    change, and the composition tests cover the error.
  - L4c drops the `migration_note` column.
