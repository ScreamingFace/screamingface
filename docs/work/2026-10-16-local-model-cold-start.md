---
ticket: OME-1499
stack: aigateway,screamingface-engine
status: done
started: 2026-10-16
finished: 2026-10-16
---

# local-model-cold-start — remove hidden listing prerequisites

## Intent

Make local and Ollama models routable from the first raw URL4 run and first model-details request,
without requiring an earlier model-list request. Preserve compatibility with OpenAI-compatible
servers that serialize an unused tool-call collection as `tool_calls: []`.

## Planned changes

- Reuse Engine's caller-scoped `CachedCatalog` to refresh the process-local model snapshot before an
  in-process run and before local/ollama model-details membership is decided.
- Keep refresh failure scoped: scheduling still creates a run whose normal world resolution reports
  the unavailable/missing route rather than failing the control-plane request before a stream exists.
- Treat an empty `tool_calls` response list as equivalent to the field being absent while retaining
  strict validation for every non-empty tool call.
- Add unit regressions and remove the catalog-list call from the process-level E2E setup.

## Test plan

- RED: cold local model details succeeds without `catalog.fetch()` having run first.
- RED: an in-process schedule refreshes the overlay before rendering `URL4_CLOUD_EXTRA_MODELS`.
- RED: ordinary text with `tool_calls: []` crosses AIGateway unchanged.
- RED: process E2E evaluates local Fusion without first calling `client.models.list()`.
- Preserve malformed tool-call refusal, caller-scoped catalog caching, stale-on-error behavior,
  hosted isolation, and all prior gates.

## Acceptance

- Raw local URL4 evaluation and cold model details have no hidden listing prerequisite.
- Fresh catalog cache entries do not cause extra upstream requests; stale entries refresh through the
  existing cache policy.
- Empty tool-call collections are compatible; malformed non-empty collections remain sanitized 502.
- Full AIGateway and Engine gates plus the process-level local-provider E2E pass.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** updated AIGateway local response validation; added Engine catalog refresh wiring
  through `ExecutableCatalog`, `InProcessJobRunner`, and local composition; added cold details,
  pre-schedule refresh, vLLM empty-tool, and list-free process E2E regressions; updated the exact test
  transition approval.
- **Commits:** cold-start and vLLM compatibility fixes are included in this squashed commit.
- **Gates:** AIGateway, screamingface-engine, and screamingface stacks all report
  `ALL GATES GREEN`; process-level local-provider E2E passed `2 passed` without `models.list()`.
- **Deviations:** refresh executes inside an already registered run lifecycle, after capacity/topic
  reservation but before env rendering. Expected refresh failure keeps the prior snapshot and logs a
  count-free warning; missing routes still terminate through the run stream. Runners without local
  refresh retain their prior eager env/factory timing. No persistence, schema, migration, or
  dependency changes.
