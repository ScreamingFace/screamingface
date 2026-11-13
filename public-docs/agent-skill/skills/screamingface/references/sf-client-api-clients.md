# Clients

Source: https://docs.screamingface.ai/sf-client/api/clients

Client and AsyncClient: how you reach an engine.

A `Client` is the connection to one engine, and the object that every other page in this reference depends on: recipes are passed to it, and benchmarks and reports come back from it. This page covers `Client` itself and `AsyncClient` for the same interface over `await`. The connection values it returns (`Connection`, the OAuth flows, and `ConnectionPanel`) are documented under [Connections](sf-client-api-connections.md).

## Client

```python
sf.Client(
    *,
    engine_url: str = DEFAULT_ENGINE_URL,
    scoreboard_url: str = DEFAULT_SCOREBOARD_URL,
    http_transport: httpx.BaseTransport | None = None,
    scoreboard_transport: httpx.BaseTransport | None = None,
    run_transport: SyncRunTransport | None = None,
    save_results: bool = True,
)
```

Creating a `Client` opens no connection and makes no request. The first call that needs the engine is the first one that talks to it.

```python
import screamingface as sf

client = sf.Client(engine_url="https://fusion.screamingface.ai")
client.engine_url, client.closed, client.authenticated
```

```
('https://fusion.screamingface.ai', False, False)
```

Note:`DEFAULT_ENGINE_URL` is the hosted engine, `https://fusion.screamingface.ai`, so a `Client()` with no arguments talks to one we operate. To use a local engine, pass its address and its scoreboard explicitly, or set `SCREAMINGFACE_ENGINE_URL` together with `SCREAMINGFACE_SCOREBOARD_URL` and use the module-level functions. `DEFAULT_SCOREBOARD_URL` is the public ScreamingFace Leaderboard, `https://leaderboard.screamingface.ai`. Both constants live in `screamingface.client`.

### Constructor arguments

| Name | Meaning |
| --- | --- |
| `engine_url` · `scoreboard_url` | The engine and the leaderboard this Client talks to. |
| `http_transport` · `scoreboard_transport` · `run_transport` | Transports for the engine, the leaderboard and the run stream. They are the seam for tests and proxies, and constructor-only. |
| `save_results` | `True` by default: every completed report is saved to `~/.screamingface/results`, and [sf.reports](sf-client-api-reports.md) reopens it. Pass `False` to keep reports in memory only. |

### Properties

| Name | Type | Meaning |
| --- | --- | --- |
| `engine_url` | `str` | The engine origin this Client was built for. Fixed for the Client's life. |
| `closed` | `bool` | Whether `close()` has run. |
| `authenticated` | `bool` | Whether this process currently holds hosted caller credentials. |
| `authenticating` | `bool` | Whether a login is in flight. |
| `scoreboard_url` | `str` | Where [leaderboard](sf-client-guides-leaderboards.md) submissions go. Separate from the engine, and separately configurable. |
| `models` | catalogue | `models.list()` returns the [ModelInfo](sf-client-api-models.md) routes this engine can reach. |
| `benchmarks` | catalogue | `benchmarks.list()` and `benchmarks.get(id)` return [Benchmark](sf-client-api-benchmarks.md) identity cards. |
| `connections` | catalogue | `connections.list()` and `connections.get(provider)`. |

### evaluate()

```python
Client.evaluate(
    candidates: Recipe | Sequence[Recipe] | str,
    *,
    benchmark: str | None = None,
    limit: int | None = None,
    cases: Sequence[int] | None = None,
    on_event: Callable[[Event], None] | None = None,
    progress: bool | None = None,
    answer_seed: int | None = None,
    capture: bool | None = None,
    use_cache: bool = True,
) -> Report
```

`evaluate()` runs one or more candidates against a benchmark and returns a [Report](sf-client-api-reports.md). This is the call that costs money.

| Name | Type | Meaning |
| --- | --- | --- |
| `candidates` | `Recipe` or sequence | One [recipe](sf-client-api-recipes.md) or several. Several candidates run independently and share one report. |
| `benchmark` | `str` | The benchmark id: `medxpert` on a local engine, or any id from `sf.benchmarks.list()` on the hosted engine, such as `ifeval`. A protocol variant is its own id and pins a different revision, so it changes what the result is comparable to. Required for recipe candidates; omit it when evaluating a complete url4 string or replaying a pinned cache. |
| `limit` | `int | None` | Run only this many cases. `None` runs the whole benchmark. Use a small limit while you are still iterating. |
| `cases` | `Sequence[int] | None` | Run a fixed list of Case ids instead of the first `limit`. A Case id is the position of the Case in the benchmark, from 1 to the case count. Pass `cases` or `limit`, not both. The list must hold 1 to 1,000 distinct whole numbers, and a replay takes no `cases`. See [Running an evaluation](sf-client-guides-running-an-evaluation.md). |
| `on_event` | callable | Called with each lifecycle event as the run proceeds. |
| `progress` | `bool | None` | Force the progress display on or off instead of letting it decide. |
| `answer_seed` | `int | None` | An integer that the engine sends to each model call as its `seed`, unless the call sets one. `None` (the default) runs unseeded. Not a `bool`. The result keeps it. |
| `use_cache` | `bool` | `True` by default: a model call may be answered from the request cache. `False` makes every call of this evaluation fresh; the report marks them cache `bypass` with the reason `opted_out`. Anything other than a `bool` raises `TypeError`. A replay ignores it. See [Caching](learn-caching.md). |
| `capture` | `bool | None` | Defaults to `None`, which means off. `True` turns capture on for a fresh evaluation. A replay never captures, and `capture=True` with a replay raises `TypeError`. When capture is on, the engine makes a pinned cache of each run, so the score can be replayed later. Best effort. Read `capture_status` on each [CandidateResult](sf-client-api-candidate-result.md). See [Reproducing a submission](learn-caching.md). |

