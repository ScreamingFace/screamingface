---
ticket: OME-1250
stack: aigateway
status: in_progress
started: 2026-09-30
finished:
---

# degraded-connection-status — Report ordered provider outcomes without revoking credentials

## Intent

Make the backing-neutral availability listing stop reporting `connected` after an
out-of-credits provider response while preserving the valid credential's ability to dispatch
and recover automatically after a later successful call.

## Planned changes

- Add a revision-fenced, ordered operational outcome register to credential blobs via migration 0013.
- Observe only non-streaming API-key dispatch through a migrated pair's effective Connection when the provider declares an operational-outcome classifier; preserve Profile, unmarked native Connection, OAuth, streaming and Local Engine behavior.
- Reserve one dispatch sequence before authorization reads the key. Replacement/deletion invalidates the immutable observation token.
- Persist only adapter-classified `needs_reauth`/`insufficient_credits` and real provider success; cache hits, retries, 429, 5xx, transport and local conversion failures are neutral.
- Project the existing wire statuses: `needs_reauth` for confirmed auth rejection, `error` for confirmed insufficient credits, `connected` after success/no outcome. Add no status or DTO field.
- Replace the migrated Connection 401 lifecycle mutation while preserving strategy/session invalidation and the original provider-failure body; later resolve refusals intentionally become operational 401s.

## Test plan

- Add failing migration/store tests for revision reset, ordered completion, stale credential replacement and reversed completion order on SQLite and PostgreSQL.
- Add failing migrated-authority tests proving insufficient credits remains resolvable, needs-reauth refuses, and availability projects both through the existing enum.
- Add failing OpenRouter tests for classified 401/402, successful recovery and neutral cache/retry/transient paths.
- Preserve unmarked native Connection, Profile, OAuth and streaming behavior; pin the original classified 401 detail and the later operational-refusal detail.
- Preserve and run existing provider-access, OpenRouter dispatch, route, and full AIGateway suites.

## Acceptance

- A classified OpenRouter 402 records `insufficient_credits` without changing Connection lifecycle and availability reports `error` while dispatch remains allowed.
- A classified OpenRouter 401 records `needs_reauth`, availability reports `needs_reauth`, and later dispatch is refused with the OME-1198 named-profile 401 shape instead of the bare Connection's former 404.
- A subsequent successful provider response records `connected` and availability recovers.
- Old-key and older-sequence completions are no-ops.
- Healthy migrated API-key resolution and listing each add one operational-state read; no provider probe, refresh or secret read is added to listing.
- Full AIGateway quality gates pass.

## Review Follow-up — Non-classifying Providers

- **Intent:** Preserve legacy op-5 handling for migrated effective API-key providers that do not
  declare an operational-outcome classifier, while avoiding row locking, sequence reservation and
  outcome writes on their healthy requests.
- **Planned changes:** Gate route observation on classifier support and let an observed but
  unclassified failure fall through to op 5. Do not change persistence or wire contracts.
- **Test plan:** Add an Anthropic migrated API-key route regression proving a 401 still marks the
  Connection error, rewrites `reauth_url`, refuses subsequent dispatch, and reserves no outcome
  sequence. Preserve all prior tests append-only.
- **Acceptance:** OpenRouter retains ordered 401/402/recovery outcomes; non-classifying providers
  retain baseline 401 handling and do not reserve or mutate the outcome register; official gates
  pass.

## Review Follow-up — Migration and Compatibility

- **SQLite rollback:** Restore the declared composite `UNIQUE(service, account)` constraint after
  reverse table rebuilds, in addition to standalone indexes. Prove it behaviorally by rejecting a
  duplicate after downgrade.
- **Rolling-version fence:** Install a PostgreSQL trigger after the outcome columns. A pre-0013
  writer that changes encrypted `value` without changing `credential_revision` increments the
  revision and clears both counters and the outcome; a current writer's explicit increment skips the
  trigger. Drop the trigger first on downgrade.
- **Resolve refusal:** Preserve the OME-1198 no-message wire contract after an operational 401:
  `name` is the requested selector and `reauth_url` is the bare legacy Profile URL. The original
  provider failure keeps its existing message-bearing replace-key URL.
- **Status surfaces:** Keep management lifecycle fields unchanged. `/v1/oauth/connections` remains
  `active`, and legacy Profile/admin projections remain `authenticated`, while
  `/v1/provider-access` reports operational `needs_reauth`. Reinterpreting those legacy lifecycle
  DTOs is a separate product contract, not an OME-1250 wire-compatible change.
