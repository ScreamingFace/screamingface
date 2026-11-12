# Provider credit implementation

Spec: `docs/spec/2026-11-11-provider-credit.md`. Implementation authorized by owner.

1. Gateway: add safe credit values/service port, OpenRouter HTTP adapter, credential
   association verification, encrypted management-key slot, authenticated routes.
   Tests first: independent failures, mismatched/missing identity, Decimal parsing,
   no secret forwarding to arbitrary origins, no provider write or paid request.
2. Engine: caller-scoped credit adapter and REST routes, sanitized schemas, strict
   upstream validation, hosted key-only reads with caller identity, and no hosted wallet
   or management-key access. Test with mock transport.
3. SDK: typed credit API, sync/async requests, management-key setup/removal, same-client
   stale observations and invalidation; connection-card balance rendering and refresh.
   Owner authorized completion: use anywidget in the optional notebook extra for browser
   visibility and five-minute refresh. Run notices use available readings at most five
   minutes old from the actual execution connection; skip failures and frozen replays.
4. Run affected stack gates, inspect desktop/mobile in light/dark, provide local preview.
5. Owner verifies real keys through secure UI. No credentials in chat or test fixtures.

The existing parent is E5 / OME-1294; tracking task OME-893 already assigned to Filip.
Prepare component-specific delivery units at PR-open per current repository process.
Product confirmed limited OpenRouter execution keys for hosted users. Hosted allowance
uses the key limit directly; no ledger dependency or separate hosted timing decision remains.

## Review follow-up

Preserve product behavior while repairing the authored replay surface, removing
provider-ID regex matching, injecting credits through an Engine protocol, checking
wire vocabulary across components, rendering the card without optional auto-refresh
when anywidget is absent, and bounding the synchronous notice wait to one second.
An overdue background lookup cannot emit a late notice; at most one sync lookup
may remain in flight per process. Full replay validation is separate from unit gates.
