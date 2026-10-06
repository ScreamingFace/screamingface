# OME-1250: Degraded Connection Status Plan

## Persistence

1. Add revision, dispatch-sequence, outcome-sequence, outcome, and observation-time columns to
   `credential_blobs` in migration 0013.
2. Reset the register and increment credential revision on credential replacement. Preserve this
   behavior across PostgreSQL rolling-version overlap and SQLite downgrade/re-upgrade. Require schema
   downgrade before rolling a SQLite database back to a pre-0013 binary so legacy optimistic writes
   retain their single-row result.
3. Reserve a sequence under row lock and complete with a compare-and-set on blob UUID, credential
   revision, and increasing outcome sequence.

## Provider Access

1. Add optional `ProviderOperationalAccess` without widening stable `ProviderAccess` substitutes.
2. Gate admission on migrated-pair authority, effective Connection identity, API-key auth, and
   provider classifier capability.
3. Resolve the blob address from the provider strategy's `credential_service()` and
   `credential_account()` methods.
4. Project `needs_reauth` and `insufficient_credits` through the existing availability enum while
   preserving lifecycle management DTOs.
5. Convert operational-store failures to sanitized retryable 503 refusals; keep completion writes
   fail-open after a provider response is already determined.
6. Preserve lifecycle availability when current provider configuration cannot build a strategy;
   strategy absence is not evidence that a stored credential was rejected.

## Dispatch

1. Reserve after cache miss and target resolution, before credential authorization.
2. Classify terminal sanitized failures through the provider hook; let unclassified failures fall
   through to legacy op 5.
3. Record success after response conversion, before cache fill and final accounting publication.

## Verification

- Append-only SQLite tests for replacement reset, stale and reversed completions, legacy-writer
  rowcount, strategy-native slots, route neutrality/order, effective-Connection fences,
  API-key-only listing, storage failures, invalidation, and fixture parity.
- PostgreSQL 16 tests for row locking, compare-and-set ordering, lock timeout, and old-writer
  compatibility.
- Run focused suites, all AIGateway quality checks, migration round trips, design validation,
  and final diff review.
