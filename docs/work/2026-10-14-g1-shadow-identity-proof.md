---
ticket: OME-1497
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-14
finished: 2026-10-14
---

# g1-shadow-identity-proof — legacy OAuth shadow identity proof for row 11 (G1, part 3 of 3)

## Intent

Last PR of the G1 successor of the D18 contract
(`docs/spec/2026-10-02-provider-credential-admin-contract.md` §5 row 11, §5.1 "Legacy OAuth
shadow — identity proof", §8 falsifiers; plan section C.1). A legacy OAuth callback on a `none`
pair writes a Profile and a shadow Connection at a different (UUID) locator. Their blobs diverge at
the first refresh, so the pair lands in row 11 and parts 1-2 refuse PUT/DELETE with 409
`credential_pair_unresolved`. This unit lets PUT and DELETE through when the pair is proven to be
one credential by OAuth identity: the Profile blob is decrypted in process, its identity extracted
with the plugin's `extract_identity` (the mechanism the callback used for
`OAuthConnection.identity_sub`), and the two subs must both exist and be equal. Anything else keeps
the 409 and the operator path. LIST is unchanged and never decrypts.

## Planned changes

All under `apps/aigateway/src/aigateway/` unless noted.

- `core/provider_access/pair_shadow.py` (new): the proof — read and decrypt the Profile blob,
  extract its identity, compare with the Connection's `identity_sub`; refusal as
  `PairNotManageable(provider, "unresolved")`. No refresh, no logging of decrypted data.
- `core/provider_access/pair_admin_writes.py`: `_capture` runs the proof for a provable row 11
  (`none`, one Profile, one live Connection); PUT publishes through the Connection exactly as row 9
  with the Profile document as the mirror under its own name, then retires the Profile blob in the
  same transaction; DELETE also removes the Profile blob. In the transaction the Connection's
  `identity_sub` is re-read; a change answers superseded.
- `core/provider_access/connection_admin.py`: only if a claim-time hook is needed for the
  in-transaction re-read.
- Tests: `tests/unit/core/provider_access/test_pair_shadow_identity.py` (new),
  `tests/unit/test_admin_connections_mutation_routes.py` (route mapping, appended only).

## Test plan

- PUT on a proven shadow: 200; the Connection keeps its id and locator, becomes an active API-key
  row and the effective reference; the Profile document is the only document (mirror); the
  Profile blob is gone; the Connection's blob holds the new key.
- DELETE on a proven shadow: the Connection is revoked, its blob and the Profile blob are gone, no
  document is left, the marker is `migrated` with a null reference.
- The proof holds AFTER a refresh rotated the Profile token (different blob, same identity).
- Refusals write nothing and run no key check: Profile identity missing (plugin returns None),
  Connection `identity_sub` missing, different identities, undecodable Profile blob (not JSON / not
  an object), missing Profile blob.
- The proof is not applied to `migrated` with a null reference beside a live row (still 409).
- A Connection whose `identity_sub` changes after the capture supersedes the write (PUT and
  DELETE); nothing is written.
- Prior tests unchanged, including the existing row-11 refusal (no identity → 409).

## Acceptance

- The §8 falsifier "legacy OAuth on `none` creates Profile plus shadow at different locators →
  LIST conflict without decrypt; PUT/DELETE succeed when both identities exist and match,
  including after a refresh has rotated the Profile token; refuse when an identity is missing,
  unextractable or different" passes.
- `uv run .claude/scripts/run_gates.py aigateway --base origin/main` all green; PostgreSQL lane
  for the mutation tests green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** under `apps/aigateway/`:
  - `src/aigateway/core/provider_access/pair_shadow.py` (new, 113 lines): `prove_shadow` and the
    in-claim `require_shadow_identity`.
  - `src/aigateway/core/provider_access/pair_admin_writes.py`: row 11 leaves the refused rows and
    goes through the proof at capture; PUT runs the publication inside one outer transaction,
    retires the Profile blob last and evicts both credential names after the commit; DELETE
    re-reads the identity and retires the Profile blob too.
  - `src/aigateway/core/provider_access/connection_admin.py`: `publish_api_key` takes an optional
    `claim_check`, run right after the live re-check and before any index, row or blob write.
  - Tests (new, 31 cases): `tests/unit/core/provider_access/pair_shadow_harness.py` (seeds and
    probes), `test_pair_shadow_identity.py` (proof holds, every refusal, no decrypted data in a
    refusal or log) and `test_pair_shadow_identity_writes.py` (atomic PUT, post-commit eviction,
    a re-auth after the proof supersedes).
  - No route change: the existing 409 pair detail and superseded mappings already cover the
    outcomes, so `test_admin_connections_mutation_routes.py` was not touched.
- **Commits:** see the PR.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base origin/main` → ALL GATES GREEN.
  PostgreSQL lane (`AIGW_TEST_PG=1 uv run pytest -m needs_postgres`): 70 passed, 5 failed — all 5
  in `test_cache_snapshot_upload_postgres.py`, a local `pg_dump` 15 vs server version mismatch,
  unrelated and unchanged from part 2. Mutation checks: the new tests fail against the part-2
  writer, without the in-claim identity re-read, without the Profile blob retirement, without the
  extractor guard, the decryption mapping, the OAuth-only check, or the post-commit eviction.
- **Review fixes (independent review before the PR):**
  - An exception raised by a plugin's `extract_identity` escaped as a 500 and could hold the
    token in its arguments; it is now the 409 operator path, decided outside the `except` block
    so no exception becomes the refusal's cause or context.
  - A Profile blob the secret store cannot decrypt answers 409 unresolved as §5.1 says, instead of
    the row-1 503 (it never becomes readable, so "temporarily unavailable" would be false).
  - The proof requires the Connection to be an OAuth row: an API-key row keeps a stale
    `identity_sub`, and a match would make DELETE remove two distinct credentials.
  - The PUT's outer transaction moved the publication's own cache eviction before the commit; the
    Connection's credential name is now also evicted after the commit, for every row.
- **Deviations:**
  - PUT proves at both of its captures (before and after the key check), so an unprovable pair is
    still refused before any provider I/O; a plugin that needs a network call for the identity
    makes it twice.
  - On PUT the Profile document stays as the private mirror under its own name (the §5.2 row-6
    rule), so no second `default` document pushes the pair into row 3.
  - Anthropic's plugin extracts no identity, so an Anthropic legacy shadow is never proven and
    keeps the 409 operator path; codex, gemini and antigravity benefit.
  - No PostgreSQL race test for a Profile refresh against the shadow PUT; the lock order was
    reviewed (marker → index → Connection row → Connection blob → Profile blob, consistent with
    both refresh owners) but not raced.
