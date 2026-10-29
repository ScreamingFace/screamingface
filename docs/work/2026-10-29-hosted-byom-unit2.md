---
ticket: OME-1770   # Engine; siblings OME-1771 (Gateway chart) and OME-1773 (SDK tests) land in the same PR
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-29
finished:
---

# hosted-byom-unit2 — hosted chat routes and config delivery for configured endpoints

## Intent

Third slice of hosted bring-your-own-model endpoints, on top of the merged Gateway slices Unit 0
(OME-1712) and Unit 1 (OME-1721, squash `559630247`). It makes configured endpoint chat models
runnable through the Engine: explicit routes in the world config, one private world config
delivered to the App and the runner pool, discovery and SDK preflight that tell each account the
truth, private routes kept out of the shared OpenAPI, and cold and warm runs that pick the
caller's Connection with no key in the queue. The Gateway chart gets opt-in delivery of the
endpoints file (OME-1771). Decisions come from the owner-held planning pack, kept local by the
owner's instruction (not copied into `docs/spec`/`docs/plan`). One PR for both issues, by the
owner's choice.

Process choice for this unit (owner, 2026-10-29): the issues were filed under epic OME-1306
before the branch was created, one per landing, instead of at PR-open. The general process is
unchanged. Branch `OME-1770-hosted-byom-unit2` from origin/main `f20c3e599`.

Out of scope: classification (Unit 3), the paid pilot (Unit 4), Router, UI, hot reload,
automatic publishing or provisioning, run-scoped credential envelopes, streaming, tools, media,
Taxonomy, a custom DNS or private-address guard, and local NATS.

## Planned changes

Fixed after reading the Engine discovery, preflight, config, worker and identity paths and both
charts on this base.

- `world/config.py`: `ModelSpec.public_schema` (default true, the existing behavior), parsed and
  type-checked like `web_search`. Nothing infers it from a provider prefix.
- `world/publication.py` (new): which declared routes are private, as route ids, mount paths and
  real Gateway ids; the deployment-review check that refuses a Gateway configured target the
  Engine declares with `public_schema` true or `web_search` true. It reads only `endpoints[].id`
  and `targets[].alias` from the Gateway file and never echoes the file.
- `world/serving.py`, `local.py`: `MountDescriptor.public_schema`, filled from the same parsed
  config the mounts come from.
- `rest/mounts.py`, `metrics.py`: a private mount stays registered and executable but is left out
  of `/openapi.json`, and both `/metrics` counters label it with one constant instead of its path.
- `catalog/`: for a private declared route, a Gateway "unknown" answer on details (400 or 404)
  becomes the Engine's own not-installed 404, the answer an undeclared id gets. Public routes keep
  their current error contract.
- `cli.py`: `admin check-publication --endpoints <file>` runs the review check.
- `packages/url4`: the `unknown processor` error stops listing every route the node declares; any
  caller could read that list in a run's terminal frame. Separate landing (`url4-engine`).
- `packages/screamingface/tests`: two accounts and a seeded run against a fake Engine; tests only,
  no SDK code change. Separate landing (`client-sf`) if it needs its own issue.
- `apps/aigateway/tests`: a remote endpoint refuses `seed` before any upstream call.
- Charts: the Engine world config (`worldConfig`) and the Gateway endpoints file
  (`remoteEndpoints`), as below.
- Operator logs and traces keep real model ids: they sit behind the operator boundary that already
  holds the private config. Shared, unauthenticated or caller-visible surfaces are the ones
  redacted.

## Test plan

- Engine discovery: a granted account with a usable Connection lists the model and passes details
  preflight; a grant without a key reads `missing`; an ungranted account gets the omitted or
  unknown answer. Two accounts, checked separately.
- Engine publication: the shared OpenAPI holds no private route ID or contract while existing
  public routes stay; reconciliation refuses a private target marked public; privacy is not
  inferred from a provider ID prefix.
- Engine execution: a cold and a warm run with no prior list call reach the Gateway with the
  caller's identity; no endpoint key in queue or worker payloads; no fallback to another account;
  the subsidized credential path is unchanged.
- Engine seed: a seedless run passes; an unsupported seed is refused before any upstream call.
- Charts: render with disabled, enabled and malformed values; source, mount, env and checksum
  parity on the App and runner pod templates and on the Gateway pod template.
- Prior tests stay unchanged (append-only); the Unit 1 credential guard and shutdown regressions
  stay green.

## Acceptance

- Deterministic checks with fake upstreams and queue and worker substitutes cover the scope;
  gates are green for every touched stack.
