# Connections

Source: https://docs.screamingface.ai/sf-client/api/connections

The provider-connection values: Connection, the OAuth flows, and the interactive panel.

The values the connections API hands back, from `sf.connections` / `client.connections` and [sf.connect() / sf.disconnect()](sf-client-api-modules.md). For the walkthrough, see the [Connections guide](sf-client-guides-connections.md).

A hosted engine takes no provider keys of its own: `connect(provider, api_key=…)` and `disconnect(provider)` raise `ProviderConnectionError` with the code `connection_method_unsupported`, and `list()` reports the providers the OpenMined team has enabled for your account. A hosted engine can list `api_key` in `auth_methods` for a provider and still refuse `connect(provider, api_key=…)`: observed for `openrouter`. On a local engine `login()` raises `AuthenticationError`.

A local engine advertises seven providers: `anthropic`, `antigravity`, `codex`, `gemini-cli`, `huggingface`, `openai` and `openrouter`. `get(provider)` on a provider the engine does not advertise raises `ProviderConnectionError`.

## Connection

Sanitized provider state as the engine reports it.

| Name | Type | Meaning |
| --- | --- | --- |
| `provider` | `str` | The provider id. |
| `display_name` | `str` | Its human-readable name. |
| `auth_methods` | `tuple[str, ...]` | The methods it offers: `api_key`, `oauth`, or both. |
| `status` | `str` | One of `not_connected`, `pending`, `connected`, `needs_reauth`, `error`. |
| `auth_method` | `str | None` | The method currently in use, when connected. |
| `account_label` | `str | None` | The connected account, where the provider reports one. |

## OAuthFlow

The pending browser authorization returned by `connect(provider, method="oauth")`.

| Name | Type | Meaning |
| --- | --- | --- |
| `provider` | `str` | Which provider is being authorized. |
| `authorize_url` | `str` | Open this to authorize. |
| `expires_in` | `int` | Seconds the flow stays valid. |
| `status` | `str` | `pending` until it resolves. |
| `wait(*, poll_interval=0.5, timeout=None)` | `Connection` | Block until the browser flow completes, then return the `Connection`. |
| `cancel()` | `Connection` | Abandon the flow. |
| `expired` | `bool` | Whether the authorization window has passed. |

## AsyncOAuthFlow

The async form of `OAuthFlow`: `await flow.wait(...)` and `await flow.cancel(...)`; the same fields and the same `expired` check.

## ConnectionPanel

An engine-scoped connection view with optional notebook controls, returned by `connect()` with no arguments.

| Name | Type | Meaning |
| --- | --- | --- |
| `engine` | `str` | The engine origin the panel is bound to. |
| `connections` | `tuple[Connection, ...]` | Every provider the engine advertises, connected or not. |
| `authenticated` | `bool` | Whether a hosted-engine login is in effect. |
| `authenticating` | `bool` | Whether a login is in progress. |
| `refresh()` | `tuple[Connection, ...]` | Re-read connections from the engine and return them. |
| `widget()` |  | The notebook widget for interactive connect/disconnect. |

```python
panel = sf.connect()
panel.connections
```
