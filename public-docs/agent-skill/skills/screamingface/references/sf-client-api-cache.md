# Shared cache

Source: https://docs.screamingface.ai/sf-client/api/cache

Use the shared cache from the hosted engine when running locally.

Whether you run on a hosted or a local engine, your cache accumulates, and you can reuse it on any run to lower that run's cost. On the hosted engine the cache is shared: you benefit from everyone else's runs and they benefit from yours, so the whole community pushes fusion research further at lower cost. Calls the cache cannot key are not shared. A call that is not in the cache is billed to the provider account that runs it. If you run your own local engine and want the shared cache, download it with the `sf.cache` module.

The gateway of a local engine stores each model response, keyed by the exact request, and serves a repeat of that request from the store. `sf.cache` loads the shareable rows of the hosted community cache into that store, so a local run answers from them, for free, the calls the community has already made. [Caching and compute](learn-caching.md) explains how the cache works.

## The local request cache

-   **Default:** `screamingface up` sets `AIGW_REQUEST_CACHE_ENABLED=true` unless the variable is already exported, so the local gateway caches by default. An exported `false` turns it off.
-   **Expiry:** Entries do not expire.
-   **Opt out per evaluation:**`use_cache=False` on `sf.evaluate`, `Client.evaluate` and `AsyncClient.evaluate` starts the run with `Cache-Control: no-cache`. The engine makes every model call fresh, and the report shows those calls as cache `bypass` with the reason `opted_out`. The default is `use_cache=True`.

```python
model = sf.Model("openrouter/google/gemini-3.5-flash-lite")
report = sf.evaluate(model, benchmark="medxpert", limit=2, use_cache=False)
```

## sf.cache.pull\_from\_remote

| Signature | What it does |
| --- | --- |
| `sf.cache.pull_from_remote(models=None, *, url=None, progress=None)` | Copies the hosted community cache into the local gateway database and returns a `PullResult`. |

-   **`models`:** A sequence of model names, exactly as the hosted cache names them, for example `"openrouter/anthropic/claude-opus-4.8"`. A run can hit only the rows of the models its candidates and judge use, so a filtered pull loses no hits. `None` pulls every model. A single string raises `TypeError`, and so does an empty or non-string name.
-   **`url`:** The hosted engine to pull from. `None` is the production engine. It never follows the engine your runs use: with `screamingface up` running, that is the local engine, where the rows go, not where they come from.
-   **`progress`:** `None` shows progress in a notebook or an interactive terminal. `True` and `False` force it on or off.

```python
import screamingface as sf

result = sf.cache.pull_from_remote()                      # every model
result = sf.cache.pull_from_remote(["openrouter/anthropic/claude-opus-4.8"])  # one model
```

One call for `openrouter/anthropic/claude-opus-4.8` returned the result below. The counts depend on what the community cache holds when you run it.

```
PullResult(rows_read=4631, rows_added=4631, pages=1, resumed=False, complete=True, rows_skipped=0)
```

Note: The first page opens the engine's sign-in in a browser, unless this process is already signed in to that engine, by an earlier pull or by the default client. One sign-in serves every later pull in the process. The production engine needs access granted by the OpenMined team, so a pull needs the same hosted access as `Client.login()`.

The pull also needs:

-   `screamingface[runtime]` installed, which provides the local gateway.
-   A local gateway database. Run `screamingface up` once to create it.
-   `SCREAMINGFACE_DATA_DIR` set to the data directory of a stack started with `screamingface up --data-dir DIR`. The default is `~/.screamingface`, the stack `sf.connect()` finds.

## PullResult

A frozen dataclass that says what one call did. `pull_from_remote` returns it, and `CachePullError.result` carries it when a pull stops.

| Field | Type | Meaning |
| --- | --- | --- |
| `rows_read` | `int` | The rows of completed pages. |
| `rows_added` | `int` | The rows that were new to the local cache. A row the cache already held is kept and not counted. |
| `pages` | `int` | The pages the call completed. |
| `resumed` | `bool` | `True` when the call continued a pull this process had started. |
| `complete` | `bool` | `True` when the call reached the last page. |
| `rows_skipped` | `int` | The rows of completed pages that the local gateway could not serve, which were not loaded. The default is `0`. |

## CachePullError

`CachePullError` subclasses `ScreamingFaceError` and has the default code `community_cache_pull_failed`. It is raised when a pull stops before its last page. Its `result` attribute is a `PullResult` that says how far the pull got.

-   **Retries:** A dropped connection, a rate limit, an edge error or a cut page is retried 4 times, with 2, 4 and 8 seconds between attempts. A `Retry-After` from the engine is honoured up to 60 seconds.
-   **Loaded rows stay loaded:** Every row is an independent cache entry. Calling `pull_from_remote` again in the same process, with the same `url` and `models`, continues from the last loaded page.
-   **A new process starts over:** The cursor lives in memory. A pull whose process ended starts again, which costs only time, because rows already loaded are kept.
-   **Interrupts:** Ctrl-C re-raises the `KeyboardInterrupt` with the same counts as its `result` attribute, and the next call continues the same way.

```python
try:
    result = sf.cache.pull_from_remote()
except sf.cache.CachePullError as exc:
    print(exc.code, exc.result)             # how far the pull got
    result = sf.cache.pull_from_remote()    # same process: continues from the last page
```

## screamingface cache pull

The shell command runs the same pull and always shows progress.

```bash
screamingface cache pull
screamingface cache pull --model openrouter/anthropic/claude-opus-4.8
screamingface cache pull --url https://fusion.screamingface.ai --data-dir ~/.screamingface
```

| Option | Meaning |
| --- | --- |
| `--model MODEL` | Only this model's rows, as the hosted cache names it. Repeat it for more models. |
| `--url URL` | The hosted engine to pull from. The default is the production engine. |
| `--data-dir DIR` | The data directory of the stack to load the rows into. |

The exit code is `0` when the pull finished, `1` when it stopped or was refused (the reason goes to stderr), and `130` when it was interrupted. An interrupted command starts over on the next run.
