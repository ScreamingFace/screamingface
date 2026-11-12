# Reports

Source: https://docs.screamingface.ai/sf-client/api/reports

Report and everything it carries.

A `Report` is what an evaluation returns, and it is the only thing worth keeping: it carries the scores, what was spent, what failed, and the exact expression that ran. This page covers `Report` itself. It holds [CandidateResult](sf-client-api-candidate-result.md) values, each of which may hold `MemberResult` and `OperationInfo` values, and both a report and each candidate carry a [Usage](sf-client-api-usage.md) and any `Failure` records. See the [evaluation guide](sf-client-guides-running-an-evaluation.md) for running one.

```python
import screamingface as sf

client = sf.Client(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)
report = client.evaluate(
    sf.Model("openrouter/google/gemini-3.5-flash-lite"),
    benchmark="medxpert",
    limit=1,
)
report
```

```
Report(benchmark='medxpert', candidates=['gemini-3.5-flash-lite'], ok=True)
```

Every example below reads from that report.

[Diagram: A Report holds one BenchmarkInfo and many CandidateResult values. Each CandidateResult holds many OperationInfo (the plan DAG), many CaseResult (per-case grades), a Usage, its url4 expression, and, for a fusion, many MemberResult values.]

A report holds one benchmark identity and one result per candidate; each candidate carries its plan, its cases, its members, its usage, and its url4.

## Report

A `Report` represents one evaluation. Its constructor is public, but in normal use a [Client](sf-client-api-clients.md) returns it and it is never constructed directly.

### Attributes

| Name | Type | Meaning |
| --- | --- | --- |
| `benchmark` | `BenchmarkInfo` | Which benchmark, at which revision, this ran against. |
| `case_count` | `int` | How many cases this run actually covered. |
| `candidates` | sequence of `CandidateResult` | One entry per candidate you evaluated, in the order you passed them. |
| `selected_cases` | `tuple[int, ...] | None` | The Case ids a `cases=` run scored, ascending. `None` for a full run and for a `limit` run. |
| `selection_fingerprint` | `str | None` | The `sha256:` of the sorted selected ids joined by commas, for example of `3,17,42`. `None` when `selected_cases` is `None`. |
| `ok` | `bool` | `True` when nothing failed anywhere in the run, at candidate or member level. |
| `failures` | `tuple[Failure, ...]` | Every failure from every candidate and every member, flattened into one tuple. |
| `usage` | `Usage` | The whole run's accounting, summed across candidates. |
| `started_at` / `completed_at` | `datetime` | Earliest start and latest finish across candidates. Always timezone-aware. |
| `duration_ms` | `int` | Wall-clock milliseconds between those two. |

```python
report.ok, report.case_count, report.duration_ms
```

```
(True, 1, 7187)
```

Note:`report.case_count` and `report.benchmark.case_count` are different numbers. The first is what this run covered; the second is the benchmark's full size.

```python
report.benchmark
```

```
BenchmarkInfo(id='medxpert', revision='1e5a3b8a461a52f7', case_count=2450, inverted_grade=False)
```

Two reports are only comparable when both the id and the revision match.

### candidates

`report.candidates` is a read-only sequence supporting iteration, positional indexing and slicing. It also indexes by candidate name, and offers `.only` for the common case of a single candidate.

```python
candidate = report.candidates.only
candidate.name, candidate.kind, candidate.score, candidate.coverage
```

```
('gemini-3.5-flash-lite', 'model', 0.0, 1.0)
```

```python
report.candidates["gemini-3.5-flash-lite"] is candidate
```

```
True
```

`.only` raises `ValueError` when the report holds more than one candidate, and indexing by an unknown name raises `KeyError`. Candidate names are unique within a report.

Each entry is a [CandidateResult](sf-client-api-candidate-result.md), one candidate's outcome, holding its score, its cases, its operation graph, its members, its [Usage](sf-client-api-usage.md), and its url4.

### Serialisation

`to_dict()` returns a plain JSON-compatible dictionary and `to_json()` returns it as a compact string. Both carry a `schema` field, `screamingface.report.v1`, so a consumer can tell what it is reading. `export(path="report.json")` writes that same document to disk, creating parent directories and replacing an existing file, and returns the path it wrote. `export(path, *, format="json", candidate=None)` also takes `format="inspect"`, which writes one candidate's run, named by `candidate=`, as an inspect `.eval` log. That format needs the `inspect` extra (`pip install "screamingface[inspect]"`), which does not install in the same environment as the `runtime` extra. `trace_dict()` returns the per-operation trace as a dictionary with a `schema` and a `candidates` key.

```python
sorted(report.to_dict())
```

```
['benchmark', 'candidates', 'completed_at', 'schema', 'started_at', 'usage']
```

## Saved reports

A Client saves every completed report to `~/.screamingface/results` unless it was built with `save_results=False`. That folder is outside the engine's data directory and shared by every environment on the machine, and the files hold the prompts and outputs of each run. A run that ends with failures is saved too. The `sf.reports` module reopens them.

| Function | Returns |
| --- | --- |
| `sf.reports.list(*, directory=None)` | A list of `SavedReportInfo`, one per saved report, with `id`, `candidates`, `directory`, `downloaded` and `size_bytes`. The order is not guaranteed. |
| `sf.reports.get(report_id, *, directory=None, destination=None)` | The saved `Report`. `get_async` is the awaitable form. |
| `sf.reports.delete(report_id, *, directory=None)` | `None`. Removes the saved report from disk. |

`directory=` points the call at a different folder than `~/.screamingface/results`.

## Beyond the report

Each candidate's outcome lives on the [CandidateResult](sf-client-api-candidate-result.md) page, which covers `CandidateResult` itself alongside `MemberResult`, `OperationInfo` and `CaseResult`. The token and cost accounting a report and its candidates carry, and the `Failure` records they hold, are on the [Usage](sf-client-api-usage.md) page.
