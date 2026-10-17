---
ticket: OME-1499
status: implemented
date: 2026-10-16
provenance: retrospective reconstruction after implementation
---

# OME-1499 — local models in Fusion benchmarks

This specification was reconstructed after implementation from the accepted issue scope, landed
behavior, tests, and review findings. It documents the resulting contract; it did not precede code.

## Problem

Researchers need models served by LM Studio, vLLM, SGLang, llama.cpp, and Ollama to appear in the
local Engine catalog and execute as Fusion members and synthesizers without API credentials or a
hosted worker that cannot reach researcher loopback.

## System boundary

- AIGateway owns provider discovery, request projection, loopback transport, and sanitized errors.
- Engine owns executable catalog projection, URL4 route encoding, run-world construction, and
  benchmark execution.
- The SDK owns candidate planning and submission, not local-provider admission.
- Local models execute only in the in-process local Engine. Hosted/queue workers remain closed.

## Invariants

- Local upstream addresses are operator-owned numeric loopback HTTP URLs ending in `/v1`.
- Callers cannot override endpoint, authentication, headers, retries, proxy policy, or redirects.
- AIGateway stores raw model IDs; Engine alone maps `:` to `~` at the URL4 route boundary.
- Listing changes visibility, never AIGateway dispatchability.
- Engine refreshes its local snapshot through its existing caller-scoped catalog cache before a cold
  local run or local model-details lookup.
- Catalog refresh errors never replace the last healthy local snapshot.
- Local dynamic routes do not claim unsupported web-search/tools capability.
- Provider error bodies never cross the gateway boundary; retryable status and a bounded Retry-After
  may cross as sanitized control data.
- Completion response parsing is bounded by bytes, depth, node count, finite numbers, and strict
  OpenAI-compatible message/tool-call shapes.

## Public behavior

- `GET /v1/models` lists routeable `local/*` and `ollama/*` rows.
- A raw URL4 evaluation can use a local route on the first run without priming `models.list()`.
- Cold `models.get()` refreshes visibility before deciding `ModelNotInstalled`.
- Older vLLM responses containing `tool_calls: []` are accepted as ordinary text completions.
- Fusion benchmarks run three local members plus a local synthesizer through the same Engine and
  benchmark contracts as remote providers.

## Out of scope

- Local-provider streaming, caller-selected endpoints, remote local-model servers, and hosted worker
  access to researcher loopback.
- Persisting local model snapshots or introducing a second cache/background refresher.
- Provider-specific generation controls beyond the proven common contract.
