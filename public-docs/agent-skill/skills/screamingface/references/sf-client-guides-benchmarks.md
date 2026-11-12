# Benchmarks

Source: https://docs.screamingface.ai/sf-client/guides/benchmarks

Discover the benchmarks an engine publishes and pick the protocol you want to run.

A **benchmark** is the exam. It is owned entirely by [the engine](learn-engine.md) and it owns everything about how candidates are judged: which cases exist, in what order they are asked, which judge model grades them, how grades become a score. Your candidate answers; it does not get a say in any of that.

That split is the point. Because the exam is fixed and pinned, a solo Model and a [Fusion](sf-client-guides-fusions.md) evaluated against it are genuinely comparable.

> **What you can list depends on the engine.** A local engine started with `screamingface up` comes with `medxpert` ready to run, and other benchmarks can run locally too. The hosted engine serves the full set (including DRACO and IFEval) with no setup. To run more benchmarks on a local engine from a repository checkout, run `just local-stack-notebooks` from `packages/screamingface/`. If there's a benchmark you'd want to run first, [we'd love to hear it](https://github.com/ScreamingFace/screamingface/issues).

## What you can do with it

-   List the benchmarks this engine publishes.
-   Read one's identity card: size, revision, and what it actually measures.
-   Check that two results are comparable by comparing revisions.

## Main APIs

| API | What it does |
| --- | --- |
| `sf.benchmarks.list()` | Lists every benchmark this engine publishes, a free discovery request that calls no model. |
| `sf.benchmarks.get(benchmark_id)` | Fetches one benchmark's identity card: its id, title, description, revision and size. |
| `sf.Benchmark` `.id` `.title` `.description``.revision` `.case_count` | The identity card itself: its id, what it measures, the opaque revision hash of the pinned protocol, and its size. |
| `sf.BenchmarkInfo` | The pinned subset a report carries, so an old result still names the exact revision it ran against. |

**Discovery is free.** Listing benchmarks and reading identity cards are plain engine requests; no model is called and nothing is charged. Only [evaluation](sf-client-guides-running-an-evaluation.md) spends.

## How to

### 1 · See what this engine publishes

A local engine comes with `medxpert` ready to run:

```python
import screamingface as sf

[(b.id, b.case_count, b.revision) for b in sf.benchmarks.list()]
```

```
[('medxpert', 2450, '1e5a3b8a461a52f7')]
```

Asking a local engine for a benchmark it does not publish raises `PlanningError`:

```python
sf.benchmarks.get("ifeval")
```

```
PlanningError: Benchmark 'ifeval' is not installed on this Engine
```

The hosted engine needs an account the OpenMined team grants. It publishes 91 benchmarks:

```python
hosted = sf.Client(engine_url="https://fusion.screamingface.ai")
benchmarks = hosted.benchmarks.list()
len(benchmarks), [b.id for b in benchmarks if b.id.startswith("draco")]
```

```
(91, ['draco', 'draco-3pass'])
```

Benchmarks differ in what grading costs. **MedXpert** is 2,450 expert-level medical multiple-choice questions graded by exact match against the published key, so its grading is **free** and only the answers cost anything. **IFEval** is 541 instruction-following prompts checked by a deterministic verifier, so no judge model is called. **HealthBench** is rubric-graded by a judge model: the professional exam is 525 conversations, and `healthbench-worst30` is the 157 hardest of them. On the hosted engine, **DRACO** is 100 deep-research tasks graded by a judge model that judges every answer five times for `draco` and three times for `draco-3pass`.

### 2 · Read the identity card

```python
medxpert = sf.benchmarks.get("medxpert")
medxpert.title, medxpert.revision, medxpert.case_count
```

```
('MedXpertQA', '1e5a3b8a461a52f7', 2450)
```

The `revision` is an opaque hash of the pinned protocol, and it is stamped into every report produced against it. That is what keeps old results attributable: if the public name later points at a newer snapshot, your report still names the revision it actually ran.

### 3 · Know what discovery will not tell you

A `Benchmark` carries no case data, so the prompts cannot be paged before a run. Cases stay on the engine and grading runs there, and that separation is what makes a verified result meaningful rather than self-reported. The case text a candidate received, its answer, and the grade behind it, including the rubric criteria and the judge, all arrive with the report afterwards, on [CandidateResult.cases](sf-client-api-reports.md).

## Links

-   [Companion notebook: `11_medxpert.ipynb`](https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/11_medxpert.ipynb)
