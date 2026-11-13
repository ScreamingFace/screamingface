# Modules

Source: https://docs.screamingface.ai/sf-client/api/modules

The modules and functions you can call on sf directly.

The names `benchmarks`, `models`, `connections`, `leaderboards`, `evaluate`, `connect` and `disconnect` work two ways. On a [Client](sf-client-api-clients.md) you build yourself, they are its attributes and methods: `client.benchmarks`, `client.evaluate(...)`. On the `sf` module, the same names act on a default Client the library creates and manages for you, so a script or notebook can call `sf.evaluate(...)` without constructing one. `sf.events`, `sf.reports`, `sf.cache` and `sf.analytics` exist only on the module.

```python
import screamingface as sf

sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)
[(b.id, b.case_count) for b in sf.benchmarks.list()]
```

```
[('medxpert', 2450)]
```

Note: Both forms return the same values. Mixing them is fine, but a Client you construct yourself is separate from the shared one, so `sf.configure()` does not affect it.

## sf.benchmarks

| Function | Returns |
| --- | --- |
| `list()` | Every [Benchmark](sf-client-api-benchmarks.md) the engine offers. |
| `get(benchmark_id)` | One `Benchmark` by its id. |

## sf.models

| Function | Returns |
| --- | --- |
| `list()` | Every [ModelInfo](sf-client-api-models.md) route the engine can reach. |
| `get(model_id)` | The full `ModelDetails` for one route. It does not need the provider connected: an unconnected route fails at evaluation, not here. |

## sf.connections

This module also re-exports the connection types themselves: `Connection`, `ConnectionStatus`, `OAuthFlow` and `AsyncOAuthFlow`.

| Function | Returns |
| --- | --- |
| `list()` | A [Connection](sf-client-api-clients.md) for every provider the engine advertises, connected or not. |
| `get(provider)` | One provider's current state. |

## sf.leaderboards

This module talks to the leaderboard rather than the engine. See [Leaderboards](sf-client-api-leaderboards.md) for the values it returns.

| Function | Returns |
| --- | --- |
| `list()` | A `LeaderboardInfo` for every board. |
| `get(benchmark_id, *, top=50)` | One `Leaderboard`, its entries capped by `top`. |
| `get_score(score_id)` | One `LeaderboardScore` by its identifier. |
| `submit(candidate_result, *, authors=None, paper_url=None, authors_metadata=None, paper_metadata=None)` | Publishes one [CandidateResult](sf-client-api-candidate-result.md) to the public board and returns the stored `LeaderboardScore`. |
| `edit(score_id, *, authors=..., paper_url=..., authors_metadata=..., paper_metadata=...)` | The updated `LeaderboardScore`, for a score you submitted. |
| `metadata_events(score_id)` | The edit log of a score you submitted, as `ScoreMetadataEvent` values. |

## sf.events

`sf.events` exposes no functions. It holds the event types a run reports through `on_event`, covered in [Events](sf-client-api-events.md).

## sf.reports

Reopens reports that evaluations saved to disk. It is documented on the [Reports](sf-client-api-reports.md) page.

| Function | Returns |
| --- | --- |
| `list(*, directory=None)` | A `SavedReportInfo` for every saved report. |
| `get(report_id, *, directory=None, destination=None)` | The saved `Report`. `get_async` is the awaitable form. |
| `delete(report_id, *, directory=None)` | `None`. Removes the saved report from disk. |

## sf.cache

Copies the hosted community cache into the local gateway, so a local run answers from it the model calls the community already made. It exposes `pull_from_remote()`, `PullResult` and `CachePullError`. The command line form is `screamingface cache pull`. See [Cache](sf-client-api-cache.md).

## sf.analytics

Reads and sets the analytics choice. Analytics are on by default. It exposes `status()`, `enable()`, `disable()` and `reset_identifier()`. The command line form is `screamingface analytics`, and `DO_NOT_TRACK` turns analytics off. See [Analytics](sf-client-api-analytics.md).

## Top-level functions

These functions act on the shared Client. They exist so a script or notebook never has to build one explicitly.

### evaluate()

```python
sf.evaluate(
    candidates: Recipe | Sequence[Recipe] | str | None = None,
    *,
    benchmark: str | None = None,
    limit: int | None = None,
    on_event: Callable[[Event], None] | None = None,
    progress: bool | None = None,
    answer_seed: int | None = None,
    capture: bool | None = None,
    pinned_cache: str | None = None,
    score_id: UUID | str | None = None,
    url4: str | None = None,
    record_reproduction: bool = True,
    use_cache: bool = True,
) -> Report
```

Runs a fresh evaluation, which may spend money, or replays captured answers. Identical to `Client.evaluate()`, including evaluating a url4 string. Its parameters are documented on the [Clients](sf-client-api-clients.md) page. That includes `answer_seed`, `capture` and `use_cache`.

```python
# Replace either placeholder with an id from the leaderboard.
replay = sf.evaluate(pinned_cache="<pinned-cache-id>")
# Or replay by score id, including a private score you submitted:
replay = sf.evaluate(score_id="<score-id>")

reproduction = replay.candidates.only.reproduction
if reproduction is not None:
    print(reproduction.outcome)
```

The keyword forms `sf.evaluate(pinned_cache=…)` and `sf.evaluate(score_id=…)` take no positional candidate or `benchmark`. They accept `url4`, `answer_seed`, `limit` and `record_reproduction` under the same rules as [Client.evaluate()](sf-client-api-clients.md). A full published replay has a verdict on its result; partial replays and unsubmitted captures have `reproduction=None`. See the [Leaderboards guide](sf-client-guides-leaderboards.md).

### configure()

```python
sf.configure(
    *,
    engine_url: str = "https://fusion.screamingface.ai",
    scoreboard_url: str | None = None,
) -> Client
```

Replaces the shared Client and returns the new one. Call it once, before anything else, to point the module-level functions at a different engine. A non-default `engine_url` requires its own `scoreboard_url`; without it `configure()` raises `ValueError`, so a local run's `submit` cannot publish to the public leaderboard. Setting `SCREAMINGFACE_ENGINE_URL` and `SCREAMINGFACE_SCOREBOARD_URL` in the environment does the same thing without a call.

### connect() and disconnect()

| Call | Returns |
| --- | --- |
| `connect()` | A `ConnectionPanel` listing every provider. |
| `connect(provider, api_key=...)` | The resulting `Connection`. |
| `connect(provider, method="oauth")` | An `OAuthFlow` carrying a URL to open. |
| `disconnect(provider)` | The provider's `Connection`, now disconnected. |

### classify()

Sends one text to a text classifier you configured on your own endpoint and returns a `Classification`. Identical to `Client.classify()`. See [Classify](sf-client-api-classify.md).

### fetch\_media()

Fetches one picture or file of a case from the engine and returns a `FetchedMedia`. Identical to `Client.fetch_media()`. See [Case media](sf-client-api-candidate-result.md#case-media).

### close()

Releases the shared Client and the sign-in sessions of `sf.cache.pull_from_remote()`. A later module-level call simply builds a new one, so this is about releasing resources rather than shutting anything down permanently.
