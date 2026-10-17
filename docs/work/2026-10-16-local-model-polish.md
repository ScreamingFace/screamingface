---
ticket: OME-1499
stack: aigateway,screamingface-engine
status: done
started: 2026-10-16
finished: 2026-10-16
---

# local-model-polish — close nonblocking review findings before PR

## Intent

Polish the OME-1499 local-model path before PR by forwarding generator cleanup, making dynamic route
capabilities honest, preserving retryable upstream status, improving local-overlay diagnostics, and
turning the opt-in live harness into a strict named-model check.

## Planned changes

- Close the inner executor generator when `_PreparedExecutor` is closed early.
- Create dynamic local/ollama `ModelSpec` values with `web_search=False`.
- Map upstream non-2xx status and a validated Retry-After into sanitized Gateway errors.
- Warn without logging the address when a local Engine disables overlay for a nonnumeric Gateway.
- Require `AIGW_LIVE_LOCAL_MODEL` and fail explicit live prerequisites instead of skipping them.
- Correct the provider ledger proxy wording and add the missing spec/plan/task artifact trail.
- Move live-harness selection checks into the ordinary unit suite.
- Define the local/Ollama provider set once in the shared model registry.
- Mark the spec/plan as retrospective and make the task mirror match Linear's actual empty labels.

## Test plan

- RED: early close reaches the inner executor generator's `finally` immediately.
- RED: local/ollama extra models disable web search while other dynamic providers retain defaults.
- RED: 429/503 remain retryable statuses, 400 remains a sanitized 400, and bodies never leak.
- RED: nonnumeric Gateway emits one safe diagnostic; numeric loopback remains silent.
- RED: enabled live mode fails missing prerequisites and selects only the explicit model.
- Preserve all existing local-provider, Engine overlay, Fusion, and process E2E tests.

## Acceptance

- No HTTP client/world cleanup waits for async-generator garbage collection.
- Engine never sends unadvertised tools to local or Ollama dynamic routes.
- Retry policy can observe upstream overload statuses without exposing upstream response bodies.
- Misconfigured local overlay and live smoke prerequisites are actionable.
- Full affected gates and independent final review are green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** updated prepared-executor cleanup, dynamic model capability projection, local
  provider status mapping, local overlay diagnostics, strict named-model live harness, exact test
  approvals, provider ledger wording, and the OME-1499 spec/plan/task trail. Moved pure live-model
  selection checks into the unit suite, centralized the local/Ollama provider set, marked spec/plan
  retrospective, and made the task mirror reflect Linear's actual empty labels.
- **Commits:** pre-PR polishing is included in this squashed commit.
- **Gates:** repo, AIGateway, screamingface-engine, and screamingface report `ALL GATES GREEN`;
  process-level local-provider E2E passed `2 passed` on the rebased branch. Strict LM Studio smoke
  passed `1 passed` in 6.04 s
  against LM Studio 0.4.24+1 and `llama-3.2-3b-instruct` (context 32768, parallel 1). Ollama smoke
  passed `1 passed` in 8.68 s against Ollama 0.40.5 and `llama3.2:3b`.
- **Deviations:** Ollama 0.40.5 and `llama3.2:3b` were provisioned on the remote macOS runtime and
  remain available for future checks. Both temporary services were stopped; LM Studio models were
  unloaded. Upstream bodies and arbitrary headers remain hidden; only
  selected status codes and numeric Retry-After cross the provider boundary. No repository schema,
  migration, dependency, or lockfile changes. The spec and plan are explicitly marked as retrospective;
  Linear labels were not invented or changed, and the mirror records the empty current label set.
