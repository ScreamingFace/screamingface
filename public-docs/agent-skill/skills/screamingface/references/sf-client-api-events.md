# Events

Source: https://docs.screamingface.ai/sf-client/api/events

What a run reports through on_event while it is still running.

Passing `on_event` to [evaluate()](sf-client-api-clients.md) gives you a callback that fires as the run proceeds, rather than waiting for the [Report](sf-client-api-reports.md) at the end. It is how a progress display, a log, or a running cost total is built.

```python
import screamingface as sf

def observe(event: sf.Event) -> None:
    print(event.kind, event.sequence, event.source)

sf.evaluate(recipe, benchmark="medxpert", limit=1, on_event=observe, progress=False)
```

Five event types arrive: `Started`, `Span`, `Log`, `Usage` and `Terminated`, with `Terminated` last. `Event` is their shared base and `TerminationError` is a value one of them carries.

## Event

The base every event inherits. These fields are present on all of them, so a callback can sort and correlate without knowing which kind it received.

| Name | Type | Meaning |
| --- | --- | --- |
| `kind` | `str` | Which type this is: `started`, `span`, `log`, `usage` or `terminated`. A class attribute, not a field. |
| `id` | `str` | Identifies this event. |
| `run_id` | `str` | Which run emitted it. Several candidates run concurrently, so this is what separates them. |
| `sequence` | `int` | Order within the run. Events can arrive out of order; this is the true order. |
| `timestamp` | `datetime` | When it happened. |
| `source` | `str` | Which part of the system emitted it. |
| `traceparent` · `tracestate` | `str | None` | W3C trace context, for stitching these into your own tracing. |

## Started

A url4 operation began executing. It adds one field:

| Name | Type | Meaning |
| --- | --- | --- |
| `url4` | `str` | The expression that is about to run. |

## Span

One OpenTelemetry span with portable GenAI attributes. This is the event that says what a model call cost in time and tokens.

| Name | Type | Meaning |
| --- | --- | --- |
| `name` · `operation` | `str` | What the span covers, and which operation it belongs to. |
| `start` · `end` | `datetime | None` | When it opened and closed. Both unset while it is still open. |
| `status` · `span_kind` | `str` | How it finished, and what sort of span it is. |
| `provider` | `str | None` | Which provider served the call. |
| `request_model` · `response_model` | `str | None` | What was asked for and what answered. They differ when a provider silently substitutes. |
| `input_tokens` · `output_tokens` | `int | None` | Token counts for this call alone. |
| `finish_reasons` | `tuple[str, ...]` | Why generation stopped. |
| `refusal` | `str | None` | Set when the model declined to answer. |
| `cache_status` · `cache_reason` | `str | None` | How the request cache treated the call: `hit`, `miss` or `bypass`, and why when the call was bypassed, for example `opted_out`. `None` on a span that is not a model call. |
| `cache_saved_cost_usd` · `cache_saved_cost_archive_usd` | `Decimal | None` | What a cache hit saved: the provider-reported cost of the call that filled the entry, and a measured amount from another call of the same model. `None` when none was observed. |

## Log

One log record from the run.

| Name | Type | Meaning |
| --- | --- | --- |
| `body` | `str` | The message. |
| `severity_text` | `str` | The level as a name. |
| `severity_number` | `int` | The same level as a number, which is what you compare against. |

## Usage

Note: Two distinct types are called Usage. This one is the event. [sf.Usage](sf-client-api-usage.md) is the accounting value, and it is what this event's own `usage` field holds.

Cost and token accounting, reported as the run spends rather than at the end.

| Name | Type | Meaning |
| --- | --- | --- |
| `usage` | `Usage` | The accounting value itself, with the same fields as [report.usage](sf-client-api-usage.md). |
| `scope` | `str` | `self` for this operation alone, or `subtree` for it and everything beneath it. Summing both double-counts. |
| `provider` · `model` | `str` | Who was billed and for which model. |
| `pricing_version` | `str` | Which price list produced the cost. |

```python
def observe(event: sf.Event) -> None:
    if isinstance(event, sf.events.Usage):
        print(event.model, event.usage.output_tokens, event.usage.cost_usd)
```

## Terminated

The run reached its terminal state. This is the last event.

| Name | Type | Meaning |
| --- | --- | --- |
| `status` | `str` | One of `succeeded`, `failed`, `stopped` or `timed_out`. |
| `error` | `TerminationError | None` | Why it failed, when it did. |

## TerminationError

The structured failure a `Terminated` event carries. It is a plain value, not an exception, and not something you raise or catch.

| Name | Type | Meaning |
| --- | --- | --- |
| `code` | `str` | Stable identifier to match on. |
| `message` | `str` | What went wrong. |
| `permanent` | `bool` | Whether retrying is pointless. |