- **Backfill boundary:** The register applies only to migrated effective API-key Connections.
  Profile-backed and unmarked native pairs intentionally retain baseline behavior. A 2026-09-23
  read-only census after the hosted-dev Stage B backfill found all 25 dev markers migrated; the
  deployment owner confirms production traffic also uses migrated Connections, so legacy Profiles
  are compatibility surfaces rather than runtime authority.

## Review Follow-up — LOW Boundaries and Process

- **Intent:** Remove address drift and raw storage failures without widening the stable
  `ProviderAccess` port or changing accepted lifecycle/operational projections.
- **Planned changes:** Derive the outcome-register blob slot from the provider strategy; translate
  operational-state read failures into retryable fail-closed 503 responses; make the credential test
  probe mirror replacement revision/reset semantics; correct stale comments and design cards.
- **Test plan:** Add append-only coverage for a non-default Anthropic account, route-level neutral
  429/5xx outcomes, reserve-before-authorize ordering, needs-reauth cache/session invalidation,
  effective-Connection fencing, API-key-only listing reads, storage-read/admission failures and test
  probe parity. New route tests live outside the frozen legacy validation allowlist and opt into
  readiness validation explicitly.
- **Acceptance:** A strategy's service/account is authoritative; storage failures render sanitized
  503 with `Retry-After`; neutral responses do not overwrite a classified outcome; only the two
  explicitly owner-approved fixture tests change and all official gates pass.

## Review Follow-up — Round 2

- **Intent:** Keep model admission consistent with chat during operational-store failures, preserve
  baseline availability when a disabled plugin cannot build a strategy, and extend the old-writer
  revision fence to SQLite rollback-without-downgrade.
- **Planned changes:** Render `CredentialStoreUnavailable` from admission as the shared retryable 503
  before collapsing ordinary provider-access refusals to not-credentialed; treat an unavailable
  strategy as no operational overlay rather than reauthentication evidence; install/drop the SQLite
  compatibility trigger with migration 0013; correct remaining runtime/design documentation.
- **Test plan:** Add append-only route coverage for admission 503, disabled-plugin lifecycle
  projection, successful 402 detail, LiteLLM `AuthenticationError`, and success-write fail-open;
  persistence coverage for SQLite old-writer replacement, `ORMStore.mutate` reset, and strict
  older-sequence rejection. Preserve all prior tests except the separately approved fixture edits,
  and preserve PostgreSQL evidence. The SQLite-guard requirement is superseded by Round 3.
- **Acceptance:** Admission and chat agree on retryable store failures; disabled plugins do not
  fabricate `needs_reauth`; old SQLite writers invalidate stale observations; every named surviving
  mutant is killed; code, ledger, spec and design cards describe the same behavior.

## Review Follow-up — Round 3

- **Intent:** Remove the SQLite old-writer guard after independent review proved that its internal
  update changes Tortoise 1.1.8's reported row count from one to two and makes a rolled-back
  pre-0013 binary exhaust every optimistic `ORMStore.mutate` retry.
- **Decision:** Keep the PostgreSQL production rolling-version guard. On SQLite, require schema
  downgrade before binary rollback and accept the narrower stale-outcome risk when that procedure is
  not followed; a LOW stale observation is safer than breaking every legacy Profile mutation.
- **Test plan:** Add a migrated-SQLite regression proving a pre-0013-shaped value update still reports
  one affected row through Tortoise, strengthen the successful-response fail-open test to prove the
  outcome write was attempted, restore the 0012 migration test to its original latest-migration
  scope, and preserve the PostgreSQL old-writer suite.
- **Acceptance:** Migration 0013 installs no SQLite trigger; a legacy SQLite writer retains its
  single-row compare-and-set contract; PostgreSQL still resets the register for old writers; source
  docs and design cards state the dialect split; official gates and PostgreSQL evidence pass.

## Review Follow-up — Round 4

- **Intent:** Remove the final stale SQLite-trigger comment and documentation-index omission, and
  strengthen successful-response persistence coverage without changing runtime behavior.
- **Planned changes:** Delete the orphaned migration comment; list all seven OME-1250 card advances
  in the solution README; assert that a contained persistence exception does not reach the response;
  add append-only coverage proving successful dispatch records its outcome exactly once.
