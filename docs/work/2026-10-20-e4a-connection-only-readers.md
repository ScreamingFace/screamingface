---
ticket: OME-1685
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-20
finished:
---

# e4a-connection-only-readers — resolve, availability and D18 classification read no Profile document

## Intent

Stage E of `OME-1209` (epic `OME-1138`), landing E4a of E4 (spec §9 Q11). The read-only census of
2026-10-20 meets the E4 precondition: every pair with a Profile document is `migrated` in dev (26,
plus one `none` pair with no document), stage (no credentials) and prod (6). Until now the runtime
read path still consults the legacy Profile index: an absent, `none` or `quarantined` marker resolves
through `ProfileBackedProviderAccess`, a `migrated` pair reads the index to choose between its
effective Connection and the label path, availability folds Profile states, and the D18 successor
classifies pairs over Profile documents (rows 8, 10, 11 and the shadow proof). E4a removes every one
of those reads (spec §9 Q8, Q9): an absent or `none` marker resolves through the pair's Connections,
a `quarantined` marker fails closed with 409 `credential_pair_unresolved`, a `migrated` pair uses its
effective Connection when the marker names one and the label path otherwise. Writes stay for E4b,
plugin hook renames for E4c. No document or blob is deleted (R5).

## Planned changes

- `core/provider_access/profile_backed.py`: deleted. `context_stamp`, `connection_target` and
  `targetless` move to a new `core/provider_access/targets.py`; `provider_access_for` and
  `operational_access_for` move to `connection_backed.py` and build the Connection-backed class.
- `core/provider_access/connection_backed.py`: no longer a subclass. Resolve decides on the marker
  only (quarantined: `PairNotManageable("unresolved")`; migrated with an effective Connection: that
  Connection; otherwise the label path). Availability lists the registry and migrated markers; any
  other provider is `not_connected`.
- `core/provider_access/connection_authority.py`: `migrated_target` drops its unused `document`.
- `core/provider_access/profile_authorize.py`, `refresh_guard.py`: the Profile-target branches of
  authorize and op 5 go (`mark_profile_error_fresh`, `ProfileRefreshOwner`, the Profile detail
  rewrite and the Profile `WriteConflict`).
- `core/provider_access/pair_admin.py`: `classify_pair` takes no documents; rows 8 and 10 and the
  document half of row 3 go; LIST reads no index.
- `core/provider_access/pair_shadow.py`: deleted. `pair_admin_writes.py` refuses row 11 like row 4,
  captures without the index and drops the row-8 blob delete and the shadow retire;
  `connection_admin.publish_api_key` drops `claim_check`.
- `routes/provider_access_http.py`: `render_refusal` renders `PairNotManageable` with the D18 body,
  so chat and model parameters answer 409 `credential_pair_unresolved`.
- `core/provider_access/__init__.py`, `ports.py`: exports and wording.

## Test plan

New tests first (prior tests are append-only until the owner approves the test map):

- resolve with an absent or `none` marker serves the label path, chatless or ambient, and reads no
  index (spy on `get` and `list` of the wired store); a lone Profile document is not a target;
- a `quarantined` pair refuses with `PairNotManageable("unresolved")` and no index read; chat and
  model parameters render 409 `credential_pair_unresolved`; model admission reports not credentialed;
- a `migrated` pair with an effective Connection resolves it with or without a document; with a null
  reference it takes the label path;
- availability reports a migrated pair's Connection status, every other registered provider
  `not_connected`, with no index read;
- D18 LIST reads no index and lists no Profile; a `none` pair with a Profile beside its one
  Connection is row 9; row 11 is refused; a Profile-only pair is empty;
- the removed names (`ProfileBackedProviderAccess`, `ProfileRefreshOwner`, `mark_profile_error_fresh`,
  `profile_backed`, `pair_shadow`) are gone; `provider_access_for` builds the Connection-backed port.

## Acceptance

- Resolve, availability and D18 classification read no Profile document (spy and text search).
- Migrated pairs with a document named for the selector resolve, authorize, dispatch and report
  availability as before; the others follow spec §9 Q9 (see Deviations).
