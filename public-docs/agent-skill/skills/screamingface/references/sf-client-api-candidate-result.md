# CandidateResult

Source: https://docs.screamingface.ai/sf-client/api/candidate-result

One candidate's outcome and the values it carries (MemberResult, OperationInfo, CaseResult), and the CaseGrade tree behind each case score.

A `CandidateResult` is one candidate's outcome inside a [Report](sf-client-api-reports.md). The candidate is whatever [recipe](sf-client-api-recipes.md) you evaluated: a Model, a fanout block, or a Pipeline. This page covers `CandidateResult` itself, alongside `MemberResult` for one member of a fusion, `OperationInfo` for a step that ran, and `CaseResult` for one graded case. Every example below reads from a `candidate` pulled off a report with `report.candidates.only`.

## CandidateResult

A `CandidateResult` is one candidate's outcome. A higher `score` is always better, whatever the benchmark measures.

| Name | Type | Meaning |
| --- | --- | --- |
| `name` | `str` | The recipe's name, unique within the report. |
| `kind` | `str` | One of `model`, `fusion`, `pipeline`, `corrective_loop` or `self_corrective`. |
| `score` | `float | None` | The headline number, or `None` when the candidate failed or was not scored. |
| `coverage` | `float` | How much of the selected case set the score was computed from, between 0 and 1. Below `1.0` the engine excluded ungraded cases and the score is a partial result over the rest. |
| `metrics` | `Mapping[str, float]` | The benchmark's individual measures. Empty when `score` is `None`: an unscored candidate cannot carry metrics. Never contains a `coverage` key, which is the field above instead. |
| `benchmark` | `BenchmarkInfo` | The benchmark identity this candidate ran against, pinned to its revision. The report carries the same value. |
| `cases` | sequence of `CaseResult` | One entry per selected case, carrying its status, the prompt, the answer, and the grade. |
| `url4` | `Url4` | The complete expression that executed, as a `str` subclass whose `to_python()` returns editable client code. See the [url4 guide](sf-client-guides-reproduce-and-share.md). |
| `models` | `tuple[str, ...]` | Every distinct model route this candidate used. Unique, and never empty. |
| `operations` | `tuple[OperationInfo, ...]` | The steps that ran, as an acyclic graph. Never empty. |
| `members` | `tuple[MemberResult, ...]` | The candidate's direct members. Always empty for a `model`, `pipeline` or `self_corrective` candidate; at least one entry for a `fusion`; at least two for a `corrective_loop`. |
| `failures` | `tuple[Failure, ...]` | This candidate's own failures. A scored candidate can carry them: the run finished with warnings worth reading. None of them names a case, since a candidate-level failure is never case-specific. |
| `usage` | `Usage` | This candidate's accounting. |
| `run_id` | `str` | Engine-assigned identifier for this candidate's execution. |
| `started_at` / `completed_at` / `duration_ms` | `datetime` / `int` | When it ran and for how long. |
| `answer_seed` | `int | None` | The answer seed the run used. `None` for an unseeded run. `submit` sends it with the score. |
| `selected_cases` | `tuple[int, ...] | None` | The Case ids this candidate scored on a `cases=` run, ascending. `None` for a full run and for a `limit` run. |
| `pinned_cache` | `str | None` | The id of the pinned cache that the run opened. `None` when the run was not captured (the default) or the copy did not open. |
| `reproduction` | `Reproduction | None` | Verdict for a full replay of a published score. Read `.outcome` for `"exact"` or `"failed"`, `.reason` for a failure, and `.missed_cases` for cases the pinned cache could not answer. `None` for fresh evaluations, partial replays and captures without a public score. See the [Reproduction reference](sf-client-api-leaderboards.md). |
| `capture_status` | `"complete" | "partial" | None` | Whether the copy holds the whole run. `None` means unknown, not partial. `submit` sends both fields with the score. |
| `capture_partial_reasons` | `tuple[str, ...]` | The names of the partial reasons that have a count above zero, sorted. Empty when the run is complete or was not captured. A local capture shows `("local",)`. `to_dict()` always includes it, as a list. |
| `trace_id` · `client_version` | `str | None` | The trace id of the run, and the screamingface version the engine saw as the caller. `None` when unavailable. |
| `run_cost_status` | `"complete" | "partial" | "unavailable"` | A fact about `usage.cost_usd`: `complete` says the amount is exact, the other two say it is absent. It is sent with a leaderboard submission. |
| `cache_hits` | `int` | How many gateway round trips the response cache served for this run. |
| `cache_saved_cost_usd` · `cache_saved_cost_archive_usd` | `Decimal | None` | What the cache hits would have cost. The first is what the provider reported for the call that filled the entry. The second is a measured amount from a different call of the same model and kind. Never add the two together. `None` means none was observed, which is not zero. |
| `cache_unpriced_hits` | `int | None` | The count of cache hits with no price at all, from the engine's run summary. `None` when no summary arrived. |
| `abstained_count` | `int` | How many cases a reducer abstained on. See [Reducers](sf-client-api-reducers.md). |
| `accounting` | `AccountingBreakdown` | What each operation consumed. See Accounting, answers and trace below. |

