# Usage

Source: https://docs.screamingface.ai/sf-client/api/usage

Usage for token and cost accounting, and Failure for anything that went wrong.

This page covers `Usage`, the token and cost accounting a [Report](sf-client-api-reports.md) and each [CandidateResult](sf-client-api-candidate-result.md) carry, and `Failure`, the typed record of anything that went wrong. The `report` the examples read from comes from the [Report](sf-client-api-reports.md) page.

## Usage

A `Usage` holds the token and cost accounting for one subtree of a run. Every field is optional, because a provider that does not report a number leaves it as `None` rather than guessing zero.

| Name | Type | Meaning |
| --- | --- | --- |
| `input_tokens` | `int | None` | Tokens sent. |
| `output_tokens` | `int | None` | Tokens generated. |
| `cache_read_tokens` | `int | None` | Tokens served from a provider cache. |
| `cache_creation_tokens` | `int | None` | Tokens written into a provider cache. |
| `reasoning_tokens` | `int | None` | Tokens spent on reasoning, where the provider separates them. |
| `cost_usd` | `Decimal | None` | Money, as a `Decimal` so it never loses precision. Accepts a string or a `Decimal` on construction. |

```python
report.usage
```

```
Usage(input_tokens=3460, output_tokens=1609, cache_read_tokens=0, cache_creation_tokens=0, reasoning_tokens=0, cost_usd=Decimal('0.0050605'))
```

A model call answered from the request cache reports 0 tokens and a `cost_usd` of `Decimal('0')`. The sample above ran with `use_cache=False`, so every call was fresh. The [CandidateResult](sf-client-api-candidate-result.md) page lists what the cache saved.

Summing follows a strict rule: `report.usage` adds a field across candidates only when *every* candidate reported it. If one candidate leaves `cost_usd` as `None`, the report's `cost_usd` is `None` too, rather than a total that silently omits part of the run.

`to_dict()` drops fields that are `None` and renders `cost_usd` as a string.

## Failure

A `Failure` is one typed failure held inside an otherwise valid report. A report with failures is still a report, so what succeeded can be read alongside what did not.

| Name | Type | Meaning |
| --- | --- | --- |
| `stage` | `str` | Where it happened: `candidate`, `grading` or `aggregation`. |
| `code` | `str` | Stable machine-readable identifier in lowercase snake\_case, such as `provider_timeout`. Match on this rather than on the message. |
| `message` | `str` | Human-readable explanation. Not stable across versions. |
| `retryable` | `bool | None` | Whether running the same thing again could plausibly succeed, or `None` when the engine did not say. |
| `operation_id` | `str | None` | Which step failed, matching an `OperationInfo.id`. `None` for a failure no single step owns. |
| `case_id` | `int | str | None` | Which case failed, when the failure was specific to one. |
| `metadata` | `Mapping[str, object]` | Whatever else the engine attached to this failure. Empty when it attached nothing. |

A failure reads like this:

```python
Failure(stage='candidate', code='provider_timeout', message='Upstream timed out', retryable=True, operation_id='op-1', case_id='7')
```
