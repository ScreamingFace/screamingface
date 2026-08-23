---
title: Relative URL4 route span names
ticket: OME-950
status: approved
date: 2026-08-23
---

# Relative URL4 route span names

## Outcome

A relative URL4 operation reports its static route template in `NodeStarted.detail`. The existing
Engine observation adapter consequently publishes that route as `SpanData.name` when the node
finishes. A consumer can identify terminal route executions from the ordinary span stream without
a new event kind or a domain-specific URL4 capability.

## Contract

For a `RelUrlNode` authored with path `/benchmarks/case-execution`, observation emits:

```text
NodeStarted(
    node_kind="RelUrlNode",
    detail="/benchmarks/case-execution",
)
```

The existing start/finish bijection and Engine folding then produce one finished span carrying
that name and its existing `ok` or `error` status.

`detail` reports the node's static `path` attribute before URL4 resolves bindings. It never reports
the resolved context, intent, query, collection row, endpoint result, prompt, answer, or other
runtime payload.

## Design

Extend the existing best-effort detail selector from `target`, `text`, and `body` to also consider
`path`. Keep the current priority and behavior of every existing source. This is a generic DAG
observation improvement: URL4 has no knowledge of Benchmarks or the consumer interpreting a
particular route.

## Boundaries

- No grammar, parser, AST, renderer, generated URL4, execution graph, result, cache, cost, retry,
  or scheduling change.
- No new observation dataclass, CloudEvent kind, schema field, queue, or transport.
- No Engine or Client production change.
- No resolved path or dynamic payload is added to telemetry.
- No compatibility fallback before V1.

## Acceptance

1. A successful `RelUrlNode` start observation carries its static path as detail.
2. An erroring `RelUrlNode` retains the same path detail and the existing matching finish event.
3. Existing `target`, `text`, and `body` detail sources remain unchanged.
4. The full `url4` quality gate passes.
