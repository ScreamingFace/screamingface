---
ticket: OME-1499
stack: aigateway
status: done
started: 2026-10-14
finished: 2026-10-15
---

# local-model-provider — expose loopback OpenAI-compatible models through AIGateway

## Intent

Add a no-auth, numeric-loopback-only `local` provider so researchers can expose models served by
LM Studio, vLLM, SGLang, or llama.cpp server through AIGateway without Profiles, Connections, or
caller-controlled endpoint routing. This is the provider half of OME-1499; Engine execution follows
as a separate stack iteration after this contract is green.

## Planned changes

- Create `apps/aigateway/src/aigateway/plugins/local_provider/` with focused settings, identity,
  discovery, parameter, and dispatch modules plus module-level `PLUGIN` registration.
- Extend the injected discovery HTTP transport to ignore environment proxies.
- Resolve providers whose only auth mode is `none` without reading legacy credential stores.
- Add unit and route tests under `apps/aigateway/tests/unit/local_provider/` plus shared no-auth
  regressions for Ollama.
- Add an opt-in strict local-provider live test without invoking it in ordinary gates.

## Test plan

- RED: disabled provider performs no egress and contributes no models.
- RED: bounded `/v1/models` discovery publishes raw `local/<id>` rows; failures raise sanitized
  discovery outcomes while valid empty responses are authoritative.
- RED: numeric-loopback URL validation rejects hostnames, remote addresses, credentials, query,
  fragment, and unexpected paths without falling back.
- RED: dispatch restores the exact discovered upstream model id and strips endpoint/auth/client/retry
  controls; captured wire request contains no auth and never uses environment proxies or redirects.
- RED: invalid, duplicate, colliding, or literal-tilde ids are refused deterministically.
- RED: no-auth-only local and Ollama resolution bypasses ProfileIndex, Connection, and credential
  blob reads even when shadow rows exist.
- RED: parameter, tool, streaming, and global-cache declarations fail closed until proven.
- Preserve all existing provider, Ollama, credential, route, and discovery tests.

## Acceptance

- `GET /v1/models` exposes healthy configured local models as raw `local/<upstream-id>` entries.
- Non-streaming chat reaches only the configured numeric-loopback endpoint with the exact upstream
  model id and no authorization material.
- Disabled, invalid, unavailable, and malformed configurations fail safely with sanitized output.
- Existing Ollama direct-chat behavior remains green and no-auth providers cannot be shadowed by
  legacy credential rows.
- Full AIGateway gates pass with no persistence or dependency changes.

## Follow-up review findings — 2026-10-15

- Remove the plugin-local 30-second wall-clock/read timeout. The shared admission layer remains the
  single execution deadline, bounded by `AIGW_PROVIDER_EXECUTION_TIMEOUT_S` and the Engine header.
- Preserve valid OpenAI-compatible choices whose `content` is null/empty while reasoning or tool-call
  evidence exists; Engine owns the final model-outcome classification.
- Treat syntactically valid but URL4-unrouteable upstream identifiers as skipped catalog rows rather
  than dropping every healthy local model, and report only the skipped count.
- Replace the three bounded-JSON tree walkers with one provider-neutral core utility.
- Record the intentional contract: live listing controls visibility only; any structurally valid
  `local/<id>` remains dispatchable at the fixed operator-owned loopback endpoint.

### Follow-up test plan

- Assert the HTTPX request carries no independent phase timeout; admission remains authoritative.
- Assert null/empty content, reasoning-only, and tool-call choices cross AIGateway unchanged, while a
  truly malformed message still returns a sanitized 502.
- Assert one unsupported model id is skipped without hiding valid rows, with a count-only warning.
- Preserve all existing discovery safety, disabled-provider zero-egress, JSON bounds, and live tests.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** added `plugins/local_provider/{__init__,settings,discovery,parameters,plugin}.py`,
  `transport.py`, shared `core/json_bounds.py`, local-provider unit/route/live tests, no-auth
  provider-access and proxy-transport regressions, and one byte-exact test-change approval; updated
  provider access and discovery transport without persistence changes.
- **Commits:** provider, live validation, and review hardening are included in this squashed commit.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway` → `ALL GATES GREEN` (append-only,
  Ruff, format, Pyright, no-enterprise, full pytest + coverage). Strict live smoke passed against
  LM Studio `llama-3.2-3b-instruct` on a remote macOS runtime, context 32768 and parallel 1; it was
  repeated after final polishing (`1 passed` in 6.04 s). A real Ollama 0.40.5
  round trip with `llama3.2:3b` also passed (`1 passed` in 8.68 s). Both temporary services were stopped
  and the LM Studio model was unloaded afterwards.
- **Deviations:** the provider uses direct HTTPX rather than OpenAI SDK; shared discovery transport
  sets `trust_env=False` only for numeric loopback and preserves environment proxy behavior for
  remote sources; no-auth-only providers bypass legacy credential and authority reads.
  Completion responses are streamed under a byte cap and shape-checked. The owner explicitly
  approved adding `local` to the closed dynamic model-less provider census. Review hardening removes
  listing-dependent dispatch, blocks disabled-provider egress, and refuses non-finite/over-complex
  upstream JSON. The follow-up removes the accidental 30-second HTTPX deadline, preserves legitimate
  contentless reasoning/tool responses, skips only URL4-unrouteable catalog rows with count-only
  logging, and centralizes JSON bounds. The full AIGateway gate remained green after the final rebase
  onto `8edd994bf` on 2026-10-16.
