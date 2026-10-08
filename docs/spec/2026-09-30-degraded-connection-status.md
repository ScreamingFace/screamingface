# OME-1250: Degraded Connection Status

## Intent

Expose the last informative operational result of a migrated effective API-key Connection without
turning recoverable provider conditions into credential lifecycle mutations.

## Contract

- Keep the public availability family unchanged: `not_connected`, `pending`, `connected`,
  `needs_reauth`, `error`.
- Keep Connection management lifecycle unchanged. Operational `needs_reauth` and `error` are
  projections of credential evidence, not new lifecycle values.
- Persist `connected`, `insufficient_credits`, or `needs_reauth` on the credential blob with a blob
  UUID, credential revision, and monotonic dispatch sequence fence.
- During PostgreSQL rolling overlap, a compatibility trigger resets the register when a pre-0013
  writer replaces credential bytes. SQLite binary rollback requires schema downgrade first: an
  internal-update trigger would change Tortoise 1.1.8's affected-row count and break legacy
  optimistic mutations, so rollback without downgrade retains a documented stale-outcome risk.
- Observe only non-streaming dispatch through a migrated pair's effective API-key Connection when
  its provider declares an outcome classifier. OpenRouter classifies validated `401 auth_required`
  and `402 insufficient_credits`.
- Reserve before authorization. Replacement or deletion makes an old observation a no-op; a later
  admitted informative completion wins regardless of completion order.
- Record `connected` only after the provider response converts successfully. Cache hits, local
  conversion failures, transport failures, `429`, `5xx`, and unclassified failures are neutral.
- A classified `needs_reauth` evicts the strategy and invalidates its session but leaves Connection
  lifecycle active. The original provider response keeps its replace-key URL; a later resolve uses
  the OME-1198 named-profile 401 shape instead of the bare Connection's former 404.
- `insufficient_credits` projects availability `error` but remains dispatchable so success can
  restore `connected`.
- Derive the operational register's service/account from the credential strategy. Storage read or
  admission failures fail closed as sanitized `503` responses with `Retry-After: 1`, including
  dynamic model admission.
- Availability may read local operational metadata and construct the strategy needed to locate it;
  it never decrypts credentials, refreshes tokens, calls providers, or mutates state. If current
  provider configuration cannot construct a strategy, availability preserves lifecycle projection
  rather than fabricating `needs_reauth`; dispatch still returns its unsupported-auth refusal.

## Scope

Hosted runtime uses migrated Connections. Profile-backed and unmarked native paths remain
compatibility behavior; OAuth and streaming outcome publication remain outside this unit.