- Retired and adapted prior tests are listed in the approval manifest with their successor coverage.
- `run_gates.py aigateway` green; the PostgreSQL lane green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** source as planned (11 files under `core/provider_access/` plus
  `routes/provider_access_http.py`; `profile_backed.py` and `pair_shadow.py` deleted, `targets.py`
  new), and comment-only edits in `main.py` and `types.py`. New tests:
  `test_connection_only_resolve.py`, `test_pair_admin_connection_only.py`,
  `test_profile_reader_removed.py`, and the shared seed `tests/unit/migrated_pair_seed.py` (a
  migrated pair whose effective Connection sits at the Profile blob address). 47 prior test files
  adapted per the owner-approved test map and listed in the approval manifest: tests whose
  behaviour is gone are retired (Profile-wins resolve, rows 8 and 10, the row-11 shadow proof,
  Profile op 5), the rest re-seeded as a migrated pair with unchanged assertions, renamed, or
  adapted per the map. The PostgreSQL LIST-fence test joined the map after the lane run: its hold
  moves from the Profile list to the Connection list, the candidate read LIST still brackets.
  Retired files keep a docstring naming their successors. Spec §9 Q8–Q11 and the plan's E4a
  section record the decisions.
- **Review:** an independent review of the first commit found that the D18 PUT always named its
  compatibility mirror `default`, so a pair whose one document has another name gained a second
  document: a pre-E4 build would classify it row 3 and the R1 rollback would refuse it (D18 §5.2,
  plan: "every Profile write and the reads that only feed it" stay until E4b). Fixed with the
  owner's approval: the PUT reads the pair's documents only to name the mirror (one document → its
  name and address, otherwise `default`). Three retired PUT tests in `test_pair_admin_mutations.py`
  and the `"work"` assertion in `test_pair_admin_publication.py` are back to their `origin/main`
  text; `test_pair_admin_connection_only.py` pins the backfill's shape (a migrated pair at the
  `work` address keeps one document). Also from the review: a new fail-closed test (a revoked,
  errored or pending effective Connection is refused beside an active sibling; it fails on a
  sibling-serving mutant), stale comments in `main.py`, `types.py` and the DELETE docstring, the
  seed's docstring, and `test_an_unreadable_index_refuses_the_whole_inventory` renamed to
  `test_an_unreadable_store_refuses_the_whole_inventory`.
- **Commits:** `f929a4d5b` (E4a), then the review fixes.
- **Gates:** `run_gates.py aigateway --base origin/main` green including the append-only check
  (ruff, format, pyright, no-enterprise, pytest with coverage). PostgreSQL lane
  (`AIGW_TEST_PG=1 pytest -m needs_postgres`): 58 passed; the 5
  `test_cache_snapshot_upload_postgres.py` failures are the local `pg_dump` 15 client against the
  PostgreSQL 16 container, unrelated to this change.
- **Deviations:** a named selector on a `migrated` pair is answered by the effective Connection only
  when it is that Connection's label; any other name takes the label path (matched or refused, never
  retargeted). Production rejects named selectors, so this keeps the port's contract only. The
  rollback rehearsal in `test_connection_backed_shared_addresses.py` resolves with the default
  selector (owner-approved). A quarantined pair reuses `PairNotManageable("unresolved")`; model
  admission reports it as not credentialed and relays no pair code (no quarantined pair exists in
  any environment). The D18 PUT's post-commit duplicate eviction went with the Profile capture (the
  publication evicts after its own commit).
- **Behaviour change for migrated pairs without a document named for the selector** (the
  `connection_only` backfill category, or a Profile named other than `default`): they used to take
  the label path and now resolve their effective Connection (spec §9 Q9). Observable: a dispatch
  refusal carries the rewritten detail with `reauth_url`; a missing OAuth blob at authorize no
  longer marks the Connection `error`; an errored effective Connection is refused instead of an
  active sibling being served.
- **Known for E4b:** two refresh and publication tests still read the D18 PUT mirror's document;
  the dev bootstrap flag yields no usable chat credential between E4a and E4b (owner-accepted); a
  `none` pair's DELETE removes its documents but leaves a Profile blob at a document address until
  E5.
