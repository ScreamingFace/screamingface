---
ticket: OME-2050
stack: screamingface-engine
status: done
started: 2026-11-27
finished: 2026-11-27
---

# engine-capability-discovery — dormant Engine capability discovery (C12, Unit 6)

## Intent

Serve `GET /v1/capabilities` on the Engine App, the C12 capability gate's reader endpoint
(`docs/spec/2026-11-16-router-recipe-extension/contracts.md`, C12). The release is dormant: it
always answers the closed `engine-capabilities-v1` document with an empty `capabilities` list.
Its one setting, `Settings.advertised_capabilities` (`URL4_CLOUD_ADVERTISED_CAPABILITIES`, a JSON
string array, default `[]`), accepts only the empty set. Any other value refuses startup, including
`router-v1`, because no ID's fleet readiness has been proved. An SDK reader that later requires
an ID will therefore find none until a later release can advertise it.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/rest/capabilities.py` (new): the route and
  its closed body, `Cache-Control: private, no-store`, no validator and no 304.
- `apps/screamingface-engine/src/screamingface_engine/config.py`: the `advertised_capabilities`
  field and its validator.
- `apps/screamingface-engine/src/screamingface_engine/rest/__init__.py`: export the router.
- `apps/screamingface-engine/src/screamingface_engine/app.py`: one more entry in `_ROUTERS`.
- `apps/screamingface-engine/tests/unit/test_rest_capabilities.py` (new): route, configuration,
  and route-collision cases.

No serving, chart, CI, database, Gateway, SDK, worker or lock change. The existing route-collision
guard (`world/serving.py`) already sees every route `create_app` registers.

## Test plan

Each case is written first and must fail first, at the real App boundary:

- **Default and explicit `[]`:** the response is 200 with the exact closed body, in exact bytes,
  and `Cache-Control: private, no-store`. No ETag is sent; `If-None-Match` and
  `If-Modified-Since` still get 200. One registered path. No run token is needed, and no token
  mint, scheduling or Gateway call happens.
- **Refused configuration:**
  - malformed JSON;
  - a non-array value (object, string, number, null);
  - an element that is not a string;
  - an empty or blank ID;
  - a duplicate;
  - an unknown ID;
  - `router-v1` and each later Router ID.

  Each refuses `Settings`, and so startup.
- **Collision:** a world that declares a `/v1/capabilities` mount fails startup through the
  existing guard, fed the real `create_app` routes. The mount is an aigateway model route over a
  synthetic registry entry, because the world already refuses a `[data]` key under the `/v1`
  eval path on its own. A world mounted elsewhere still starts, and discovery still answers.
- **Exposure:** the local App exposes the route through the same composition.
- **Unchanged:** `/v1/operators` keeps its body and its conditional-read policy. The existing
  operators, mount-guard and CI path-filter tests are rerun unchanged.

## Acceptance

- Default and explicit `[]` return the exact 200 body with `private, no-store`, without a token.
- A validator never produces a 304.
- Every malformed or nonempty capability configuration refuses startup.
- A shadowing world mount refuses startup through the existing guard.
- The operators route is unchanged.
- Discovery has no I/O side effects.
- Only the five planned paths change, besides this ledger. New files are at most 450 lines.
- Engine gates are green on Python 3.13 and 3.12, and the repo gates are green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
  - `rest/capabilities.py`: new, 46 lines.
  - `config.py`: +37/-2.
  - `rest/__init__.py`: +2.
  - `app.py`: +2.
  - `test_rest_capabilities.py`: new, 277 lines, 40 cases.
  - No prior test changed.
- **Commit:** one, `1b7b42d08` on `OME-2050-engine-capability-discovery`, holding the
  implementation, this ledger and the task mirror, on base `61c83cbcb`.
  [PR #2092](https://github.com/ScreamingFace/screamingface/pull/2092) (head `1b7b42d08` on
  `61c83cbcb`) was squash-merged on 2026-11-27 as `727a7645d`. At that head 23 CI checks passed
  and 4 jobs were skipped (`plan`, `images`, `finish`, `engine`).
- **RED:** 39 of the 40 new cases failed before the change:
  - 404 for the route;
  - no refusal for any of the 25 refused values;
  - no collision at startup;
  - an unknown-field refusal instead of the release rule.

  The case that passed guards the existing operators route.
- **Mutation controls:** 11 of 11 killed, each restored byte-exact.
  - Route: no `Cache-Control`, a cacheable `Cache-Control`, an ETag sent, IDs in configured order,
    the setting ignored, an extra key.
  - Setting: the release rule removed, `router-v1` allowed, `NoDecode` dropped, the env text not
    decoded.
  - Composition: the route left out of the App's routers.
- **Gates:**
  - Engine on 3.13: `run_gates.py screamingface-engine` ALL GATES GREEN.
  - Engine on 3.12: ruff, format, pyright and layering 0; pytest 13234 passed, coverage 96.55%,
    `rest/capabilities.py` 100%.
  - Repo: `run_gates.py repo` ALL GATES GREEN; `git diff --check` clean.
- **Deviations:**
  - **`null` refused.** The env source turned a configured JSON `null` into the default `[]`
    without the validator seeing it. The field is therefore `NoDecode`, and a before-validator
    decodes the text, so `null`, empty and malformed text are refused like any other value
    that is not a JSON array.
  - **Collision mount.** The probe mounts an aigateway model route, not a `[data]` key; see the
    test plan.
  - **Lexical order.** The ordering rule is pinned through `Settings.model_construct`, because
    this release refuses every ID at startup.
  - **Oversized files.** `config.py` (700 lines) and `app.py` (1049) were already over 450 lines
    at base. They gain one field with its validators, and one router entry, inside their existing
    responsibilities.
