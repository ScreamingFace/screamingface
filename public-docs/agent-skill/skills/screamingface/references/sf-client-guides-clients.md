# Clients

Source: https://docs.screamingface.ai/sf-client/guides/clients

The default Client behind sf.*, and when to build your own.

There are two ways to call the SDK, and both use the same interface.

Most of the time you'll reach for the **module-level shortcuts**: `sf.evaluate(...)`, `sf.connect(...)`, and the rest. They're the shortest to write, which is why the [Quickstart](sf-client-first-fusion.md) and every notebook use them.

When a script grows into something you ship, construct an explicit **`Client`** instead. It takes a little more code, but it hands you the Client's lifecycle, lets you point at a second engine, and works with your own event loop.

These aren't two different SDKs. Every shortcut runs against a single `Client` the package creates and holds for you. The only real question this page answers is *who owns that Client: you, or the package*.

## What you can do with it

-   Call the SDK with no setup through the process-wide default Client.
-   Point that default at a local or alternate engine, by environment or in code.
-   Construct your own `Client` when you need to own its lifecycle.
-   Run against more than one engine at once, or over `await`.

## The two forms, side by side

The same evaluation, written both ways. The shortcut lets the package hold the Client:

```python
import screamingface as sf

report = sf.evaluate(
    sf.Model("openrouter/anthropic/claude-haiku-4.5"),
    benchmark="medxpert",
    limit=1,
)
sf.close()
```

The explicit form hands the Client to a `with` block that closes it for you:

```python
import screamingface as sf

with sf.Client(engine_url="https://fusion.screamingface.ai") as client:
    report = client.evaluate(
        sf.Model("openrouter/anthropic/claude-haiku-4.5"),
        benchmark="medxpert",
        limit=1,
    )
```

| Concern | `sf.*` shortcuts | `sf.Client` / `sf.AsyncClient` |
| --- | --- | --- |
| Construction | Implicit, on the first call that needs it | You call the constructor |
| How many | One, shared across the process | As many as you build |
| Configuration | `SCREAMINGFACE_ENGINE_URL` / `SCREAMINGFACE_SCOREBOARD_URL`, or `sf.configure(...)` | Constructor keyword arguments |
| Lifecycle | `sf.close()` (or `sf.configure()` swaps it) | `with` / `close()`; async `async with` / `await aclose()` |
| Async | Synchronous only | `AsyncClient` |
| Custom transports | Not available | `http_transport` / `scoreboard_transport` / `run_transport` |
| Login state | Shared by the whole process | Held per Client |

## The default Client

`sf.evaluate()`, `sf.connect()` and `sf.disconnect()` all run against one `Client` the package builds **the first time you call one of them**, and reuses forever after. Nothing is created at `import`, and constructing a Client opens no connection either. The first call that needs the engine is the first one that talks to it:

```python
import screamingface as sf

client = sf.Client(engine_url="https://fusion.screamingface.ai")
client.engine_url, client.closed, client.authenticated
```

```
('https://fusion.screamingface.ai', False, False)
```

Left alone, that default points at the hosted engine, `https://fusion.screamingface.ai`, and the public leaderboard, `https://leaderboard.screamingface.ai`. When `screamingface up` is running and no environment variable is set, the first call connects to that local stack instead and prints the URL it chose. Point it somewhere else in one of two ways. Set the environment before the first call, which suits a local engine you already export elsewhere:

```bash
export SCREAMINGFACE_ENGINE_URL=http://127.0.0.1:9108
export SCREAMINGFACE_SCOREBOARD_URL=http://127.0.0.1:9106
```

Or configure it in code, which also closes and replaces any default already built:

```python
import screamingface as sf

sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)
report = sf.evaluate(
    sf.Model("openrouter/anthropic/claude-haiku-4.5"),
    benchmark="medxpert",
    limit=1,
)
sf.close()
```

`sf.configure(...)` takes only `engine_url` and `scoreboard_url`. A non-default `engine_url` requires its own `scoreboard_url`; without it the call raises `ValueError`, so a local run never publishes to the public leaderboard. `SCREAMINGFACE_ENGINE_URL` requires `SCREAMINGFACE_SCOREBOARD_URL` the same way. A `sf.Client(engine_url=...)` without `scoreboard_url` uses the public leaderboard. For anything more, construct a `Client` yourself. `sf.close()` closes the default and forgets it, so the next shortcut builds a fresh one; it is the tidy end to a script. The fresh default does not keep your `sf.configure(...)` settings: call `sf.configure(...)` again, or set `SCREAMINGFACE_ENGINE_URL` together with `SCREAMINGFACE_SCOREBOARD_URL`, before the next call, or it targets the local stack when one is running and the hosted engine otherwise.