```python
dict(candidate.metrics)
```

```
{'correct': 0, 'scored_cases': 1, 'answered': 1, 'answered_rate': 1.0}
```

`score` and `coverage` together describe four outcomes, and the notebook card labels each one: a score at full coverage and no failures is complete; a score with failures completed with warnings; a score at coverage below `1.0` is partial; and no score at all means no aggregate was available.

### cases

`candidate.cases` is a read-only sequence of `CaseResult` values, one per selected case. Each carries a `status` of `scored`, `refused` or `failed`, the case `input`, the candidate's `output`, and a `CaseGrade` holding the individual checks behind the score. A refused case is still graded, so a provider refusal is measured rather than dropped.

```python
case = candidate.cases[0]
case.status, case.grade.score, case.output[:40]
```

```
('scored', 0.0, 'To determine the most appropriate indica')
```

## CaseResult

A `CaseResult` is the complete retained result for one selected case. Its `status` records the closed outcome, and the remaining fields carry the prompt, the answer, the grade, and anything that went wrong. A scored case carries an `output` and a numeric `grade` and no failures; a refused case carries a `refusal` and no output; a failed case carries `failures` and no numeric grade.

| Name | Type | Meaning |
| --- | --- | --- |
| `status` | `str` | The closed outcome: `scored`, `refused` or `failed`. |
| `case_id` | `int | str` | The benchmark's identifier for this case. |
| `input` | `str` | The case prompt as it was sent, structured multi-turn cases included. |
| `output` | `str | None` | The candidate's answer, or `None` when it refused or failed. |
| `finish_reason` | `str | None` | Why generation stopped, when the engine reported it. |
| `refusal` | `str | None` | The provider's refusal message, set only on a refused case. |
| `stop_reason` | `str | None` | For a multi-round case, why the loop stopped: `passed` or `max_rounds`. `None` for a single-round case. |
| `rounds_executed` | `int | None` | How many rounds ran, present together with `stop_reason` and `None` otherwise. |
| `grade` | `CaseGrade | None` | The grade behind the case score. `None` when the case was not graded. |
| `failures` | `tuple[Failure, ...]` | This case's own failures, each naming this case. Empty when nothing went wrong. |
| `operations` | `tuple[CaseOperation, ...] | None` | The per-operation outputs captured during the run, or `None` when the engine attributed none. See [CaseOperation](#case-operation) below. |
| `metadata` | `Mapping[str, object]` | Anything else the engine recorded with the case. Empty when it recorded nothing. |

## CaseOperation

A `CaseOperation` carries one operation's captured terminal output for a case: the member or synthesis text the engine attributed to that step's stable operation id, so a fusion's contribution can be read back from a saved report. Its `output` and `finish_reason` stay `None` when the engine could not attribute the output unambiguously. Reach these through `CaseResult.operations`.

| Name | Type | Meaning |
| --- | --- | --- |
| `operation_id` | `str` | The step this output belongs to, matching an `OperationInfo.id`. |
| `output` | `str | None` | The step's terminal output, or `None` when it was not attributed. |
| `accounting` | `OperationAccounting | None` | What the step consumed, or `None` when it was not attributed. |
| `combine` | `CombineEvidence | None` | For a combine step, what it read and decided for the case. See [Combine evidence](#combine-evidence). `None` for any other step. |
| `finish_reason` | `str | None` | Why that step stopped, or `None` when it was not attributed. |

## Case media

`CaseResult.media` lists the pictures and files of a case as a tuple of `CaseMedia`, in the case's order. It makes no network call, and it is empty for a text case. A `CaseMedia` names what proves the bytes and not the bytes themselves.

[Diagram: Sequence: the Case media item is read from the report with no network call; sf.fetch_media asks the engine for the bytes and returns FetchedMedia when the size and SHA-256 match, or raises MediaUnavailableError with the code media_not_kept when the engine does not hold the item.]

Reading a CaseMedia makes no call. Fetching it does, and fails with media\_not\_kept when the engine no longer holds it.

| Name | Type | Meaning |
| --- | --- | --- |
| `kind` | `"image" | "file"` | Whether the item is a picture or a file. |
| `media_type` | `str` | The media type, such as `image/png`. |
| `size` | `int` | The size in bytes. |
| `sha256` | `str` | The SHA-256 digest of the bytes. |
| `filename` | `str | None` | The item's own name, when it has one. |

`str(item)` is the placeholder line that every view shows, for example `image/png · 300 KB · sha256 9f86d081…`.

`sf.fetch_media(item)` and `Client.fetch_media(item)` fetch the bytes from the engine and return a `FetchedMedia` only when the size and the SHA-256 match the placeholder. `AsyncClient` has no `fetch_media`. A `FetchedMedia` has `media`, the `CaseMedia` it came from, and `data`, the bytes. `save(path)` writes the bytes to `path`, or into it under the item's name when `path` is a folder, and returns the `Path`. An item with no name is saved under a name made from its SHA-256 and its media type, for example `3fcd47b91497.jpg`. A picture shows inline in Jupyter, and a file shows its placeholder line.

A local engine started with `screamingface up` comes with `medxpert` ready to run, which has no pictures. The example below ran on the 0.1.11 engine from a repository checkout, started with `just local-stack-notebooks` from `packages/screamingface/`, which adds `inspect-lab_bench_figqa`, whose cases each carry one picture.

```python
report = sf.evaluate(model, benchmark="inspect-lab_bench_figqa", limit=1)
case = report.candidates.only.cases[0]
item = case.media[0]            # a CaseMedia, with no network call
item, str(item)
```

```
(CaseMedia(kind='image', media_type='image/jpeg', size=1962250, sha256='3fcd47b91497d9cd78e49e90efc006bb54f74c2a8f4057c8b2424fa9d6ec1a5a', filename=None),
 'image/jpeg · 1.9 MB · sha256 3fcd47b9…')
```

```python
fetched = sf.fetch_media(item)   # checks size and sha256 against the placeholder
len(fetched.data), fetched.save("picture.jpg")
```

```
(1962250, PosixPath('picture.jpg'))
```

A local engine keeps parked pictures and files for 48 hours by default. After that, or when the engine never held the item, the fetch raises `MediaUnavailableError` with the code `media_not_kept`. The error is permanent, so retrying does not help.

```python
sf.fetch_media(item)
```

```
MediaUnavailableError: The engine no longer holds x.png · image/png · 10 B · sha256 00000000…; a local engine drops parked pictures and files after a while (48 hours by default). Run the Case again to see it.
```

A benchmark whose Cases carry pictures refuses a model that the gateway reports as text-only, and a model the gateway knows nothing about counts as text-only. The call raises `ExecutionError` with the code `intent_error`. The error is permanent (`retryable` is `False`), and the message names the models. With two candidates where one is text-only, the call raises `ExecutionError` with the code `candidates_failed`.

```python
m = sf.Model("openrouter/deepseek/deepseek-v4-flash")
sf.evaluate(m, benchmark="inspect-lab_bench_figqa", limit=1)
```

```
ExecutionError: This Benchmark's Cases carry pictures, and these models cannot take images: openrouter/deepseek/deepseek-v4-flash. The gateway reports them as text-only; a model it knows nothing about counts as text-only too.
```

## Accounting, answers and trace

`candidate.accounting` is a property, not a method. It returns an `AccountingBreakdown` with `rows`, `unattributed_cost_usd` and `consistent`. Each row is an `AccountingRow` with `accounting`, `case_id`, `label`, `member_id`, `model`, `operation_id` and `stage`, one of `generation`, `synthesis` or `grading`. The row's `accounting` is an `OperationAccounting`: `provider`, `request_model`, `response_model`, `usage`, `provider_latency_ms`, `provider_attempts` and `cache`. Fields the engine did not report stay unknown and are never filled in.

`OperationCache` counts the responses of one operation by how the cache treated them: `hits`, `misses`, `bypasses` and `unknown`. The four counts sum to the model-call responses the operation represents.

A `CaseResult` also carries:

-   `abstained`: `True` when a reducer found no usable answer, so the output is `''` and the score is `0.0`.
-   `attempts`: every attempt's own answer, finish reason, failures, grade and cost, in order, for a benchmark that asks each case several times. `None` for every other benchmark.
-   `answers(operation_id=None)`: one `sf.Answer` per member and one for each combine step. An answer's `status` is `answered`, `abstain`, `excluded` or `fail`. A case with no combine step returns `()`. An unknown `operation_id` raises `ValueError`.
-   `trace()`: `TraceEntry` values in operation order, of kind `model_call`, `extract` and `reduce`. `Report.trace_dict()` exports them.

## Combine evidence

`CaseOperation.combine` is a `CombineEvidence` for a combine step. It holds `kind`, `reducer`, `operators`, `members`, `tally`, `judge`, `fields`, `chosen`, `built`, `agreement`, `tie`, `median`, `mean`, `presentation_order`, `separator_collision`, `signal`, `cut`, `narrow`, `consistency`, `declared`, `gate`, `result`, `dropped` and `finish_reason`. A field that the step does not use is `None` or empty.

| Type | Fields | Meaning |
| --- | --- | --- |
| `CombineAnswerRow` | `member_id`, `raw`, `value`, `status`, `reason`, `signals`, `weight`, `score`, `rank` | One row per member. `status` is `answered` or `excluded` in the runs above. `reason` is `not_selected` for a member that a narrow step left out and `no_signal` for a member with no value for the signal that a step reads. `signals` holds each signal of the member, such as `score:judge`. |
| `CombineNarrow` | `reduce`, `select`, `signal`, `kept`, `cut`, `scores`, `ranks` | One record per narrow step: the select operator, the signal it read, the kept member ids and, for a `sf.Rank`, the cut, the scores and the ranks (1 is the best, and equal scores take author order). |
| `CombineCut` | `k`, `order` | The `k` and the order of a `sf.Rank`. |
| `CombineGate` | `observe`, `observed`, `cmp`, `threshold`, `passed`, `branch`, `otherwise`, `abstain_band` | What a `sf.Gate` read, the comparison, and which branch ran. |
| `CombineJudgeReading` | `raw`, `returns`, `parsed` | The judge's reply as text and as one number per member. |
| `CombineResult` | `member_id`, `value`, `status`, `reason` | What the step decided. |

A chain `Fanout([1, 1, 2]) >> Judge(...) >> Rank(2, by="score:judge") >> Vote()` leaves the third member out. These are the records it produced:

```python
op = next(o for o in case.operations if o.combine is not None)
evidence = op.combine
evidence.narrow[0], [(m.member_id, m.status, m.reason) for m in evidence.members]
```

```
(CombineNarrow(reduce='scores@1', select='top_k@1', signal='score:judge',
               kept=('member_1', 'member_2'), cut=CombineCut(k=2, order='max'),
               scores={'member_1': 10.0, 'member_2': 10.0, 'member_3': 2.0},
               ranks={'member_1': 1, 'member_2': 2, 'member_3': 3}),
 [('member_1', 'answered', None), ('member_2', 'answered', None), ('member_3', 'excluded', 'not_selected')])
```

A `sf.Gate` that does not hold records the comparison and abstains:

```
CombineGate(observe='agreement', observed=0.6666666666666666, cmp='>=', threshold=0.7,
            passed=False, branch='fallback', otherwise='abstain', abstain_band=None)
CombineResult(member_id=None, value=None, status='abstain', reason='gate_not_met')
```

The `reduce` entry of `case.trace()` has the keys `operation_id`, `op`, `rule`, `mode`, `tally`, `chosen`, `signal`, `result`, `dropped`, `judge_operation_id` and `judge_model`. The two judge keys name the judge call of a step that reads the judge directly. For `Judge >> ArgMax("score:judge")` they are `op_judge_1` and `openrouter/google/gemini-3.5-flash-lite`. For `Judge >> Rank >> Vote` they are `None`.

## How a case is graded

A `CaseResult`'s `grade` is a `CaseGrade`, and it is the top of a small tree. A grade holds ordered `Check`s; each check holds the `Evidence` gathered for it; each piece of evidence names the `EvidenceProducer` that observed it. Reading down takes you from one case score to the exact observation a benchmark accepted or rejected.

[Diagram: A CaseGrade holds many ordered Checks; each Check holds the Evidence gathered for it; each Evidence names the one EvidenceProducer that observed it.]

## CaseGrade

The aggregate for one case: a `score`, the `method` that produced it, and the ordered `Check`s it was built from.

| Name | Type | Meaning |
| --- | --- | --- |
| `method` | `str` | How the score was produced. |
| `score` | `float | None` | The case's score, or `None` when no aggregate was available. |
| `checks` | `tuple[Check, ...]` | The ordered checks behind the score. |

## Check

One ordered grading check and all the `Evidence` gathered for it. The benchmark owns the check; the Client only reports what it returned, so match on `id` rather than on `label`.

| Name | Type | Meaning |
| --- | --- | --- |
| `type` | `str` | The check's kind. |
| `id` | `str` | Identifies the check within the case. The stable value to match on. |
| `label` | `str` | A human-readable description of what it checks. |
| `evidence` | `tuple[Evidence, ...]` | The observations gathered for it, in sequence order. |
| `outcome` | `str | None` | `MET` or `UNMET`, or `None` when it produced no verdict. |
| `score` | `float | None` | The check's own score, where it has one. |

## Evidence

One exact observation a check accepted or rejected. When `valid` is `False` the observation could not be read, so it carries no `outcome` and no `explanation`: that state records a gap rather than a verdict.

| Name | Type | Meaning |
| --- | --- | --- |
| `sequence` | `int` | Position within the check, unique and 1-based. This is the true order. |
| `producer` | `EvidenceProducer` | What observed it. |
| `valid` | `bool` | Whether the observation could be read at all. |
| `outcome` | `str | None` | `MET`, `UNMET`, `PASS` or `FAIL`. Unset on invalid evidence. |
| `explanation` | `str | None` | Why, when the producer gave a reason. Unset on invalid evidence. |
| `raw_output` | `object` | The producer's raw output, as it was returned. |
| `accounting` | `OperationAccounting | None` | What the producer consumed, or `None` for a deterministic producer. |
| `metadata` | `Mapping` | Anything else recorded with the observation. |

## EvidenceProducer

The producer the engine credits with one observation: what looked at the output and reported.

| Name | Type | Meaning |
| --- | --- | --- |
| `type` | `str` | The kind of producer, such as the grader that ran. |
| `id` | `str` | Identifies the producer. |

## MemberResult

A `MemberResult` is one direct member of a fusion, held as a compact view: enough to see what the member cost and whether it failed, without repeating the full candidate structure. Members carry no score, because only the fusion's final answer is graded.

Its runtime fields are `None` until the engine attributes work to the member's operation id. That is a different statement from an empty value: `None` means the attribution was unavailable, while an empty tuple means it arrived and reported nothing.

| Name | Type | Meaning |
| --- | --- | --- |
| `name` | `str` | The member recipe's display name. Two siblings can share one, for instance the same model reached through two providers, so identity is `operation_id` rather than this. |
| `kind` | `str` | One of `model`, `fusion`, `pipeline`, `corrective_loop` or `self_corrective`. |
| `models` | `tuple[str, ...]` | The routes this member used. |
| `operation_id` | `str` | Links this member to an entry in the candidate's `operations`. |
| `failures` | `tuple[Failure, ...] | None` | This member's failures, which also appear in `report.failures`. `None` when the engine attributed nothing to this member. |
| `duration_ms` | `int | None` | How long the member took, when the engine reported it. |
| `usage` | `Usage | None` | This member's accounting, or `None` when it was not attributed. |

## OperationInfo

An `OperationInfo` is one step in a candidate's compiled graph. Reading `operations` shows what actually ran and in what order, which is how a fusion's members can be seen executing before its synthesis. See the [url4 guide](sf-client-guides-reproduce-and-share.md) for reading the same plan as a url4 expression.

| Name | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | Unique within the candidate. This is what `depends_on` refers to. |
| `kind` | `str` | What sort of step it was, for example `model`. |
| `label` | `str` | Human-readable description, such as `claude-haiku-4.5 answer`. |
| `depends_on` | `tuple[str, ...]` | Ids of the steps that had to finish first. Empty for a step with no prerequisites. |

```python
candidate.operations
```

```
(OperationInfo(id='op_model_1', kind='model', label='gemini-3.5-flash-lite answer', depends_on=()),)
```

The operations of a candidate form an acyclic graph: ids are unique, every dependency names a step that exists, and no step can depend on itself.
