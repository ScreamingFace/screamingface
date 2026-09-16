---
ticket: OME-1210
stack: aigateway
status: done
started: 2026-09-16
finished: 2026-09-16
---

# OME-1210 — Provider identity naming decision

## Intent

Make the remaining `OME-1138` work planning-visible and unambiguous before A2 starts. The current
adapter PR introduced a provider-access boundary while keeping the implementation Profile-backed.
The next slices need one vocabulary for domain language, API names, docs, UI copy and temporary
compatibility language.

## Decision

- **Connection** is the final product/API/domain noun for the provider credential resource. It is the
  term used for the target state: one effective credential per `(account, provider)`, shared by Local
  and Hosted, supporting OAuth and API keys.
- **Provider access** names the boundary and successor route family. It is not a persisted credential
  resource and should not become the object users manage.
- **Profile** means only the legacy compatibility surface and current Profile-backed implementation.
  New docs should prefer **legacy Profile** when the distinction matters.
- **Provider Account** is not introduced as a resource, API object or UI noun. It creates a third
  credential concept and conflicts with account ownership language. If a future internal backing uses
  a provider-account-like aggregate, it still publishes and documents the effective resource as a
  Connection.
- **Credential target** remains an internal per-request resolution value of the provider-access port.
  **Effective credential** remains an invariant, not a user-facing object name.

## Consequences for the next phases

- `OME-1207` should move consumers to the provider-access boundary while preserving legacy Profile
  behavior in the compatibility window. It should not introduce Provider Account naming.
- `OME-1208` remains a backing/authority migration toward Connections. D11 still decides backing
  mechanics, but public/API/UI language follows this decision.
- `OME-1209` retires or renames legacy Profile surfaces using this vocabulary: remove or deprecate
  legacy Profile terms, not replace them with Provider Account terms.
- Docs and code comments added after this decision should reserve `Profile` for compatibility and
  use `Connection` for the final resource.

## Checks

- Documentation-only change; no runtime source changed.
- `git diff --check` clean.

## Owner-verify

- Confirm if product copy wants a friendlier phrase such as "provider connection" in UI text. The
  underlying API/domain noun remains `Connection` unless this decision is reopened.