Note: Because the default is one object for the whole process, its login state is shared too: one [login](sf-client-guides-connections.md) covers every later `sf.*` call. That is convenient in a notebook and surprising in a server handling several users, which is the reason to build your own Client below.

## Build your own Client

Constructing a `Client` gives you the object directly. Prefer a `with` block so it closes on the way out, which is the form to reach for in a script or a service:

```python
import screamingface as sf

with sf.Client(engine_url="https://fusion.screamingface.ai") as client:
    report = client.evaluate(
        sf.Model("openrouter/anthropic/claude-haiku-4.5"),
        benchmark="medxpert",
        limit=1,
    )
```

Owning the Client is what lets you hold **more than one at a time**: a hosted engine and a local one, each with its own address, login and connections:

```python
import screamingface as sf

candidate = sf.Model("openrouter/anthropic/claude-haiku-4.5")

with (
    sf.Client(engine_url="https://fusion.screamingface.ai") as hosted,
    sf.Client(
        engine_url="http://127.0.0.1:9108",
        scoreboard_url="http://127.0.0.1:9106",
    ) as local,
):
    hosted_report = hosted.evaluate(candidate, benchmark="medxpert", limit=1)
    local_report = local.evaluate(candidate, benchmark="medxpert", limit=1)
```

The full surface (properties, `login()` / `logout()`, the catalogue accessors) lives on the [Clients API reference](sf-client-api-clients.md). A closed Client raises rather than reconnecting silently, so a `with` block is safer than a bare constructor when the Client is short-lived.

## Async

`AsyncClient` offers the same interface over `await` and returns the same value types. `evaluate()`, `connect()`, `login()` and the rest are awaited; the properties are not, and cleanup is `async with` or `await client.aclose()`:

```python
import asyncio
import screamingface as sf

async def main():
    async with sf.AsyncClient(engine_url="https://fusion.screamingface.ai") as client:
        return await client.evaluate(
            sf.Model("openrouter/anthropic/claude-haiku-4.5"),
            benchmark="medxpert",
            limit=1,
        )

report = asyncio.run(main())   # in a notebook: report = await main()
```

A script starts the event loop with `asyncio.run(main())`. A notebook already runs one, so there `asyncio.run` raises `RuntimeError: asyncio.run() cannot be called from a running event loop`: call `await main()` instead.

Note: There is deliberately **no `await sf.evaluate(...)`**. A single process-wide async Client would bind its connection pool to one event loop. That is a footgun the moment a second loop, a notebook re-run, or a server worker appears. So the async path has no module-level shortcut: you construct an `AsyncClient` and own its lifecycle, every time.

## Custom transports

The constructor accepts `http_transport`, `scoreboard_transport` and `run_transport`: the seam for tests and proxies. A mock transport lets a test drive the Client with no network at all. These are constructor-only: there is no way to reach them through the `sf.*` path, which is another reason a test suite builds its own Client. The constructor also takes `save_results`, which controls whether completed reports are saved to `~/.screamingface/results`; it is on by default. See [Running an evaluation](sf-client-guides-running-an-evaluation.md).

```python
import screamingface as sf

client = sf.Client(
    engine_url="https://fusion.screamingface.ai",
    http_transport=my_transport,          # any httpx.BaseTransport
)
```

## One process, one shared Client

The default is a single instance, built once behind a lock and reused, so `sf.*` calls that happen to overlap share it rather than racing to create two. That sharing is exactly what makes it a poor fit for isolation: separate work that must not share a login, a connection pool, or an engine wants a separate `Client`. Give each thread, each event loop, or each tenant its own, and close it when that work is done.

## When to use each

| Reach for `sf.*` | Build a `Client` |
| --- | --- |
| Notebooks, the REPL, one-off scripts | Libraries and services you ship |
| One engine for the whole process | More than one engine at once |
| Straight-line synchronous code | Async code, or concurrency that needs isolation |
| Configuration by environment | Tests that inject a transport |

## See also

-   [Client AsyncClient](sf-client-api-clients.md)
-   [Connections](sf-client-guides-connections.md): logging in and connecting a provider through whichever Client you chose
-   [Companion notebook: `01_client_tour.ipynb`](https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/01_client_tour.ipynb)