### Replay a captured run with evaluate()

```python
Client.evaluate(
    *,
    pinned_cache: str | None = None,
    score_id: UUID | str | None = None,
    url4: str | None = None,
    answer_seed: int | None = None,
    limit: int | None = None,
    record_reproduction: bool = True,
    on_event: Callable[[Event], None] | None = None,
    progress: bool | None = None,
    capture: Literal[False] | None = None,
) -> Report
# Supply pinned_cache or score_id (or both, if they agree).
```

Call `client.evaluate(pinned_cache="…")` for a public capture or `client.evaluate(score_id="…")` for a public score or a private score you submitted. Pass the score's id, not the `LeaderboardScore` object. A pinned cache id must be a canonical lowercase UUID string. A replay takes no positional candidate or `benchmark`. It returns a `Report`; the single `CandidateResult.reproduction` holds a `Reproduction` object or `None`, and the verdict string is `.outcome`. The [Leaderboards reference](sf-client-api-leaderboards.md) lists the outcomes and reasons.

The board supplies the original recipe and seed. A passed `url4` must match the published parsed recipe, and a passed `answer_seed` must equal the stored one. `None` uses the stored seed; `0` is a seed. A seedless capture replays without one. A capture with no public score needs the original `url4` and seed if it had one, and is not judged or recorded.

`limit=n` replays the first n cases of a published run, with no verdict or record. It must be a positive integer smaller than the published case count. The Client refuses it with `PlanningError` (`partial_replay_unavailable`) if the Engine cannot rebuild the published recipe and a compatible subset. Omit `limit` for a full replay.

Only an exact full replay records a reproduction, unless `record_reproduction=False`. A public score needs leaderboard authentication only for recording; a private score may need it before replay. Engine authentication is separate. Replay never captures, and explicit `capture=True` is an error.

A partial or unknown published capture raises [`ReproductionError`](sf-client-api-errors.md) with code `not_reproducible`; an Engine that does not acknowledge replay raises it with `replay_unsupported`. Its `.reproduction` carries the verdict. Bad argument types or conflicting values raise `TypeError` or `ValueError`; a failed score read raises `LeaderboardError`.

### connect() and disconnect()

`connect(provider, api_key=...)` stores a provider credential on the engine and returns the resulting `Connection`. `connect()` with no arguments returns a `ConnectionPanel` instead. `disconnect(provider)` removes the credential and is safe to call repeatedly on a local engine. A hosted engine raises `ProviderConnectionError`. `connect(provider, method="oauth")` returns an `OAuthFlow` for providers that offer OAuth.

Passing a key requires a secure origin: an `https` engine, or a local one over `http`. Supplying `api_key` without a provider raises `TypeError`; a provider without `api_key` raises `ValueError`. A provider the engine does not advertise raises `ProviderConnectionError`.

### Lifecycle

`close()` releases the Client's transports and is idempotent. Using a closed Client raises:

```python
client.close()
client.connections.list()
```

```
RuntimeError: ScreamingFace Client is closed
```

A `with` block closes it automatically, which is the form to prefer in a script:

```python
with sf.Client() as client:
    report = client.evaluate(
        sf.Model("openrouter/anthropic/claude-haiku-4.5"),
        benchmark="ifeval",
        limit=1,
    )
```

`login(timeout=300.0)` and `logout()` apply to hosted engines that sit behind browser-based access. A local engine needs neither.

## AsyncClient

An `AsyncClient` offers the same interface over `await` and returns the same value types. It suits evaluations that run alongside other asynchronous work.

```python
import asyncio
import screamingface as sf

async def main():
    async with sf.AsyncClient(engine_url="http://127.0.0.1:9108") as client:
        models = await client.models.list()
        return len(models), client.engine_url

asyncio.run(main())   # in a notebook: await main()
```

```
(110, 'http://127.0.0.1:9108')
```

Three differences are worth knowing:

| Client | AsyncClient |
| --- | --- |
| `close()` | `await aclose()` |
| `with` | `async with` |
| `connect()` may open a panel | `connect(provider, ...)` always requires a provider |

`evaluate()`, `connect()`, `disconnect()`, `login()` and `logout()` are all awaited. The properties (`engine_url`, `closed`, `authenticated`) are not.
