# Benchmarks

Source: https://docs.screamingface.ai/sf-client/api/benchmarks

Benchmark and the read-only values discovery returns.

A benchmark is a fixed set of cases, owned by the engine and pinned by a revision. This page covers `Benchmark` itself, alongside `BenchmarkInfo` for the compact identity a report keeps of it. See the [Benchmarks guide](sf-client-guides-benchmarks.md) for choosing which benchmark to run, and the [Models page](sf-client-api-models.md) for the model routes the engine can run a benchmark against.

A [Client](sf-client-api-clients.md) returns these values, which are all read-only, and assigning to a field raises `FrozenInstanceError: cannot assign to field 'id'`. They also never refresh themselves, so the Client needs to be called again when current data is desired.

## Benchmark

A `Benchmark` is the engine's record of one benchmark, carrying its identity, its size, and what it measures. `client.benchmarks.get(id)` returns a single benchmark and `client.benchmarks.list()` returns every benchmark the engine offers. The list depends on the engine: a local engine started with `screamingface up` comes with `medxpert` (2,450 cases) ready to run, and other benchmarks can run locally too; the hosted engine serves the full set with no setup. To run more benchmarks on a local engine from a repository checkout, run `just local-stack-notebooks` from `packages/screamingface/`.

```python
import screamingface as sf

client = sf.Client(engine_url="http://127.0.0.1:9108")
[(b.id, b.case_count) for b in client.benchmarks.list()]
```

```
[('medxpert', 2450)]
```

### Attributes

| Name | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | Stable identifier, one flat lowercase identifier such as `ifeval` or `draco-3pass`. This is what you pass as `benchmark=` when evaluating. |
| `title` | `str` | Display name, such as `IFEval`. |
| `description` | `str` | Prose describing what the benchmark measures and how it is graded. |
| `revision` | `str` | Opaque content hash of this benchmark's current state. Two reports are only comparable when their revisions match. |
| `case_count` | `int` | How many cases the benchmark holds in total. |
| `origin` | `str` | Where the benchmark comes from, as the engine serves it. `'screamingface'` when an older engine serves none. |
| `interaction` | `str | None` | How a case is asked, such as `'single_shot'` or `'multi_turn'`. `None` when the engine does not serve it. |
| `difficulty` | `str | None` | The engine's tier for the benchmark, such as `'medium'` or `'hard'`. `None` when the engine does not serve it. |
| `inverted_grade` | `bool` | `True` when every case score is already 1 minus the eval's grade, as for a benchmark scored by refusal rate. It is a mark, not an instruction: never flip a score with it. |
| `provenance` | `BenchmarkProvenance | None` | The benchmark's cover sheet: `paper_url`, `authors`, `citation`, `inspect_contributors`, `homepage_url`, `harness_url`, `license`, `license_note`, `content_warning`, `human_baseline`, `frontier_score` (each score a `PublishedScore` with `score`, `source_url`, `model` and `as_of`) and `notebook`. `None` when the engine serves none. |
| `saturation` | `str` | The engine's verdict on whether frontier models already top the benchmark: `'saturated'`, `'open'` or `'unknown'`. |
| `attempts` | `int` | How many times each case is asked. A check counts as met if any attempt met it. `1` for an ordinary benchmark. |

Note: A `Benchmark` carries no case data. The Client cannot page a benchmark's prompts, because the cases stay on the engine. Case text becomes visible after a run, through the `CaseResult` values on [CandidateResult.cases](sf-client-api-reports.md).

## BenchmarkInfo

A `BenchmarkInfo` is the pinned identity of a benchmark as it stood when a run took place. It is the value embedded in a [Report](sf-client-api-reports.md), which is why it carries a revision but no title or description: its purpose is to make a result reproducible rather than to describe the benchmark.

Note:`BenchmarkInfo.case_count` is the benchmark's full size, not the number of cases a run covered. The two differ: after evaluating with `limit=1`, `report.case_count` is `1` while `report.benchmark.case_count` remains `2450` for `medxpert`.

| Name | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | The benchmark identifier. |
| `revision` | `str` | The revision the run was executed against. |
| `case_count` | `int` | The benchmark's full size. For what the run covered, read `report.case_count`. |
| `inverted_grade` | `bool` | The benchmark's refusal-rate mark as it stood at the run. `False` for an ordinary benchmark. |

## Validation

Both types validate their arguments on construction, so a malformed value cannot exist. Blank strings raise `ValueError`, non-strings raise `TypeError`, and `case_count` rejects zero and negative values:

```
ValueError: Benchmark case_count must be a positive integer
```