- Helm renders as above. A render is desired state, not live convergence.
- **Pending, not blocking development:** one mixed Fusion, a configured endpoint model plus an
  existing subsidized provider, through the queue, a cold or warm worker and the Gateway to fake
  upstreams, with no prior list call and one graded one-case result; each credential reaches only
  its own upstream. It needs an existing Linux environment with NATS/JetStream, not available on
  2026-10-29. Hosted readiness is not claimed until it passes, and OME-1770 stays open.
- A missing usage count shown as 0 is documented as not a measured zero.

## Outcome (fill at the end — required before COMMIT)

Development slice complete; the unit stays `in_progress` because the hosted mixed Fusion check is
pending (Acceptance). Hosted readiness is not claimed.

- **Actual files:**
  - Engine source: `world/config.py`, `world/publication.py` (new), `world/serving.py`,
    `world/connector.py` (the `_report_usage` docstring only), `local.py`, `metrics.py`,
    `rest/mounts.py`, `catalog/__init__.py`, `catalog/executable.py`, `cli.py`.
  - Engine tests (new): `test_route_publication.py`, `test_publication_review.py`,
    `test_endpoint_route_execution.py` (cold and warm runs, the queued message, and child
    inheritance: a cold child reads the runner pod's config path, a warm child builds the private
    route from that file), `test_chart_render_world_config.py`.
  - Engine chart: `values.yaml`, `values.schema.json`, `templates/_helpers.tpl`,
    `templates/deployment.yaml`, `templates/deployment-runner.yaml`, `README.md`.
  - Gateway chart (OME-1771): `values.yaml`, `templates/_helpers.tpl`,
    `templates/deployment.yaml`, `README.md`; test `tests/unit/test_chart_render_remote_endpoints.py`
    (new).
  - Gateway tests (appended): `remote_endpoint/test_app_catalog.py` (access reads `missing` until
    that account's key is attached; the contract has no seed row),
    `remote_endpoint/test_request_contract.py` (a seed is refused before any key read or upstream
    call).
  - SDK test (new): `packages/screamingface/tests/test_hosted_byom_preflight.py` (each account's
    view settles preflight before dispatch, plain Model and mixed Fusion, seeded run refused).
- **Commits:** none. Staging, commit and push were not authorized for this slice.
- **Gates (2026-10-29, this worktree):**
  - `run_gates.py screamingface-engine`: all green (ruff, format, pyright, layering, pytest with
    coverage floor 80). The same suite without coverage: 5919 passed, 153 skipped.
  - `run_gates.py aigateway`: all green (ruff, format, pyright, no-enterprise check, pytest with
    coverage floor 80).
  - `run_gates.py screamingface`: all green (ruff, format, pyright, pytest with coverage floor 95,
    notebooks, build, distribution check), after `uv sync --extra notebook` as CI does.
  - Chart checks: render tests above, `helm lint` on both charts, `verify_chart_wiring.py`.
- **Deviations:**
  - The planned `packages/url4` change was dropped. A deployed Engine always sets the run's
    processor to the route path `/<default_model>`, and a probe of an in-process `/v1` call carrying
    `processor=<id>` dispatched no reduce, so no caller reaches the route listing in
    `_route_for_id`. Residual: if a later change lets a caller choose a processor id, that error
    would list private routes; the fix then drops the enumeration in `_route_for_id`, which one
    prior url4 spec test pins (`test_unknown_id_raises_and_names_the_declared_routes`). No
    `url4-engine` landing.
  - Engine execution needed no code change: the cold and warm tests passed on first run and stay as
    characterization tests. The SDK and Gateway changes are tests only, so no `client-sf` issue is
    needed unless the owner wants the SDK test filed separately. The owner chose a separate leaf:
    OME-1773 (`client-sf`), filed at PR-open under OME-1306.
  - The catalog builder parses the world config a second time at startup to read the private set.
  - Both chart READMEs gained a section. They are Markdown outside `docs/` and need owner approval
    before they are committed.
  - The first Engine gate run hung with idle workers while the Gateway gate ran beside it; the same
    gate run alone was green. Later the Engine venv had gained the `inspect` extra, which CI does
    not install, and pyright failed in untouched `tests/unit/inspect` files; `uv sync --dev`, as CI
    runs it, restored the lock and the gate was green again. No code change.
  - The SDK `provider_not_connected` hint names `sf.connect()` or a hosted provider profile. For a
    configured endpoint the key is attached through the Gateway admin route. Left unchanged here.
