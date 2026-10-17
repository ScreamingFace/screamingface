---
ticket: OME-1499
stack: screamingface-engine
status: done
started: 2026-10-14
finished: 2026-10-15
---

# local-model-engine-overlay — make local runtime models executable

## Intent

Project dynamic `local/*` and `ollama/*` rows from the configured loopback AIGateway into the local
Engine's executable catalog and in-process run world. Preserve the hosted closed world and existing
OpenRouter admission lifecycle while allowing URL4 to encode raw colon-bearing model ids safely.

## Planned changes

- Add a separate process-local replace-on-refresh model overlay in `catalog/`.
- Teach `ExecutableCatalog` to observe approved raw local-provider rows before declared-world
  projection and expose encoded route ids for local run injection.
- Enable the overlay only from local composition when the configured AIGateway origin is a numeric
  loopback address.
- Reuse the existing per-run extra-model environment path; do not add persistence or worker protocol.
- Add focused catalog, removal/stale, hosted-isolation, route-codec, and local-run injection tests.

## Test plan

- RED: raw `local/fixture:model` and `ollama/fixture:model` rows are filtered today.
- RED: local overlay lists them as `local/fixture~model` / `ollama/fixture~model` and exposes encoded
  run ids while retaining raw membership ids.
- RED: healthy replacement removes missing rows atomically; malformed rows never enter the overlay.
- RED: hosted composition and remote AIGateway origins never enable the overlay.
- RED: in-process local runs receive the encoded snapshot through existing `extra_models` plumbing.
- Preserve OpenRouter admission, catalog caching, ETag, queue codec, and world-config tests.

## Acceptance

- Local Engine lists and can route current AIGateway `local/*` and `ollama/*` rows.
- Colon-bearing raw ids are encoded exactly once by Engine and decoded before AIGateway dispatch.
- Only local in-process composition enables the overlay; hosted/remote configurations are unchanged.
- Full Engine gates pass without schema, migration, or new dependency changes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** added `catalog/local_models.py`, byte-preserving `catalog/json_projection.py`,
  shared numeric-loopback transport policy, focused overlay/proxy tests, and cross-app Fusion
  benchmark coverage; updated executable catalog/model-parameter projection, builder wiring, local
  composition, and loopback HTTP clients. No persistence or worker protocol files changed.
- **Commits:** Engine overlay and benchmark/detail-response fixes are included in this squashed commit.
- **Gates:** rebased `uv run .claude/scripts/run_gates.py screamingface-engine` →
  `ALL GATES GREEN` on 2026-10-15 (append-only, Ruff, format, Pyright, layering, full parallel pytest
  + coverage).
- **Deviations:** local execution is explicitly in-process only. Engine mirrors the catalog AIGateway
  serves after its own stale/fallback policy rather than maintaining a second independent stale cache.
  The overlay updates only on serialized real upstream refreshes, so caller cache hits cannot roll it
  back. The regression moved from removed IFEval to current MEDXPERT after rebase. Engine rewrites
  only the validated `model.id` JSON string token back to its encoded route form; malformed,
  ambiguous, over-complex, and every unrelated valid upstream byte remain unchanged.
