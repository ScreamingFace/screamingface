---
ticket: OME-556
stack: url4-cloud
status: done
started: 2026-07-22
finished: 2026-07-22
---

# OME-556 — Dedicated capability token header `URL4-Capability`

## Intent

Move the per-run capability JWT off `Authorization: Bearer` onto a dedicated **`URL4-Capability`**
request header (bare JWT value), decoupling the per-run capability from primary caller identity so
an API gateway / service mesh / client SDK that owns `Authorization` cannot strip or overwrite it.
Owner-decided name (Q2, 2026-07-22). RFC 6648-clean (no `X-`); RFC 9449 DPoP-style secondary
credential. WS keeps the `?ticket=` query param (browsers can't set WS request headers). Drop the
now-vestigial `WWW-Authenticate: Bearer`. Add an OpenAPI apiKey security scheme so Scalar renders
the header input.

## Planned changes

- `src/url4_cloud/auth/dependencies.py` — read the bare JWT from `URL4-Capability`; drop the
  `Bearer ` prefix parsing and the `WWW-Authenticate: Bearer` 401 header; update docstrings.
- `src/url4_cloud/auth/__init__.py`, `auth/errors.py` — docstring wording (capability, not Bearer).
- `src/url4_cloud/schemas/openapi.py` — add `components.securitySchemes.URL4Capability`
  (`apiKey`/`header`/`URL4-Capability`) and attach `security` to `GET /` + `DELETE /`.
- `src/url4_cloud/ws/endpoint.py` — docstring wording (WS keeps `?ticket=`).
- **AUTHORIZED test edits** (the ticket's contract change): `tests/unit/test_auth.py`,
  `tests/unit/test_rest.py`, `tests/unit/test_ws.py`, `tests/integration/test_e2e_compose_flow.py`
  — send `URL4-Capability` instead of `Authorization: Bearer`; drop the `WWW-Authenticate` assert.
- **NEW tests (append):** `test_auth.py` — a valid token on `Authorization: Bearer` is now rejected
  (401), proving the decoupling; `tests/unit/test_docs_ops.py` — the OpenAPI declares the
  `URL4Capability` apiKey scheme and the execution ops reference it.
- `apps/url4-cloud/docs/protocol.md §7` + `docs/spec/2026-07-21-url4-cloud.md` — document the header.

## Test plan

- **RED:** the auth/rest/ws/e2e tests, switched to `URL4-Capability`, fail against the
  `Authorization`-only source; the new "reject `Authorization: Bearer`" test fails (currently
  accepted); the new security-scheme test fails (no scheme yet).
- **GREEN:** the dependency reads `URL4-Capability`; the customizer declares the scheme → all pass.
- **Coverage:** present / missing / invalid / tampered capability; `Authorization: Bearer` ignored;
  security scheme present + attached to `GET /`,`DELETE /`.

## Acceptance

REST auth reads `URL4-Capability`; `401` problem+json on missing/invalid/expired; the OpenAPI apiKey
scheme is present and attached to the execution ops; `docs/protocol.md §7` + spec updated;
`run_gates.py url4-cloud --skip-append-only` GREEN.

> **Append-only note (rule 5):** the test modifications are the *authorized* contract change for
> this ticket — the owner picked the header name (Q2, 2026-07-22). Not a silent weakening; verified
> with `--skip-append-only` and recorded here.

## Outcome

- **Actual files (src):** `auth/dependencies.py` (`_extract_capability` reads `URL4-Capability`,
  bare JWT; dropped the `Bearer ` prefix + `WWW-Authenticate: Bearer`) · `auth/__init__.py`,
  `auth/errors.py` (docstrings) · `schemas/openapi.py` (adds `URL4Capability` apiKey securityScheme
  + `security` on `GET /` and `DELETE /`) · `ws/endpoint.py` (docstring).
- **Actual files (tests):** `test_auth.py` (renamed `*_bearer`→`*_capability`, `URL4-Capability`
  headers, dropped the `WWW-Authenticate` assert, NEW `test_dependency_ignores_authorization_bearer_header`)
  · `test_rest.py` (`_bearer`→`_cap`) · `test_ws.py` (1 REST-auth header) ·
  `test_e2e_compose_flow.py` (`bearer`→`cap`) · `test_docs_ops.py` (NEW security-scheme test).
- **Actual files (docs):** `apps/url4-cloud/docs/protocol.md §7` (capability-carrier row + note) ·
  `docs/spec/2026-07-21-url4-cloud.md` (`GET /` auth line).
- **Commits:** see the OME-556 commit on `OME-513-url4-cloud`.
- **Gates:** `run_gates.py url4-cloud --skip-append-only` **GREEN** — ruff check · ruff format ·
  pyright · pytest cov ≥ 80 (unit 117 pass). Append-only skipped: the test edits are the
  authorized contract change for this ticket (owner-decided header name, Q2 2026-07-22).
- **Deviations:** the ticket said "update the OpenAPI security scheme" but there was **none** —
  this ADDS the first `securityScheme` (apiKey `URL4-Capability`), a net improvement (REST auth
  was previously undocumented in OpenAPI). Integration `test_e2e_compose_flow.py` edited but it is
  OWNER-RUN (needs Docker), not in the headless gate.

## Closure justification (OME-1215, round 2)

This ledger's `status:` was `in_progress` with the unit's work already merged, while the
`docs/tasks/` mirror said `done` — the mirror was the correct side. `OME-1215` closed the
ledger, which is an edit to an audit record, so the owner required the closure to be
justified with evidence rather than asserted.

EVIDENCE, verifiable from this repo: the unit's work is on `origin/main` as `79f6e9dc`
(`feat(url4-cloud): dedicated URL4-Capability header, decoupled from Authorization`), authored 2026-07-22. `finished: 2026-07-22` is that commit's author date — read
from git, not reconstructed.

WHAT IS *NOT* CLAIMED: nothing about why the ledger was left open, and nothing about the
ticket's Linear state. Only that the work in this ledger reached `main` on the date given.
