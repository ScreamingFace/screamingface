---
id: OME-1196
linear_url: https://linear.app/openmined/issue/OME-1196
status: Canceled
type: task
priority: medium
labels: [screamingface-engine, agentic, deferred]
created: 2026-09-14
closed: 2026-09-14
---

# Relay Gateway execution access through Engine model details

Coordinating epic OME-1194: Gateway OME-1195 → existing Engine passthrough → Client OME-1042. Planned Engine unit OME-1196 canceled: the existing proxy already preserves unknown fields and response bytes.

Gateway implements `context.execution_access` in existing model-details discovery. Existing Engine code relays the field unchanged; Client rejects missing access before any Candidate dispatch. Only Gateway implementation is underway. See `docs/spec/2026-09-14-OME-1195-gateway-access.md`.

Canceled before implementation: existing `catalog/aigateway.py` and `rest/catalog.py` preserve the response bytes; `tests/unit/test_model_parameters_proxy.py` asserts unchanged forwarding. No Engine change required.
