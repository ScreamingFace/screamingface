---
id: OME-735
linear_url: https://linear.app/openmined/issue/OME-735/repair-the-aigateway-dependency-group-pr-and-bump-the-pyjwt-pin
status: in_review
type: task
priority: P1
labels: [aigateway, autonomous, agentic]
created: 2026-08-04
closed:
---

# OME-735 — aigateway dependency upgrade + PyJWT pin bump

Sub-issue of `OME-733` (Dependabot compliance + alert burndown).

Takes the dependency upgrade Dependabot could not land on its own — its group PR for this app
had been red since 2026-07-28 — and bumps the one pinned package it can never propose.

## Result

**A real security gap, found by an existing test.** litellm 1.95 added four Datadog
dynamic-callback params (`dd_api_key`, `dd_agent_host`, `dd_agent_port`, `dd_site`) that the
gateway was **not** stripping from inbound chat bodies. `dd_api_key` is a caller-injectable
credential; the host/port/site fields redirect where prompt and response telemetry is shipped —
the same exfiltration category as the langfuse/arize/braintrust fields already in the strip
list. `test_litellm_dynamic_callback_parameter_set_is_covered` caught it, which is exactly what
that test exists for. Fixed in production code.

The gap opened the moment litellm shipped 1.95; only the upgrade revealed it. That is the
clearest argument in this epic for keeping bumps flowing rather than letting them queue.

**Two upstream API changes, both behaviour-preserving once adapted:**

- `AnthropicConfig._map_reasoning_effort` gained a required `custom_llm_provider`. It was
  *added*, not renamed — `llm_provider` still defaults to `"anthropic"` — so passing
  `"anthropic"` reproduces the previous call exactly.
- FastAPI 0.141 stopped flattening included routers into `app.routes`, storing lazy
  `_IncludedRouter` wrappers. Verified product behavior is unchanged: the route still serves
  200, `app.openapi()` still lists it, and no production code introspects `app.routes`.

**PyJWT 2.12.1 → 2.13.0** clears a high-severity alert that had **no Dependabot PR at all** —
the hard `==` pin left no in-range update for the bot to propose.

## Versions

litellm → 1.95.0 · fastapi → 0.141.1 · pyjwt → 2.13.0 · idna → 3.18 ·
pydantic-settings → 2.14.2 · pydantic → 2.13.4 · uvicorn → 0.52.1 · ruff → 0.16.1

## Gates

`run_gates.py aigateway` all green — 2645 passed, 40 skipped, coverage 92.36% (floor 80%).
Re-run on Python 3.12 as well, matching the CI matrix.

All three prior-test changes were stopped on and owner-approved under sdlc rule 5. The repo's
own append-only gate fired first and blocked the run — working as designed.

Ledger: `docs/work/2026-08-04-OME-735-aigateway-deps-pyjwt.md`
