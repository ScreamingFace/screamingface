---
ticket: unfiled (bug, filed at PR-open)
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-19
finished: 2026-10-19
---

# url4-replay-admission — a scheduled url4 admits the models it names

## Intent

Make a complete evaluation url4 that names a dynamically admitted model (for example
`openrouter/anthropic/claude-opus-5.5`, which is not in the gateway's static catalog) replay
with `sf.evaluate("<url4>")` without a manual admission step. Today every Case fails at
`/benchmarks/candidate` with "Answering failed" and the run makes 0 gateway calls (runner log
`runner world models=117`). One `GET /v1/model-parameters?model=…` on the Engine before the run
makes the identical replay work. The Recipe path works because the SDK probes and preflights
every candidate model before it runs.

## Root cause

Dynamic admission (OME-880) happens only as a side effect of the Engine's
`GET /v1/model-parameters` lookup. The run world is built from a snapshot of the admitted
overlay that the App takes at schedule time. Nothing on the scheduling path admits a model.

1. `ExecutableModelParameterSource.fetch_model_parameters` (`catalog/executable.py`) is the
   only caller of `_admit_and_fetch`. That calls gateway `POST /v1/models/admit`, adds the id
   to the in-memory `AdmittedModels` overlay (`catalog/admission.py`) and fires `on_admitted`.
2. A run world gets dynamic models only through `URL4_CLOUD_EXTRA_MODELS`. The App copies
   `catalog.admitted_model_ids` into the run env when it schedules the run (`app.py` →
   `adapters/queue_runner.py` → `runner_queue.py` for worker pods; `adapters/inprocess.py`
   for local mode). The runner merges it into its world (`world/config.py`,
   `world/factory.py`, `runner/main.py`).
3. `start_run` → `_schedule` → `job_runner.schedule` (`rest/routes.py`) never looks at the
   models in the url4. `rest/mounts.py` uses the same `_schedule`.
4. So if nothing called `/v1/model-parameters` for the model since this Engine process
   started, the run gets no `EXTRA_MODELS`, the runner world has only the static catalog, and
   every `/openrouter/anthropic/claude-opus-5.5` call fails route resolution ("unknown
   processor") with 0 gateway calls.
5. The SDK's Recipe path probes (`runner.py` `load_models` / `load_model_details` /
   `preflight_*`), which triggers admission. The url4 replay path
   (`_evaluation/url4.py` `evaluate_url4_*`) makes no probe.

## Evidence

- SDK unit repro (temporary, removed): replaying a compiled
  `openrouter/anthropic/claude-opus-5.5` url4 records no Engine request before the run.
- Engine-side walker prototype on the published FrontierScience `lb.json` opus url4 finds 7
  routes; exactly one is dynamically admissible: `/openrouter/anthropic/claude-opus-5.5`.
- Live (shared kind cluster, $0 cached replay): fails with `runner world models=117` until one
  `GET /v1/model-parameters?model=openrouter/anthropic/claude-opus-5.5`; then all cache hits.
- `docs/work/2026-08-18-OME-880-engine-preflight-admission.md`: admission was put on the
  model-parameters miss only because "the engine has NO run-submission preflight". OME-878's
  intent is "the engine asks the gateway … and the run just works".
- An SDK-only fix is blocked: `packages/screamingface/tests/test_url4_replay_operator_check.py`
  pins that a url4 replay makes no catalog request (append-only tests).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/catalog/expression_models.py` (new):
  `dynamic_model_ids(url4) -> tuple[str, ...]`, url4-parser walk (no regex). (Walk moved to
  `benchmarks/expression_routes.py`, gate to `rest/routes.py` — see Deviations.)
- `apps/screamingface-engine/src/screamingface_engine/catalog/admission.py`: the
  `RunModelAdmission` port.
- `apps/screamingface-engine/src/screamingface_engine/catalog/executable.py`:
  `ExecutableModelParameterSource.admit_run_models` (reuses the forward / heal / admit flow).
- `apps/screamingface-engine/src/screamingface_engine/rest/routes.py`: `_schedule` admits the
  named dynamic models before `job_runner.schedule` snapshots the overlay; skipped for
  frozen-copy replay (spec 02 §5.3 1a).
- tests: `apps/screamingface-engine/tests/unit/test_schedule_time_admission.py` (new).

## Test plan

- `dynamic_model_ids`: published-shape evaluation url4 → the opus id; declared, benchmark,
  `~`/`:` ids excluded; Iteration body, call context and corrective-member intent found;
  unparsable url4 → (); prose Text ignored.
- `admit_run_models`: grant joins the overlay and fires `on_admitted`; declared id → no
  upstream call; refusal / unsupported / `CatalogError` → no raise, overlay unchanged, warning;
  stale overlay member healed and re-admitted.
- REST `GET /?q=` with a recording job runner: `URL4_CLOUD_EXTRA_MODELS` source carries the id
  at schedule time (RED before the fix); frozen-copy replay → no admit call; gateway failure →
  run still scheduled; no dynamic model → zero upstream calls.

## Acceptance

- New tests RED before the fix and GREEN after; `run_gates.py screamingface-engine` green;
  no existing test edited.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `apps/screamingface-engine/src/screamingface_engine/benchmarks/expression_routes.py` (new):
    the ONE url4 route walker. `relative_route_paths(root, *, as_executed)` collects `RelExpr`
    and `RelUrl` literal paths through Iteration body/intent/reducer and local call contexts
    (`@` holdings contexts stay opaque); `as_executed=True` also reads text literals that hold
    an expression and reads an Iteration body as the source list the executor runs.
    `local_route_paths(url4)` is the best-effort string entry point.
  - `apps/screamingface-engine/src/screamingface_engine/benchmarks/registry.py`: the old
    `_relative_endpoint_paths` / `_embedded_protocols` / `_literal_path` copy moved into
    `expression_routes.py`; install validation calls it with `as_executed=False` (unchanged
    behaviour).
  - `apps/screamingface-engine/src/screamingface_engine/catalog/admission.py`: the
    `RunModelAdmission` port.
  - `apps/screamingface-engine/src/screamingface_engine/catalog/executable.py`:
    `ExecutableModelParameterSource.admit_run_models` (through `fetch_model_parameters`, so the
    F1 heal and `_admit_and_fetch` are reused; declared / local / non-admissible ids skipped;
    never raises, one warning per failed id, class name only). Accepted cost: a url4 that names
    an already-admitted model makes one gateway `GET /v1/model-parameters` call (the F1 heal
    check) on the scheduling critical path, even for an all-cache-hit run — note it in the PR
    body.
  - `apps/screamingface-engine/src/screamingface_engine/rest/routes.py`: `_Deps.model_admission`
    (resolved from `app.state.model_parameters` by isinstance), `_named_dynamic_models` (decode
    `~` + `is_dynamically_admissible` gate over the walk), `_admit_named_models`, called
    from `_schedule` before `job_runner.schedule`, skipped for a frozen-copy replay. No
    `create_app` parameter, no new status code.
  - tests (new): `tests/unit/test_schedule_time_admission.py` (walk + port, 31 cases),
    `tests/unit/test_schedule_time_admission_rest.py` (real `create_app` + real
    `QueueJobRunner` over a fake broker; asserts the queued run env), and the plain support
    module `tests/unit/schedule_admission_support.py` (the published opus url4, verbatim).
- **RED → GREEN:** with `src/` reverted and the new tests kept, the REST file fails 4 of 7 on
  behaviour (`URL4_CLOUD_EXTRA_MODELS` is `[]`, the gateway is never asked); the two guards
  (frozen copy, no dynamic model) and the mount guard pass both ways by design. The catalog
  file fails at import (`RunModelAdmission`, `dynamic_model_ids` absent; the helper is now
  `_named_dynamic_models`). Review round: against the first walker, the new data-reference and
  unparsable-intent cases fail (`()` instead of `('openrouter/a/b',)`). After the fix: all
  pass.
- **Commits:** one local commit on branch `url4-replay-admission`,
  `fix(screamingface-engine): admit the dynamic models a scheduled url4 names` (not pushed).
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main` →
  ALL GATES GREEN (re-run at finalize, 2026-10-19) (append-only, ruff, format, pyright, layering, pytest + coverage 95.6%).
- **Deviations:**
  - The url4 walk lives in `benchmarks/expression_routes.py`, not `catalog/`. The existing
    boundary test `test_url4_executor.py::test_only_engine_extensions_import_url4` confines
    url4-engine imports to Runner adapters and `benchmarks/`; widening its allowlist would edit
    an existing test. `benchmarks/registry.py::_relative_endpoint_paths` is the precedent (it
    walks a submitted protocol for its routes). `benchmarks` is a shared leaf, so it returns raw
    paths and `rest/routes.py::_named_dynamic_models` decodes and gates them.
  - Review round: the separate `catalog/expression_models.py` bridge was removed (it was the
    only `catalog` → `benchmarks` import), and the walker was merged with `registry.py`'s copy.
    The Iteration body and intent are now parsed separately, so an intent that does not parse no
    longer hides the body's model; bare `(/path)` data references now count too.
  - Mount (direct) runs go through the same `_schedule`, but their target is a mount path plus
    its raw percent-encoded query and runs no DAG, so the walk names nothing there. The mount
    test pins "unchanged, zero upstream calls" instead of admission.
  - No live replay: the shared kind cluster runs the old image and this stage may not rebuild
    or redeploy it. Proof is the unit tests (the REST test drives the published url4 through
    the real scheduling route and queue codec).
- **Follow-ups (not filed):**
  - Frozen-copy replay of a dynamically admitted model (`sf.reproduce`) still lacks the route
    in its run world: admission is skipped by design (spec 02 §5.3 1a). Owner decision: e.g.
    put the url4's shape-valid ids into the replay run's `EXTRA_MODELS` without an admit call.
  - The gateway's own admitted set is in-memory per gateway process; a gateway restart between
    schedule and the run's chat calls can still refuse (pre-existing, also the Recipe path).
  - A mount call that names an OpenRouter model in a handler parameter (not a DAG route) is not
    admitted by this change.
