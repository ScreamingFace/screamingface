# Running an evaluation

Source: https://docs.screamingface.ai/sf-client/guides/running-an-evaluation

Evaluate one or many candidates against a benchmark and get one Report.

`sf.evaluate()` is the one call that costs money. You give it candidates and a benchmark id. It compiles each candidate against that benchmark's protocol, runs them concurrently on [the engine](learn-engine.md), and returns a single `Report`.

Everything expensive happens inside this call, but validation happens first and in full. An unknown benchmark, an unreachable route, or a malformed candidate all fail **before the first paid request**.

[Diagram: Candidates and a benchmark go into the engine, which runs every candidate on every case and grades them behind the trust boundary, returning one report.]

One call runs every candidate on the same cases, grades them behind the trust boundary, and returns one report.

## What you can do

-   Evaluate one candidate, or run several at once.
-   Cap the number of cases with `limit`, or run a fixed list with `cases`.
-   Skip the request cache for one run with `use_cache=False`.
-   Reopen a saved report from disk.
-   Watch the run live, or turn off the progress display.
-   Use an explicit Client, sync or with `await`.

To replay captured answers, call `sf.evaluate(pinned_cache="…")` or `sf.evaluate(score_id="…")` with no positional candidate and no `benchmark`. The board supplies the recipe and seed. The returned report's single result has a `reproduction` object with an `outcome` of `exact` or `failed`. A partial replay with `limit=n` has no verdict. See the [Leaderboards guide](sf-client-guides-leaderboards.md) for replay checks, private scores and `record_reproduction=False`.

## Main APIs

| API | What it does |
| --- | --- |
| `sf.evaluate(candidates, *, benchmark, limit=None, cases=None, on_event=None, progress=None, answer_seed=None, capture=None, pinned_cache=None, score_id=None, url4=None, record_reproduction=True, use_cache=True)` | Runs one or more candidates against a benchmark's protocol concurrently, returning a single `sf.Report`. Validates everything before the first paid request. Capture is off by default: with `capture=True` the run stores a pinned cache, so a score can be [replayed](learn-caching.md) later. A replay never captures. With `use_cache=False` every model call is made fresh instead of being answered from the request cache. |
| `sf.Client.evaluate(...)` · `await sf.AsyncClient.evaluate(...)` | Same call on an explicit Client you manage yourself, sync or with `await`. Only way to talk to two engines from one process. |
| `sf.configure(engine_url=…, scoreboard_url=…)` | Repoints the shared Client so every later `sf.evaluate()` call uses that engine and its leaderboard. A non-default engine without its `scoreboard_url` raises `ValueError`. |
| `sf.close()` | Releases the shared Client and forgets the `sf.configure(...)` settings, so call `sf.configure(...)` again before the next call. |

## How to

### 1 · Evaluate one candidate

The benchmark id is **required**, with no default and no implicit choice. `limit` caps the case count and is your main cost control.

```python
import screamingface as sf

haiku = sf.Model("openrouter/anthropic/claude-haiku-4.5")
report = sf.evaluate(haiku, benchmark="medxpert", limit=3)
report
```

```
Report(benchmark='medxpert', candidates=['claude-haiku-4.5'], ok=True)
```

The repr is a summary: which benchmark, which candidates, whether anything failed. `ok` is `True` only when no candidate and no member had a failure.

### 2 · Read the score

Scores live on candidates rather than on the report, since a report can hold several. With one candidate, `.only` gets you right to it.

```python
c = report.candidates.only
c.name, c.score, report.case_count, report.benchmark
```

```
('claude-haiku-4.5', 0.0, 3, BenchmarkInfo(id='medxpert', revision='1e5a3b8a461a52f7', case_count=2450, inverted_grade=False))
```

Notice the two case counts: `report.case_count` is how many cases *ran*; `report.benchmark.case_count` is how many the benchmark has. Running 3 of 2,450 is a smoke test, and the report keeps both numbers visible so that stays obvious later.

`score` is always higher-is-better, and can be `None` if a candidate failed. Benchmark-specific diagnostics live under `metrics`:

```python
dict(c.metrics)
```

```
{'correct': 0, 'scored_cases': 3, 'answered': 3, 'answered_rate': 1.0}
```

Read `coverage` beside the score. It is the fraction of the selected cases the score was computed from, and anything below `1.0` means the engine graded only part of the run and the score describes that part. A candidate can also finish with both a score and entries in `failures`, which is a completed run carrying warnings worth reading rather than a broken one.

### 3 · Evaluate several at once

Pass a list. Every candidate runs against the same pinned exam in the same call. That's what makes the comparison fair. It's the only way to compare, because a report has no "baseline" or "gain" field. You put the solo model and the fusion in one run and read both scores.

```python
opus = sf.Model("openrouter/anthropic/claude-opus-4.8")
gpt = sf.Model("openrouter/openai/gpt-5.5")

sf.evaluate(
    [opus, gpt, sf.Fanout([opus, gpt]) >> sf.Synthesize("openrouter/openai/gpt-5.5")],
    benchmark="medxpert",
    limit=1,
)
```

Results come back in declared order. MedXpert grading is an exact match, so it is free and this costs only the answers. On DRACO every criterion is graded by five judge passes, so even `limit=1` is a real spend.

### 4 · Read what it cost

```python
report.usage
```

```
Usage(input_tokens=6218, output_tokens=2813, cache_read_tokens=0,
      cache_creation_tokens=0, reasoning_tokens=0, cost_usd=Decimal('0.020283'))
```

