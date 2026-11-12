# Connections

Source: https://docs.screamingface.ai/sf-client/guides/connections

Connect a model provider through the engine, and log in to a hosted one.

A **connection** is a provider credential [the engine](learn-engine.md) holds on your behalf. The Client never talks to OpenRouter, Anthropic or any other provider directly. It sends your key to the engine once, the engine passes it to AI Gateway to validate and store encrypted, and every later model call is dispatched there.

Two steps get you there: configure the engine, then connect a provider. Without a connection the engine can still list benchmarks and models, but any evaluation fails: there is no credential to call a model with.

## What you can do with it

-   Login to the engine, or point the Client at your own engine instead.
-   Connect a provider interactively from a notebook, or with an explicit key from a script.
-   Read which providers this engine advertises, and the state of each.
-   Remove a credential.

## Main APIs

| API | What it does |
| --- | --- |
| `sf.connect()` | Called with no arguments, returns a `ConnectionPanel` widget listing every provider the engine advertises. |
| `sf.connect(provider, api_key=…)` | Connects one provider directly and returns the resulting `Connection` instead of a widget. |
| `sf.connections.list()` | Returns a tuple of every provider this engine advertises, one `Connection` each. |
| `sf.connections.get(provider)` | Fetches a single provider by name, returning its current state as a `Connection`. |
| `sf.disconnect(provider)` | Removes a stored credential. On a local engine repeated calls are harmless and return the provider back in its `not_connected` state. |
| `sf.Connection` | The sanitised provider-state value, carrying the public provider name, its supported methods, and its state. |
| `sf.ConnectionPanel` | The live widget that `sf.connect()` returns when called with no arguments. |
| `sf.Client.login()` · `sf.Client.logout()` | Log in to and out of a hosted engine behind Cloudflare Access; `login()` prints a URL (a script also opens it in your browser) and holds the token in process memory only. |

## How to

### 1 · Configure engine

Point the Client at an engine. There are two ways, depending on where it runs.

**Hosted engine**

A hosted engine sits behind **Cloudflare Access**. There is no token to paste: `login()` prints a URL (a script also opens it in your browser; a notebook only prints it), then polls an encrypted transfer service and decrypts the returned token locally. The token lives only in process memory and is sent as `Cf-Access-Token`. `logout()` forgets it.

```python
import screamingface as sf

client = sf.Client(engine_url="https://fusion.screamingface.ai")
client.login()          # a script opens Cloudflare Access in your browser; a notebook prints a link to open
client.authenticated    # True once the token arrives
```

In a notebook you rarely call this directly: the panel below handles it. A protected engine shows a login row first and loads provider rows only once login succeeds.

Logging in is not enough to run an evaluation. The OpenMined team grants hosted access: reach out to them. Until your account has access, every provider shows as unavailable and an evaluation is refused with `provider_not_connected`. On a local engine you use the providers the engine advertises, with the keys you hold yourself. On a hosted engine you use only the compute that has been subsidised for you, through a grant call or a direct allocation. A hosted engine takes no keys of its own, so `connect(provider, api_key=…)` and `disconnect(provider)` raise `ProviderConnectionError` with the code `connection_method_unsupported`. The rest of this guide, from step 2, describes a local engine.

**Local engine**

If you run the engine yourself, point the Client at it and skip the login step entirely: a local engine advertises no Cloudflare Access, so the panel shows provider rows immediately. Calling `login()` on a local engine raises `AuthenticationError`. A non-default `engine_url` requires `scoreboard_url` in `sf.configure()`; without it the call raises `ValueError`. `SCREAMINGFACE_ENGINE_URL` requires `SCREAMINGFACE_SCOREBOARD_URL` the same way. When `screamingface up` is running and neither is set, the module-level functions connect to that stack.

```python
sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)
```

### 2 · Connect from a notebook

Called with no arguments, `sf.connect()` returns a `ConnectionPanel`: a live widget listing every provider the engine advertises, with a field for each one's supported auth method. The [Reproduce DRACO](sf-client-reproduce-draco.md) steps through the whole flow state by state.

```python
sf.connect()
```

### Provider connections

Engine · http://127.0.0.1:9108

-   Anthropic
    
    NOT CONNECTED
-   Antigravity
    
    NOT CONNECTED
-   Codex
    
    NOT CONNECTED
-   Gemini CLI
    
    NOT CONNECTED
-   Hugging Face
    
    NOT CONNECTED
-   OpenAI
    
    NOT CONNECTED
-   OpenRouter
    
    CONNECTED

### 3 · Connect from a script

With a provider and a key, the same function connects directly and returns the resulting `Connection` instead of a widget.

```python
sf.connect("openrouter", api_key="sk-or-v1-…")
```

The two arguments go together. `sf.connect("openrouter")` without a key raises `ValueError`, and passing `api_key=` without a provider raises `TypeError`: there is no partial form that silently does nothing.

### 4 · Read the current state

```python
{c.provider: c.status for c in sf.connections.list()}
```

```
{'anthropic': 'not_connected',
 'antigravity': 'not_connected',
 'codex': 'not_connected',
 'gemini-cli': 'not_connected',
 'huggingface': 'not_connected',
 'openai': 'not_connected',
 'openrouter': 'connected'}
```

`list()` returns a **tuple**, not a list, with one `Connection` per provider: seven on a local engine. The line above reads just the status of each. Fetch a single one by name when you want its full state:

```python
sf.connections.get("openrouter")
```

```
Connection(provider='openrouter', display_name='OpenRouter',
           auth_methods=('api_key',), status='connected',
           auth_method='api_key', account_label=None)
```

### 5 · Disconnect

```python
sf.disconnect("openrouter")
```

On a local engine repeated calls are harmless. The returned `Connection` shows the provider back in its `not_connected` state.

## What a connection carries

Every `Connection` is sanitised: the public provider name, its supported methods, and its state. AI Gateway account IDs, credential locators and upstream error bodies never cross this boundary.

-   `status`: one of `not_connected`, `pending`, `connected`, `needs_reauth`, `error`
-   `auth_methods`: what the provider supports. A local engine advertises `('api_key',)` for OpenRouter, OpenAI and Hugging Face, `('api_key', 'oauth')` for Anthropic and Gemini CLI, and `('oauth',)` for Codex and Antigravity
-   `auth_method`: which one is in use, or `None`
-   `account_label`: an optional display label

## When it fails

Credential problems raise `ProviderConnectionError`, which carries a stable `code` and a `hint`. One rule is worth knowing before you deploy: an API key sent to a non-loopback `http://` engine is **refused outright** with `secure_transport_required`. A remote engine must be HTTPS.

## Links

-   [Companion notebook: `00_quickstart.ipynb`](https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/00_quickstart.ipynb)
