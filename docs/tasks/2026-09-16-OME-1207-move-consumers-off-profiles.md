---
id: OME-1207
linear_url: https://linear.app/openmined/issue/OME-1207/aigateway-move-remaining-consumers-off-direct-profiles-dependencies
status: in_progress   # committed locally; PR not opened
type: task
priority: high
labels: [aigateway]
parent: OME-1138
created: 2026-09-16
closed:
---

# AIGateway: move remaining consumers off direct Profiles dependencies

Stage A2 of `OME-1138`. A1 (`OME-1200`/`OME-1204`) introduced `core/provider_access/` — the port, the
Profile-backed implementation and the one HTTP refusal table — but left every route call site behind
two re-export shims. This unit moves the four in-process consumers onto the port itself, so the
backing swap at Stage B (D11) changes no route: chat credential resolution (`routes/chat.py`), model
parameters / datasheet defaults and the auth-mode path (`routes/model_parameters.py`), model
admission (`routes/model_admission.py`), dispatch-failure marking (`routes/chat_dispatch.py`).

D20 vocabulary binds: `Connection` is the final resource noun, `provider access` the boundary,
`legacy Profile` the compatibility surface. `Provider Account` is not introduced.

Ledger: `docs/work/2026-09-16-OME-1207-move-consumers-off-profiles.md`.
Spec: `docs/spec/2026-09-09-OME-1138-converge-connections.md` §3.4.
Plan: `docs/plan/2026-09-09-OME-1138-converge-connections.md` A2 (U2).

- 2026-09-16: implementation complete. Four consumers migrated; `_context_identity` and
  `_contract_auth_mode` deleted in favour of the port's `context_stamp` and `contract_auth_mode`;
  `ResolvePolicy.DATASHEET` replaces the call-site `missing_target_ok` predicate; admission reads the
  typed refusals instead of re-reading HTTP detail codes. New import-boundary test (7 cases) RED→GREEN.
  Focused changed-seam tests 100 passed; full suite 4463 passed / 58 skipped, coverage 92.69 %;
  OpenAPI byte-identical to `0c0abfcf`; ruff, ruff format, pyright, `check_no_enterprise.py` and
  pytest+coverage green.
- 2026-09-17: **the append-only gate is RED and stays red** — five prior suites were re-expressed at
  the port seam instead of the two originally named, because A2 deletes `_context_identity` and
  `_contract_auth_mode` and three further suites depended on those seams. The owner accepted this
  Confidence-Gate deviation for OME-1207 only; it is an accepted deviation, NOT a clean gate pass.
  Committed on that basis; not pushed.
- Scope note: the Linear description also lists "provider availability/listing paths" and "admin
  route bodies". Both are Stage A3/A4 in the plan and are explicitly out of scope for this unit;
  `core/admin_schemas.py` keeps its `ProfileState` import because changing it would change OpenAPI.
