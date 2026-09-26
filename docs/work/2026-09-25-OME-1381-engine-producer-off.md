---
ticket: OME-1381
stack: screamingface-engine
status: in_progress
started: 2026-09-25
finished:
---

# OME-1381-engine-producer-off — refuse X-Profile at Engine ingress and stop producing selector-bearing runs

## Intent

This is Stage D step 2 of `OME-1138`: Engine producer-off, under the D4 rollout decided in
`OME-1377`. Once this landing ships, the Engine no longer creates work that selects a credential
by label.

- **Refusal at ingress.** A nonblank `X-Profile` is refused with a value-free, non-retryable
  `400 x_profile_unsupported`. The refusal happens before any schedule, queue publication,
  catalog or gateway I/O, or connection mutation.
- **No selector on new work.** New schedule calls and queue messages carry no selector.
- **No ambient inheritance.** A queue message without the field no longer inherits an ambient
  worker `AIGATEWAY_PROFILE`.
- **Legacy messages still honoured.** A message accepted before the cutover that carries the
  field is still honoured and forwarded until the drain proof.

AIGateway stays on `HONOUR`, and this build is the rollback floor for the later gateway reject.

## Owner decision (2026-09-25)

No separate provenance census. The dev evidence and the absence of first-party callers that send
`X-Profile` are enough to proceed to producer-off. The SDK never sends the header
(`packages/screamingface/src/screamingface/_engine/catalog.py`). Recorded on `OME-1381`.

The tracked spec and plan still named the census as the next step. On 2026-09-26 the owner
decided to record the waiver in this same landing, with no separate `OME-1377` landing. This
landing therefore also amends the spec's §3.6, §6.2 and D4 row, the plan's stage row D, its
Stage D rollout paragraph and its G5b gate row, and the `OME-1377` mirror.

## Preflight (2026-09-25)

- Base `origin/main` `edf77790`, rebased onto `origin/main` `69971220` on 2026-09-26. Nothing
  upstream touched any path of this landing. The design target is `component/provider-access` v6, "Stage D
  target", rollout step 2 (screamingface-design `3ba6a3d`).
- Ingress readers:
  - `rest/routes.py` `start_run` → `_schedule(profile=)` → `job_runner.schedule(profile=)`; the
    log names the label (`:225`);
  - `rest/catalog.py` `list_models` and `model_parameters` → `Credential.derive(profile, ...)`;
  - `rest/connections.py:_caller` → `Caller(profile=...)`;
  - sync mounts: `rest/forwarder.py:NodeForwarder` (deployed) and `local.py:_LocalNodeMount`,
    both of which forward `X-Profile` to the node, and the node reads it
    (`request_scope.request_scope_from_headers`).
- Carriers:
  - `runner_queue._env_mapping` writes `AIGATEWAY_PROFILE` only when a profile is given;
  - `worker/supervisor.py:_child_env` starts from `dict(os.environ)` and so inherits an ambient
    value (pinned by `OME-1199`);
  - `adapters/inprocess.py:_env` already pops it.
- Legacy readers kept until Phase 5: `runner/main.py:94` → `world/connector.py:1076`; the node's
  `request_scope_from_headers`.