- **Test plan:** Run the two focused success-recording tests, all AIGateway quality checks with the
  approved fixture exception, history-aware design validation and both-worktree diff checks.
- **Acceptance:** Runtime behavior is unchanged; persistence remains fail-open and non-leaking after
  a successful provider response; exactly one success write is attempted; README and migration
  comments match the implemented PostgreSQL-only trigger design.

## Outcome (fill at the end — required before COMMIT)

### Publication integration

- The optional `unavailable` consumer integration was reverted before publication. This change
  preserves the existing availability family: confirmed insufficient credits project `error`,
  confirmed credential rejection projects `needs_reauth`, and successful dispatch recovers.
- Integrated `main` at `db6757bc56a7f6b49b38ae16e7059c06a55cda3f`, preserving its newer
  selector-refusal and dispatch-error logging behavior in the four changed route files. Dispatch
  observation and error-type provenance now travel through the same terminal failure boundary.
  Integration commit: `ce03cc2fa`.
- The combined implementation passed the complete AIGateway static and >=80% coverage checks,
  SQLite migration suites 0012/0013 (13 cases), PostgreSQL outcome suite (4 cases), whitespace
  checks and mirror/ledger consistency validation. The remaining provider/service-health scope
  stays open.
- Strict test-preservation checking reports only the two previously approved fixture-body edits.
  The owner also approved a single publication push without its repeated local hook check, after
  the complete checks above passed; no hook or repository configuration is changed.

- **Actual files:** Added the credential outcome value types and migration 0013; extended the
  credential-blob model/store with revision reset, ordered admission and conditional completion;
  added the optional provider operational-access capability, effective-Connection projection,
  OpenRouter classification and non-streaming route recording; added SQLite migration/store,
  provider-access, route-level and real PostgreSQL concurrency/contention coverage. Updated the
  accepted metamodel cards in the OME-1250 design worktree.
- **Review follow-up:** `chat.py` now reserves only for plugins declaring an operational classifier;
  `chat_dispatch.py` falls through to op 5 when a concrete failure is unclassified. Added route-level
  Anthropic migrated-API-key 401 coverage (including no reservation and no repeated dispatch) and
  OpenRouter unclassified-401 fallback coverage. Updated provider-access/chat-processing cards.
- **MEDIUM follow-up:** Migration 0013 now restores SQLite pair uniqueness on downgrade and installs
  a PostgreSQL old-writer revision guard. Operational resolve refusals again carry the pinned
  selector and bare legacy URL. Tests cover duplicate rejection, old/new writer increments and the
  exact second-401 body consumed by the SDK. Lifecycle/availability separation and the migrated-pair
  boundary are recorded explicitly; hosted dev was observed backfilled and the deployment owner
  confirms production traffic uses migrated Connections.
- **Commit checkpoint:** This ledger is included in `fix(aigateway): project credential operational
  outcomes` on `OME-1250-degraded-connection-status`. Resolve its SHA from the commit history; this
  is the credential-evidence checkpoint, not closure of the full outage/service-health acceptance.
- **Gates:** The two fixture-body edits are explicitly owner-approved exceptions to test
  preservation. Lint, formatting, type checking, the enterprise-import guard and the >=80%
  coverage suite pass. Focused outcome suites pass; outcome tests pass 4/4 on PostgreSQL 16.
  Design validation completes with 0 errors and 8 pre-existing warnings. Independent
  follow-up review found no scoped blocker, including after the SQLite table-constraint restoration
  replaced the initially considered named unique index.
- **Deviations:** The exact stable `ProviderAccess` Protocol remains unchanged. The two new methods
  live on optional `ProviderOperationalAccess`, probed at runtime so existing structural substitutes
  retain legacy behavior. Migration 0013 also gained a PostgreSQL 3000 ms lock timeout and SQLite
  reverse-index restoration after deployment review. OAuth, streaming and Local Engine overlays
  remain explicitly out of scope.
- **LOW follow-up outcome:** Operational register reads now derive service/account from the provider
  strategy, and read/admission store failures render sanitized `503` with `Retry-After: 1`.
  `CredentialBlobProbe.write` mirrors runtime replacement revision/reset semantics. Added append-only
  route and authority coverage for neutral `429`/`5xx`, reserve-before-authorize order,
  needs-reauth eviction/invalidation, effective-Connection admission, API-key-only listing reads,
  storage failures and a non-default Anthropic account. Earlier OME-1250 route tests now opt into
  readiness validation explicitly instead of silently inheriting the frozen legacy fixture.