`cost_usd` is the cost the provider reported, for example `Decimal('0.020283')`. Any field is `None` if even one candidate run failed to report it, rather than being silently summed as a partial total.

The local gateway starts with the request cache on, so a repeated call can be answered from it and report `cost_usd=Decimal('0')`. `use_cache=False` opts one evaluation out: its calls are made fresh and the report shows them as cache `bypass` with the reason `opted_out`.

### 5 · Watch a run

`on_event` receives typed events in sequence as the run executes, and `progress=False` silences the default display. If your callback raises, the Client cancels every active run and re-raises your exception.

```python
def observe(event: sf.Event) -> None:
    print(event.kind)

sf.evaluate(haiku, benchmark="medxpert", limit=1, on_event=observe, progress=False)
```

### 6 · Point at the engine

`sf.evaluate()` never asks where the engine is. Left unconfigured and with no local stack running, it falls back to `DEFAULT_ENGINE_URL`, a hosted engine, which is not what you want when the engine you mean is your own, so name it once with `sf.configure()`, together with its scoreboard, and every later call uses it. When `screamingface up` is running and nothing is configured, the shared Client connects to that stack instead. `sf.close()` forgets that setting, so name the engine again before the next call.

Holding your own `sf.Client` is the alternative, and the only way to address two engines from one process. `sf.AsyncClient` has the same interface with `await`.

```python
# once, at the top: every later sf.evaluate() call uses it
sf.configure(
    engine_url="https://fusion.screamingface.ai",
    scoreboard_url="https://leaderboard.screamingface.ai",
)

# or hold a client yourself
client = sf.Client(engine_url="https://fusion.screamingface.ai")
report = client.evaluate(haiku, benchmark="medxpert", limit=3)
client.close()
```

### 7 · Reopen a saved report

Every completed evaluation is saved to `~/.screamingface/results` on your machine, outside the engine's data directory and shared by every environment you use. A run that ends with failures is saved too, so you can still fetch its report. The files hold the prompts and outputs of the run.

```python
ids = sf.reports.list()          # one SavedReportInfo per saved report
saved = sf.reports.get(ids[0].id)   # the full Report, reopened from disk
sf.reports.delete(ids[0].id)        # remove it from disk
```

`sf.reports.get_async(report_id)` is the awaitable form. To stop a Client saving reports, build it with `save_results=False`; `sf.configure()` does not take that option.

```python
client = sf.Client(engine_url="https://fusion.screamingface.ai", save_results=False)
```

### 8 · Run chosen cases

`cases=[3, 17, 42]` runs those Cases instead of the first `limit`, for example a development set and a held-out set. A Case id is the position of the Case in the benchmark, from 1 to the case count. The list is sorted before it runs, so `[42, 3, 17]` is the same run as `[3, 17, 42]`. `report.selected_cases` names the Cases scored, in ascending order, and `report.selection_fingerprint` is the `sha256:` of the sorted ids joined by commas, which a paper can cite. Both are `None` for a full run and for a `limit` run, and a list equal to Cases 1 to N is the same run as `limit=N`.

```python
report = sf.evaluate(haiku, benchmark="medxpert", cases=[3, 17, 42])
report.selected_cases, report.selection_fingerprint
```

```
((3, 17, 42), 'sha256:31771f390aca49f97d87821e360188b2ff776fa5ff02c5fc63c4a6b943775352')
```

The SDK refuses these before it sends anything:

| Call | Raises |
| --- | --- |
| `cases` with `limit` | `TypeError`: `pass cases= or limit=, not both` |
| an empty list | `ValueError`: `cases must name at least one Case id` |
| an id below 1, or an id twice | `ValueError`: `Case ids must be distinct and at least 1` |
| an id that is not a whole number (a float, a string or a bool) | `TypeError`: `Case ids must be whole numbers, e.g. cases=[3, 17, 42]` |
| more than 1,000 ids | `ValueError`: `a run takes at most 1,000 Case ids; this list has 1,001` |
| `cases` on a replay (`pinned_cache=` or `score_id=`) | `TypeError`: `cases= is not supported when replaying; replay the run, or use limit=` |
| an id above the benchmark's case count | `PlanningError` with the code `invalid_benchmark_selection`: `the Benchmark has 2450 Cases; 999999 out of range`. It is not retryable. |

```python
sf.evaluate(haiku, benchmark="medxpert", cases=[1], limit=1)
```

```
TypeError: pass cases= or limit=, not both
```

A run on chosen Cases cannot be submitted to a leaderboard: `sf.leaderboards.submit` raises `ValueError` with `a run on selected Cases can't be submitted to the leaderboard; submit a full run`. The hosted engine serves the selection route: it refuses an id above the case count with the same `PlanningError`, before any model call. The SDK posts the list to the Engine's selection route and refuses before any model call when the Engine does not echo the list back, so an older Engine never runs and bills every Case. The report JSON written by `to_json()` carries no `selected_cases` key.

## When it fails

`PlanningError` means the run never started: change the candidate, benchmark or configuration. `ExecutionError` means it reached the engine and ended without a valid report. `EngineUnavailableError` means the engine was not reachable at all. `ReproductionError` means a replay could not start. A benchmark the engine does not publish raises `PlanningError`: a local engine started with `screamingface up` comes with `medxpert` ready to run, so a run against a benchmark it has not prepared raises it. Each carries a stable `code` and a `hint`.

## Links

-   [Companion notebook: `06_draco.ipynb`](https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/06_draco.ipynb)
