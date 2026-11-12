# Provider credit visibility — E5 P3 / OME-893

Approved in the implementation conversation, 2026-11-11. This is the OpenRouter
credit implementation. Product confirmed that platform users execute with limited
OpenRouter keys; their remaining key allowance supplies the hosted allowance.

## Behavior

`sf.credits()` and `Client.credits()` read the selected connection's balance.
Account balance is primary; key allowance is separate. Neither is a run budget.
Unsupported providers and unreadable allowances say unavailable, never zero.
For hosted users, the hosted allowance and key allowance describe the same limited
execution key, not two balances to add together.
An optional management key enables account totals only after matching the provider's
account identity with the inference credential. Credentials stay encrypted in the
Gateway store, separate from inference credentials, and are never returned or logged.
Missing/ambiguous identity fails closed for account totals. No provider mutations or
paid model calls are made by balance verification.

Each amount has a value, status and observation time. Temporary failure can retain a
last successful value for the same credential pair only, clearly marked stale.
Revocation, changed credentials, identity mismatch and logout invalidate old values.
No balance check blocks evaluation. A factual zero-balance notice must not replace or
explain an execution error. On the owner-authorized completion pass, use available
zero readings observed within five minutes on the current execution connection.
Skip stale, unknown or future readings and frozen replays. The SDK checks once per
OpenRouter evaluation with a short best-effort request; warnings-as-errors do not block runs.

The existing connection card shows balances, refresh and optional management-key
setup. It refreshes on open/connection change, manually, and every five minutes while
visible; requests never overlap and failures back off. A browser visibility bridge
uses anywidget in the optional notebook extra. Hidden tabs/off-screen cards pause
refresh; removing or closing a card cleans up its timer and observers.

## Boundaries and wire contract

Gateway owns provider requests and encrypted management credentials, using the same
ProviderAccess resolve/authorize path as inference. Routes are caller-scoped:
GET `/v1/credits/{provider}`, GET `/v1/credits/{provider}/key` (hosted key-only),
PUT/DELETE `/v1/credits/{provider}/management-key`.
The Engine exposes matching routes, authenticates the caller, validates responses,
and uses a key-only Gateway route in hosted mode. That route requires a named caller
and a stored API-key execution connection; it never reads management credentials or
requests the shared account balance. Hosted management-key writes remain disabled.
SDK decodes only safe typed amounts. No cross-app source imports or new database schema.
No global cache keyed only by provider; no environment-key fallback.

OpenRouter `/key` supplies key allowance and account identifiers; `/credits` supplies
account totals with a management key. Match nonempty provider-authored creator id,
organization and workspace context before reading or showing account totals; missing
identity means unavailable, even if both keys otherwise work. Live verification with
the owner's keys is required before release; API identity fields are not assumed to
be present on every account.

Sources checked 2026-11-11:
- https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key
- https://openrouter.ai/docs/api/api-reference/credits/get-remaining-credits

## Acceptance

Correct execution connection; verified account association; independent zero/unknown/
stale amounts; finite Decimal USD; timeout/429/malformed response handling; no secret
in JSON, validation errors or logs; caller isolation; no hosted shared balance;
SDK sync/async parity; desktop/mobile light/dark inspection; read-only owner-key check.

## Owner-key verification

From `apps/aigateway` in this worktree, run:

```sh
.venv/bin/python scripts/verify_openrouter_credits.py
```

The terminal prompts hide both keys. This invokes only the provider's read-only key
and credits endpoints; it does not store credentials or make inference requests.
It prints only amounts, timestamps, and fixed status/reason labels. Do not paste
keys into a notebook cell, shell command, issue, or chat. A result of
`account_unverified` means the required account association was not established;
keep totals unavailable and investigate the provider contract before release.

## Implemented backend refresh policy

The default explicit `sf.credits()` call requests a fresh observation. Callers can
use `refresh=False` to share the Gateway's five-minute observation cache. Repeated
transient failures delay cached retries by 5, 10, 20, then at most 30 minutes; a
manual `refresh=True` bypasses that delay. Successful reads reset the retry delay.
All values retain their provider observation timestamps. Overlapping requests for
the same caller and credentials share a lookup, including during credential-store
outages. A cancelled caller does not cancel another caller's request. App shutdown
cancels and awaits owned requests before closing storage.

The cache and retry policy do not start any background polling. Browser visibility
and the notebook timer will be connected during the final UI pass.

## Review follow-up

Preserve product behavior while repairing the authored replay surface, removing
provider-ID regex matching, injecting credits through an Engine protocol, checking
wire vocabulary across components, rendering the card without optional auto-refresh
when anywidget is absent, and bounding the synchronous notice wait to one second.
An overdue background lookup cannot emit a late notice; at most one sync lookup
may remain in flight per process. Full replay validation is separate from unit gates.