- **LOW process outcome:** Added the missing source spec and plan snapshot; corrected the ledger
  slug, wire/cost/backfill claims and stale runtime docstrings. Design cards now match post-conversion
  success recording, lifecycle `error -> error`, the intentional later OME-1198 401, and
  classifier-gated op 5.
- **LOW verification:** Focused outcome/provider-access suites passed (111 and 67 cases in the two
  broad runs); PostgreSQL 16 passed 4/4; all static checks passed; design validation returned
  0 errors and the same 8 pre-existing warnings; whitespace checks passed.
  The fixture-body edits were explicitly owner-approved test-preservation exceptions.
  Three full coverage runs each passed the other 5,033 tests at 92.61% coverage
  and failed only the previously reproduced baseline timing flake
  `test_unknown_user_timing_close_to_wrong_password`; that test passed in isolation. The round-2
  verification below supersedes this earlier blocked checkpoint.
- **Round-2 outcome (SQLite portion superseded by Round 3):** Dynamic model admission now relays
  operational-store outages as the shared
  sanitized retryable 503 instead of collapsing them to `provider_not_credentialed`. Availability
  preserves lifecycle projection when current provider configuration cannot build a strategy,
  rather than fabricating `needs_reauth`. Round 2 temporarily installed the old-writer revision/reset
  guard on SQLite as well as PostgreSQL; Round 3 retains only the PostgreSQL guard.
- **Round-2 coverage:** Added route tests for admission 503, disabled-plugin projection, persisted
  402 detail, LiteLLM `AuthenticationError`, success-write fail-open and missing-blob admission;
  store tests for `mutate` reset and strict sequence fencing; and a real SQLite CLI migration test
  that Round 3 replaces with legacy-writer rowcount coverage. The temporarily isolated 0012
  downgrade test is restored to its original latest-migration scope in Round 3.
- **Round-2 verification:** The new RED run failed only the three target defects; focused suites then
  passed 24/24 and 140/140, the 0012/0013 migration suites passed 13/13, and PostgreSQL 16 passed
  4/4. All enabled AIGateway checks passed with the approved test-preservation exceptions;
  the prior auth timing flake did not recur. Design validation returned 0 errors and the same 8
  pre-existing warnings; whitespace checks passed in both worktrees.
- **Round-3 outcome:** Removed the SQLite old-writer trigger after reproducing Tortoise 1.1.8
  returning affected-row count 2 for its outer update, which makes a pre-0013 `ORMStore.mutate`
  exhaust optimistic retries. PostgreSQL keeps its production rolling-version guard; SQLite binary
  rollback now explicitly requires schema downgrade, accepting the narrower stale-outcome risk when
  that procedure is skipped. Restored the 0012 downgrade test to its original latest-migration
  scope, so only the two owner-approved fixture edits remain test-preservation exceptions.
- **Round-3 coverage:** A migrated-SQLite test now proves a pre-0013-shaped value update still reports
  one affected row through Tortoise. The successful-response fail-open test also proves that outcome
  persistence was attempted exactly once before its failure was contained.
- **Round-3 verification:** The rowcount regression first failed with actual value `2`, then the
  0012/0013 migration suites passed 13/13 after removing the SQLite trigger. PostgreSQL 16 outcome
  tests passed 4/4. Strict test-preservation checking reports only the two owner-approved fixture
  edits; all other static checks and the full >=80% coverage suite passed. History-aware design
  validation returned 0 errors and the same 8 pre-existing warnings after required card version bumps.
- **Round-4 outcome:** Removed the orphaned comment for the deleted SQLite trigger and expanded the
  solution README from four to all seven advanced OME-1250 cards. Success-recording coverage now
  asserts both that a contained persistence failure cannot expose its message and that a normal
  successful dispatch attempts exactly one outcome write.
- **Round-4 verification:** The two focused route tests passed 2/2. All static checks and the full
  >=80% coverage suite passed with the approved fixture exceptions. History-aware design validation
  returned 0 errors, the same 8 pre-existing warnings and all seven changed entities correctly versioned.
- **Remaining scope:** OME-1250 remains In Progress;
  `429`, `5xx`, transport faults and gateway/engine outages are not solved by this checkpoint.
  Design cards remain in their separate worktree; no push, PR or Linear mutation accompanies this
  source commit.