- Plan S6 lists `S11 disposition` as a dependency. The D4 decision puts producer-off *before* the
  gateway reject, and S6's legacy-reader removal (Phase 5) is what waits for S11. That ordering is
  consistent with the decision.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/request_scope.py` — `X_PROFILE_UNSUPPORTED`,
  a value-free message, and `requests_selector(values)`, which reuses the one "blank means absent"
  rule (`_optional`).
- `apps/screamingface-engine/src/screamingface_engine/auth/problem.py` — an optional `code`
  extension member (RFC 9457 §3.2). It is dropped when unset, so no other problem changes on the
  wire.
- `apps/screamingface-engine/src/screamingface_engine/rest/selector.py` (new) — `refuse_selector`,
  the one REST-side refusal.
- `apps/screamingface-engine/src/screamingface_engine/rest/routes.py` — refuse before any other
  work; `_schedule` passes no profile and logs no label; the header is documented as deprecated
  and refused.
- `apps/screamingface-engine/src/screamingface_engine/rest/catalog.py` — refuse on both routes
  before the service is touched; derive the credential without a profile. `Vary` is unchanged,
  because the 400/200 outcome still depends on the header.
- `apps/screamingface-engine/src/screamingface_engine/rest/connections.py` — `_caller` refuses and
  builds a selector-less `Caller`.
- `apps/screamingface-engine/src/screamingface_engine/rest/forwarder.py` — url4 envelope `400`
  after the identity check and before the forward.
- `apps/screamingface-engine/src/screamingface_engine/local.py` — the same refusal before binding.
- `apps/screamingface-engine/src/screamingface_engine/worker/supervisor.py` — `_child_env` pops the
  ambient `AIGATEWAY_PROFILE` before overlaying the message.
- Engine docs: `docs/request-workflow.md`, `docs/execution-flow-diagrams.md`.
- Added 2026-09-26, the census-waiver record:
  - `docs/spec/2026-09-09-OME-1138-converge-connections.md`;
  - `docs/plan/2026-09-09-OME-1138-converge-connections.md`;
  - `docs/tasks/2026-09-25-OME-1377-selector-sunset-decision.md`.
- Tests: a new `tests/unit/test_selector_producer_off.py`, plus the prior tests re-expressed in
  the table below.

## Test plan

New tests are written first (RED):

- Refusal on every surface:
  - covers execution, catalog, model parameters, the four connection routes, the deployed sync
    forwarder and the local sync mount;
  - the selector values are `team-a`, the literal `default`, a padded value, and a repeated
    header whose first value is blank;
  - each surface returns `400` with `code: x_profile_unsupported`;
  - the refusal never echoes the value;
  - nothing is scheduled, fetched, forwarded or mutated.
- Refusal ordering:
  - on execution, the refusal comes before the subscriber gate;
  - on the forwarder, it comes after the identity check.
- Selector-less requests:
  - absent, blank and whitespace-only headers behave exactly as absent;
  - the schedule call and the credential carry no profile;
  - the catalog cache key equals the absent-header key.
- The run-scheduling log names no profile.
- Identity, `traceparent`, cache policy, answer seed and client version reach the runner
  unchanged.
- The queue message produced by the real queue runner carries no `AIGATEWAY_PROFILE`.
- Worker:
  - a new message on a worker with an ambient value gives a child without the field;
  - a legacy message is honoured with or without an ambient value;
  - a redelivered legacy message is honoured on every delivery;
  - a legacy message's env still renders `X-Profile` on the outbound gateway call.

Added after the owner review (2026-09-26), again written first (RED):

- Connection-route precedence:
  - a stated selector wins over each invalid body (malformed JSON, missing, wrong type,
    forbidden extra field) and over the unconfigured-service 503;
  - controls: without a selector the same requests still answer 422 and 503.
- The no-echo check also covers every response header, names and values.
- OpenAPI:
  - every refusing operation declares `X-Profile` as a deprecated header and declares its 400
    as `application/problem+json` with the `Problem` schema;
  - `Problem` carries an optional `code`;
  - model parameters still declare AI Gateway's verbatim `application/json` 400;
  - `/token` and `/healthz` do not declare the header.

## Mixed-version matrix

| Combination | Covered by |
| --- | --- |
| old ingress + old worker | pre-change behaviour, pinned by the `OME-1199` characterisation at `edf77790`; not re-runnable from this build |
| new ingress + old worker | new ingress emits messages without the field, which the old decoder reads unchanged (same JSON env map); the old worker still inherits an ambient value, so the rollout precondition is to deploy workers with or before ingress, or to verify that no ambient `AIGATEWAY_PROFILE` is set |
| new ingress + new worker | the refusal tests plus the new-message-on-ambient-worker test |
| legacy message on a new worker | legacy-honoured tests (no ambient, and ambient replaced) |
| new message on a worker with an ambient value | ambient-removed test |
| redelivered legacy message | redelivery test (`num_delivered > 1`) |
| rollback before the gateway reject | old Engine plus `HONOUR` is today's behaviour; nothing here changes the gateway |
| rollback after the gateway reject | forbidden below this build; this build never emits a selector (refusal plus queue-message tests) |

## Prior tests re-expressed (old → new, accepted by the owner 2026-09-26)

Each of these tests pinned the ingress or carrier behaviour that this unit changes on purpose.
The intent of each test is kept; only the assertion about the retired contract moves.

The owner accepted all five on 2026-09-26 as a Confidence-Gate exception. They replace only the
retired selector contract and keep the identity, cache, environment, catalog and traceparent
checks. The runner's append-only check still flags them against `HEAD`, so the substantive gates
run with `--skip-append-only`.

| Old test | Old assertion | New test / assertion |
| --- | --- | --- |
| `test_rest_models.py::test_the_profile_becomes_part_of_the_identity` | `/v1/models` with `X-Profile: team-a` → `seen[0].profile == "team-a"` | `test_a_profile_is_refused_before_it_can_become_part_of_the_identity`: `400`, `code == x_profile_unsupported`, `seen == []` |
| `test_model_parameters_proxy.py::test_engine_returns_model_details_for_the_verified_identity_and_profile` | sent `X-Profile: research` → `200`, `credential.profile == "research"` | `test_engine_returns_model_details_for_the_verified_identity`: same verbatim/private assertions without the header; `credential.profile is None` (refusal in `test_selector_refusal.py`) |
| `test_rest_cache_convergence.py::test_the_cache_policy_travels_beside_profile_and_identity_not_instead_of_them` | sent `X-Profile: prod` → `call["profile"] == "prod"` | `test_the_cache_policy_travels_beside_identity_not_instead_of_it`: the header is not sent; `"profile" not in call`; identity and cache assertions unchanged |
| `test_traceparent_propagation.py::test_the_rest_edge_carries_a_valid_inbound_traceparent_through` | the request carried `X-Profile: prof` → `caller.profile == "prof"` | same name; the header is not sent; `caller.profile is None`; the traceparent assertion is unchanged |
| `test_profile_env_characterisation.py::test_the_worker_child_inherits_an_ambient_profile_the_message_did_not_carry` (`OME-1199` characterisation) | `env[AIGATEWAY_PROFILE] == _AMBIENT` | `test_the_worker_child_drops_an_ambient_profile_the_message_did_not_carry`: `AIGATEWAY_PROFILE not in env`; the module note and the in-process docstring now say the two runners agree |

The legacy-message test in the same module
(`test_a_profile_carried_by_the_message_replaces_the_ambient_one_in_the_child`) is unchanged and
still green.

## Acceptance

- Every listed surface refuses a nonblank `X-Profile` before any side effect, without echoing it.
- Selector-less behaviour is unchanged.
- New messages carry no selector, and ambient worker values are not inherited.
- Legacy messages are honoured and forwarded.
- Engine gates are green.

## Owner review (2026-09-26) — changes required

| # | Finding | Resolution |
| --- | --- | --- |
| 1 (high) | Connection routes refused inside `_caller()`, so FastAPI body validation (422) and `_service()` (503) could answer first; confirmed at runtime | The refusal moved into the router's route class (`_SecretSafeRoute`), before FastAPI reads, parses or validates the body and before the endpoint looks up its service; `_caller()` no longer refuses. Precedence tests plus controls, in `tests/unit/test_selector_connections.py` |
| 2 (medium) | OpenAPI: the catalog 400s were text-only; the connection routes did not declare the deprecated header | The catalog 400s declare `application/problem+json` with `Problem`, and model parameters also declare AI Gateway's verbatim `application/json` 400. The connection router declares the header through a documentation-only router dependency. One shared declaration (`rest/selector.py:X_PROFILE_PARAMETER`) serves all three modules. Tests in `tests/unit/test_selector_openapi.py` |
| 3 (medium) | The tracked spec and plan still required the census first | The spec and plan record the waiver in this landing (owner, 2026-09-26: one PR, no separate `OME-1377` landing). The `OME-1377` mirror is updated. The Q02 census mentions are a different census and stay unchanged |
| 4 (low) | The no-echo check ignored response headers | Also checks every response header name and value; mutation-checked (echoing the value in a header fails 37 tests) |
| 5 (low) | Stale docs | `request-workflow.md`: the world builder takes no token (`build_aigateway_world(cfg, tavily_api_key=…)`). `contracts.md` C3: `X-Profile` goes to the gateway only for a legacy queued message. The task mirror says "no first-party callers that send `X-Profile`" and shows the current status |
| 6 (low) | 28 PyJWT key-length warnings from the new tests | Test HMAC secrets are now 45 bytes; the new modules emit no warnings |

Owner decisions of the same review:

- the five re-expressed prior tests are accepted (see above);
- the breaking classification is approved. The final commit uses
  `feat(screamingface-engine)!:`, a `BREAKING CHANGE:` footer and `Refs: OME-1381`;
- commit, push and PR were not yet authorized at that point; a re-review followed these fixes;
- no internal artifacts are committed.

Follow-up decision (2026-09-26):

- everything lands as one PR with `Refs: OME-1381, OME-1377` (not a closing reference);
- the census waiver is recorded here; there is no separate `OME-1377` landing;
- both issues stay In Progress.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** 26 paths, as planned plus the following.
  - `docs/plans/contracts.md`: the C1 request headers, the C1 400 codes, the C2 forwarded headers
    and the C3 gateway headers.
  - The census-waiver record: the tracked OME-1138 spec and plan, and the `OME-1377` mirror.
  - the OpenAPI 400 descriptions on execution, catalog, model parameters and connections;
  - the new test modules are split by responsibility:
    - `tests/unit/test_selector_refusal.py`: execution, catalog and sync mounts, with the shared
      assertions;
    - `tests/unit/test_selector_connections.py`: the connection router boundary and its
      precedence;
    - `tests/unit/test_selector_openapi.py`: the published contract;
    - `tests/unit/test_selector_carrier.py`: queue, worker and legacy messages.
- **Commits:** one commit, `feat(screamingface-engine)!: refuse X-Profile at ingress and stop
  producing selector-bearing runs`, with a `BREAKING CHANGE:` footer and
  `Refs: OME-1381, OME-1377`. Its sha is recorded in the close comment.
- **Gates:** baseline at `edf77790` was `3827 passed, 23 skipped`.
  - First round (2026-09-25), `run_gates.py screamingface-engine --skip-append-only`:
    - ruff check, ruff format, pyright and layering green;
    - pytest `3905 passed, 23 skipped`, coverage 94.48%: 78 new tests plus the five re-expressed
      ones.
  - After the owner-review fixes (2026-09-26), the same command reported `ALL GATES GREEN`:
    - ruff check, ruff format, pyright and layering green;
    - pytest `3954 passed, 23 skipped`, coverage 94.48% (gate 80%): 49 more new tests, 32 for
      precedence and 17 for OpenAPI.
  - The four `test_selector_*` modules (127 tests) emit no warnings under `-W default`. The
    full suite's remaining PyJWT key-length warnings come from earlier modules.
  - The append-only check is still red on exactly the five owner-accepted tests.
- **Review:** an independent read-only review found no blocking defects. It confirmed:
  - every ingress refuses;
  - nothing happens before the refusal;
  - there is no leakage;
  - mixed-version behaviour is correct;
  - none of the five re-expressed tests lost coverage.

  Taken from it:
  - regression checks that the value never reaches the logs and that the refusal carries no
    `Retry-After`;
  - an `origin == "sync"` assertion on the local-mount binding test;
  - a docs fix: the refusal runs after the capability check.

  Offered and not taken:
  - a value-free refusal counter, because the census is skipped;
  - a forwarder test through `install_forwarder`, where the risk is low because the refusal
    lives in `__call__`.

  The owner review (2026-09-26, above) then found the connection-route ordering defect that
  this review missed, and it asked for the deprecated header on the connection routes.
- **Deviations:**
  - `Vary` on the catalog routes still names `X-Profile` (see `rest/catalog.py`); the design's
    "Vary stops naming X-Profile" is a gateway-side statement.
  - Repeated headers: every value is judged, so a blank first value cannot hide a named second
    one.
  - Found in RED: before this change a blank or whitespace-only `X-Profile` on `GET /?q=` reached
    the queue message as `AIGATEWAY_PROFILE: ""` or `"   "`. It no longer does.
  - `local.py` grows from 473 to 485 lines and `routes.py` from 607 to 611. Both files were
    already over 450 lines; the added lines are the refusal inside each file's existing
    request-validation step, not a new responsibility.
