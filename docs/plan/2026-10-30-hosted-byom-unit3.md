# Plan: hosted BYOM Unit 3, classification inference (OME-1794, OME-1795, OME-1796)

Spec: `docs/spec/2026-10-30-hosted-byom-unit3-classification.md`. Ledger:
`docs/work/2026-10-30-hosted-byom-unit3.md`. Branch: `OME-1794-hosted-byom-unit3` from origin/main
`05a7a6234`, moved to `fed613da2`, `e915d8037`, `bc96df570` and then `969d4e303` after the code was written
(ledger, Base). Stacks: `aigateway`, `screamingface-engine`, `screamingface`.
Epic `OME-1306`. One PR for the three leaves.

## Preconditions

- **Base synced.** On 2026-10-30 the branch, which had no commits, was fast-forwarded from
  `f76cacf85` to origin/main `05a7a6234`. No source or test file cited here changed between the
  two. On the new base `tests/test_public_surface.py` passes, so the snapshot there already holds
  main's `Mean`, `Judge` order, `Filter` judge and `Pick` output entries.
- Owner decisions of 2026-10-30 are in spec section 6. Two prior-test changes are approved:
  - `apps/aigateway/tests/unit/remote_endpoint/test_definitions.py`: the parameter value
    `"text-classification"` becomes `"embeddings"`; and, approved during the build (spec decision
    1a), two `isinstance(..., ChatTarget)` assertions with their import. Manifest
    `.claude/test-change-approvals/OME-1794.json`.
  - `packages/screamingface/tests/public_surface_snapshot.json`: regenerated on the synced base for
    `sf.classify`, `Client.classify`, `Classification` and `LabelScore`. Manifest
    `.claude/test-change-approvals/OME-1796.json`.
- **One base for both blobs.** Each manifest pins `branch: OME-1794-hosted-byom-unit3`.
  `base_blob` is `git rev-parse origin/main:<path>` at the branch base, and `approved_blob` is the
  `git hash-object` of the file edited on that same base. The gate compares the file at
  `--base origin/main` with `base_blob`, so if main moves a pinned file before merge, rebase
  first, redo the edit on the new base keeping main's entries, and refresh both blobs, as OME-1601
  did. Any later edit to a pinned file needs the same refresh. No other prior test changes; a red
  prior test is a finding to raise, not to edit.
- No Tortoise model, query or migration changes, so the `tortoise-dev` companion does not apply.
- Fakes only: no live key, paid call, production action or local NATS.
- Code starts only after the owner approves this plan in plain words. Staging, commits and the
  push happen only with the owner's go-ahead for each.

## Phase A: Gateway (OME-1794)

Paths below are under `apps/aigateway/`. New test helpers go in new functions or new modules;
existing helpers such as `Upstream._handle` and `Harness.start` are protected and stay unchanged.

### A1. Definitions

**RED.** New module `tests/unit/remote_endpoint/test_classification_definitions.py`, with a new
`classifier_target(**overrides)` helper appended to `tests/unit/remote_endpoint/fixtures.py`:
- a classifier target is accepted alone, as the validation target, and next to a chat target; both
  envelopes parse; the definition exposes its fields;
- refused at their location, with no value in the message: a classifier carrying
  `upstream_model`; a chat target carrying `response_envelope` or `score_semantics`; each
  incompatible `task` and `contract` pair, both ways; an unknown `task` at `targets.0.task`; a
  missing or unknown `response_envelope`; `score_semantics = "raw-score"`; a duplicate alias across
  kinds; a classifier `request_path` breaking the existing path rule.

Then the approved change at `test_definitions.py:359` and the `OME-1794.json` manifest.

**GREEN.** `src/aigateway/plugins/remote_endpoint/definitions.py` (296 lines):
- add the `ClassificationTarget` dataclass and `_ClassificationTargetDoc`;
- `targets` holds both kinds. A target is checked first against a one-field
  `Literal["chat", "text-classification"]` probe, so an unknown task fails at `targets.M.task` with
  a message that names no input. Then the kind's own model validates it;
- add `chat_targets` and `classifier_targets` accessors next to `target(alias)`.

If the module would pass 450 lines, the classifier document model moves to a new
`classification_definitions.py`.

### A2. Chat stays chat

**RED.** New module `tests/unit/remote_endpoint/test_classification_chat_isolation.py`:
- `/v1/models`, `/v1/model-parameters` and model admission never show a classifier ID;
- a chat call with a classifier ID answers `400 invalid_model` with zero upstream calls and zero
  key reads (`CredentialBlobProbe`);
- the global cache does not take part for a classifier ID.

**GREEN.** `plugin.py`: `register_models()` and `_declared` use chat targets only.

### A3. Provider hooks and the provider listing

**RED.** New modules `tests/unit/core/test_classification_hooks.py` and
`tests/unit/remote_endpoint/test_classifier_only_provider.py`:
- every bundled plugin lists no classifiers and refuses a classification as unsupported;
- a classifier-only endpoint appears in `/v1/providers` for a granted account and not for another
  account;
- the rows for every other provider are unchanged.

**GREEN.**
- `src/aigateway/core/plugin_base/_provider.py` (385 lines) gets two hooks next to
  `register_models` and `chat_completion`:
  - `register_classifiers() -> list[ModelEntry]`, default `[]`;
  - `async classify(body) -> dict`, default raising `NotImplementedError`.
- `routes/providers.py:35`: the predicate keeps a provider that has models or classifiers.

### A4. Decoder and transport

**RED.** New modules `tests/unit/remote_endpoint/test_classification_decoder.py` and
`test_classification_transport.py`.

Decoder:
- both envelopes decode;
- order and ties are kept;
- each of these is refused: an empty list, a duplicate label, an empty label, a non-string label,
  a boolean score, `NaN`, `Infinity`, a score outside `[0, 1]`, a two-item batch, a flat body
  under the `single-batch` setting and the reverse, a non-JSON content type, and too-deep JSON.

Transport:
- the exact URL, bearer and `{"inputs": ...}` body for text with Unicode, newlines, quotes and
  `+`;
- non-200 statuses map as chat does;
- a redirect is not followed;
- a body with no length header aborts near the cap;
- neither the key nor the input appears in any error detail.

**GREEN.**
- New `src/aigateway/plugins/remote_endpoint/classification.py` holds the request builder and the
  decoder. It reuses the JSON checks of `completion.py`.
- `transport.py` (181 lines): a generic `post_json(url, payload, *, api_key, client, decode)`, with
  `post_chat_completion` delegating to it. Chat behaviour does not change; its existing tests guard
  that.

### A5. Readiness by task

**RED.** New module `tests/unit/remote_endpoint/test_classification_readiness.py`. A classifier
validation target sends one classification of a fixed synthetic text to its own origin and path:
- a valid result gives `VALID`, and a malformed one gives `UNAVAILABLE`;
- 401, 402, 403 and 429 map as the chat probe maps them;
- a failed replacement keeps the previous key.

**GREEN.** `validation.py`: pick the request and decoder by the target's kind.

### A6. `POST /v1/classifications`

**RED.** New module `tests/unit/remote_endpoint/test_app_classification.py`. It uses the existing
`byom` harness and a new classifier fake upstream in a new helper module
`tests/unit/remote_endpoint/classifier_upstream.py`, swapped in after `byom.start`.

Log capture: `logs.configure` turns propagation off for `aigateway`, so `caplog` alone can see no
record and a "secret absent" check then passes on nothing. The helper module gets its own copy of
the recording handler that Unit 1 attaches to the `aigateway` logger (`_Recording` and
`_gateway_log()`, `tests/unit/remote_endpoint/test_app_shared_cache.py:220-241`). The Unit 1
module stays unchanged. Every log check first asserts that the expected record is present, then
that the key and the input are absent from every captured record.

The happy path runs end to end. It checks the exact upstream URL, bearer and body, the response
shape, and that ties come back in upstream order.

Each refusal below is checked for zero upstream calls and zero key reads:
- non-JSON;
- a non-string `model` or `input`;
- a missing prefix;
- each of `seed`, `top_k`, `function_to_apply` and `stream`, answered `400 unsupported_parameters`;
- an absent provider and an ungranted provider, which get the same `400 unknown provider` body;
- a granted unknown alias and a granted chat alias, answered `400 invalid_model`;
- a disabled endpoint.

The remaining cases:
- **No key:** the existing not-connected refusal.
- **Upstream failures:** every bad result is a sanitized `502`. A `429` or `503` passes its bounded
  `Retry-After` through. Each case finds its expected record in the capture above: the route's
  `classification failed` record with the provider, the code and the status, and for `429` and
  `503` also the existing overload-retry warning. The key and the input appear in no body and no
  captured record.
- **Isolation:** two accounts and two endpoints under overlapping calls each reach only their own
  origin with their own key.
- **No cache:** the global cache is neither read nor written.
- **Disconnect:** a cancelled dispatch answers `499`.

**GREEN.**
- New `src/aigateway/routes/classifications.py`. It follows the order of spec G6 and imports no
  chat module.
  - The credential resolve and authorize helpers are about 25 lines of plain `ProviderAccess`
    calls. They are re-implemented here, not imported from `routes/chat.py`.
  - The target check is membership in `plugin.register_classifiers()`.
  - Dispatch goes through `dispatch_with_budgets` around `with_overload_retry`.
  - Every failed dispatch logs one `classification failed provider=... code=... status=...`
    record, like chat's `dispatch failed` record: no body, key or input. An unexpected exception
    becomes the sanitized `502 provider_error`, logged by its type name only.
- `RemoteEndpointPlugin.classify` does the following:
  - looks up the classifier target;
  - requires the resolved key, with no ambient fallback;
  - calls `post_json` with the classifier decoder;
  - returns the result document.
- `src/aigateway/main.py`: one `include_router` line.

### A7. Classifier catalog

**RED.** New module `tests/unit/remote_endpoint/test_app_classifier_catalog.py`:
- **List.** A granted account lists its classifiers, an ungranted one lists none, and chat models
  are absent. Response headers are `private, no-store`.
- **Details for a granted caller.** The answer gives the task, the target contract, the result
  contract `classification-scores-v1`, and `execution_access`. That field is `missing` until a key
  is attached and `configured` after.
- **Details refusals.** An ungranted caller gets `400 unknown provider`. A granted caller's
  unknown or chat alias gets `404 model_not_found`. Refusals carry the same private headers.

**GREEN.** New `src/aigateway/routes/classifiers.py`, plus one `include_router` line in `main.py`.

### A8. Gate

Run `uv run .claude/scripts/run_gates.py aigateway` from the worktree root, one stack at a time.

## Phase B: Engine (OME-1795)

Paths below are under `apps/screamingface-engine/`.

### B1. Handler

**RED.** New module `tests/unit/test_classification_endpoint.py`. Its fake Gateway is an
`httpx.MockTransport` that records requests, following `tests/unit/test_endpoint_route_execution.py`.

Requests sent to the fake Gateway:
- it receives `POST /v1/classifications` with exactly `{"model", "input"}`, the input byte for
  byte;
- the identity headers and both budget headers are present, and Authorization is absent.

The result:
- it is the Gateway's JSON, validated, and served as JSON;
- a Gateway answer that fails validation becomes `aigateway_bad_response`.

Refusals, each with zero Gateway calls:
- context that is not JSON, an array, a missing field, an extra field, or a non-string value;
- a wrong intent, answered `malformed_source` (400).

Refusals by scope, with the handler called directly, each with zero Gateway calls:
- an answer seed, a capture scope and a replay scope (`frozen_copy_support.capture_scope` and
  `replay_scope`) get one Engine code;
- that code maps to `400` through `mount_http_status`.

These handler checks alone do not prove the capture boundary, because the executor talks to the
Gateway before and after the handler. That proof is the executor test below.

Gateway refusals:
- `400 unknown provider` and `400 invalid_model` both become one not-found code with one fixed
  message, mapping to `404`;
- `429`, `5xx` and transport errors keep the existing retry rules.

Usage: once the request is dispatched, exactly one record with no cost reaches the sink, whatever
the outcome; none before dispatch (spec E8, section 6, decision 7; changed after review, see
Phase R).

**GREEN.**
- New `src/screamingface_engine/world/classification.py` with no url4 import. It reads the scope
  through `current_scope()`. It reuses the connector helpers `_headers`, `_post_completion`,
  `_raise_for_status` and `_json_or_raise`, and adds the two budget headers. Its refusals are
  `RunnerRequestError` with stable codes.
- `world/serving.py`: two entries in `_ENGINE_STATUS`.

### B2. Registration and composition

**RED, capture boundary.** New module `tests/unit/test_classification_frozen_copy.py`, modelled
on `tests/unit/test_frozen_copy_executor.py`. It builds the world through `build_world`, so
`/classify` is registered as in production, with a recording `frozen_copy_support.Gateway`, and
runs the real `Url4Executor(world.node).execute(...)` on an expression that calls `/classify`
(spec section 6, decision 6):
- under `request_scope(capture_scope())` the Gateway paths are exactly the frozen-copy open and
  its seal; `POST /v1/classifications` is absent;
- under `request_scope(replay_scope())` the Gateway records no request;
- both runs end with the refusal code, and no usage reaches the sink.

The simulated binding in `frozen_copy_support.run_call` is not used here: it plays the
executor's open step instead of running it.

**RED, composition.** New module `tests/unit/test_classification_world.py`:
- `/classify` is in `direct_mount_paths` and in the App mount table as a public mount;
- OpenAPI lists `/classify`; metrics label it by that path; no classifier ID appears in either;
- a world with no Gateway section has no `/classify`;
- a declared model `classify` and a `[data]` mount at `/classify` each fail with a
  `WorldConfigError`, and the world's client is closed;
- `check-publication` passes an endpoints file whose classifier target the world does not declare.

**GREEN.** `world/factory.py` (365 lines):
- After `build_aigateway_world` returns, check for a `/classify` model route, then register the
  endpoint. A failure goes through a `try` that closes the world and raises `WorldConfigError`,
  as the read-side mounts do.
- A small wrapper turns `RunnerRequestError` into url4's `ResolutionError`, as
  `connector.py:487-491` does.

### B3. Hosted path

**RED.** New module `tests/unit/test_classification_hosted.py`, modelled on
`tests/unit/test_endpoint_route_execution.py` and `tests/unit/test_private_route_denial.py`:
- one `/classify` serves two target IDs, cold and warm, with no prior listing and no
  reconfiguration, and forwards the caller identity;
- the App mount `GET /classify?q=` goes through `InProcessJobRunner`:
  - a query of exactly 8182 raw bytes is accepted, and 8183 answers `414`;
  - an `X-Answer-Seed` header is refused before any Gateway call;
  - either frozen-copy header is refused by the App with `400 capture_unsupported` and no Gateway
    request;
  - wait bound: with `sync_max_wait_s = 60`, not the default 30, and a fake Gateway that never
    answers, a call with `Prefer: wait=0.2` answers `504 timeout` within a few seconds and its run
    is stopped. This is the Engine half of the SDK's wait contract (spec section 4.3).

**GREEN.** None is expected beyond B1 and B2. Any extra change found here is recorded as a
deviation.

### B4. Access-log redaction

**RED.** New module `tests/unit/test_access_log_redaction.py`. It saves and restores the
`uvicorn.access` filters itself. It builds the five-argument record uvicorn 0.52.3 emits and
formats it with uvicorn's `AccessFormatter`:
- a synthetic marker in `/classify?q=...` and in `/?q=...`, raw and percent-encoded, is absent
  from the line, while the method, path, HTTP version and status are present;
- a record without a query is unchanged;
- a record of another logger is untouched;
- two `create_app()` calls install one filter.

**GREEN.**
- A logger-level filter in a new `src/screamingface_engine/access_log.py`.
- `app.py`: it is installed in `create_app` next to `configure_logging()` (`app.py:146`), so the
  deployed and local start paths both get it.

### B5. Gate

Run `uv run .claude/scripts/run_gates.py screamingface-engine`.

## Phase C: SDK (OME-1796)

Paths below are under `packages/screamingface/`.

### C1. RED

New module `tests/test_classify.py`, using `httpx.MockTransport` as `tests/test_case_media.py`
does.

The request:
- it goes to `/classify`;
- `q` decodes to the exact JSON for text with Unicode, `+`, `&`, quotes and newlines;
- it carries no replay-safe extension;
- it carries `Prefer: wait=30`, and its read timeout is 45 seconds;
- wait contract with a non-default server limit: a fake Engine with a limit of 10, 30 or
  60 seconds (parametrized) parses the request's `Prefer` header, computes its bound as the smaller
  of that wait and its limit, as the Engine's
  `apps/screamingface-engine/src/screamingface_engine/rest/mounts.py:348` does, and asserts the bound is below the
  request's read timeout. It then answers `504 timeout`, which raises an `ExecutionError`, not a
  client timeout. After review that error is not retryable (Phase R).

Size:
- an input that fits exactly is sent;
- one more character raises before any request.

The result:
- a typed result keeps order and ties;
- a malformed success body raises;
- a `303` is followed with a bounded read and decoded.

Errors:
- A `404` without the url4 envelope raises `EngineCapabilityError` with its code, status,
  details and hint.
- A `404`, `400` or `414` with the envelope raises `PlanningError` carrying the Engine code.
- `502`, `503` and `504` raise an `ExecutionError`; after review only a confirmed refusal before
  sending is retryable (Phase R).
- `401` and `403` raise `AuthenticationError`.
- A connect-phase transport error raises `EngineUnavailableError`; after review a later one raises
  a non-retryable `ExecutionError` (Phase R).

Finally, `sf.classify` delegates to the default client.

### C2. GREEN

- New `src/screamingface/classification.py` holds the result types `Classification` and
  `LabelScore`, which are frozen dataclasses, as `media.py` holds `FetchedMedia`.
- New `src/screamingface/_engine/classification.py` holds the encoding, the size check, the
  request, with `Prefer: wait=30` and the 45 second read timeout, and the decoding. It takes a GET
  callable, as `_engine/catalog.py` does.
- `client.py` (1000 lines) gets a thin `classify` method and a private
  `_engine_get(path, *, headers, timeout)` seam that sets no replay-safe mark.
- `_default_client.py` gets `classify`.
- `__init__.py` adds `classify`, `Classification` and `LabelScore` to the exports and `__all__`.

### C3. Public surface

- Work on the synced base only (preconditions). Regenerate the snapshot with
  `UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py`.
- Compare with `git diff origin/main -- tests/public_surface_snapshot.json`. The diff may only
  add: `classify`, `Classification` and `LabelScore` with their members under the top level, the
  three names in `__all__`, and `classify` among the `Client` members. Every entry main already
  has, `Mean`, `Judge` order, `Filter` judge and `Pick` output among them, stays byte for byte.
- `PINNED_MODULES` does not change. The result types are pinned through the top-level
  re-export, as `FetchedMedia` is, so `screamingface.classification` needs no entry of its own.
- Write `OME-1796.json`: `base_blob` from `git rev-parse origin/main:packages/screamingface/tests/public_surface_snapshot.json`,
  `approved_blob` from `git hash-object` of the regenerated file, both on the same base.
- Add a `CHANGELOG.md` entry under "Unreleased", after main's entries there.

### C4. Gate

Run `uv run .claude/scripts/run_gates.py screamingface`.

## Phase R: Review fixes (owner decisions 7 to 10)

A read-only review of the first implementation found a cost gap and a retry mislabel. The owner
chose the fixes on 2026-10-30. Each one is TDD, in new test files or the branch's own new ones.

1. **Engine cost (decision 7).** After dispatch, one usage record with `cost_usd=None` and the
   two required token counts at 0, documented as not measured. Tests: one record after success,
   Gateway refusal and contract failure; none before dispatch; through `Url4Executor`, a priced
   chat call plus `/classify` gives an unpriced total and the same run without it stays priced.
2. **SDK retry (decision 8).** Retryable only for a connect-phase failure, `429`, a `503` with
   `Retry-After` and a `503` with `admission_timeout`. Everything else, transport failures after
   sending and a failed artifact fetch after a `303` are classification-specific, non-retryable
   `ExecutionError`s. `EngineUnavailableError` does not change.
3. **Lone surrogates (decision 10).** Refused before I/O: Gateway `400 invalid_request`, Engine
   `malformed_source`, SDK `PlanningError`; nothing replaced, no text in the error.
4. **`check-publication` (decision 10).** A classifier target declared as an Engine model is
   refused; a chat target still passes. Prior publication tests stay unchanged.
5. **SDK overflow (decision 10).** A score past the float range is `engine_contract_error`.
6. **`$` literal and docs (decision 10).** Tests that `$text` stays literal on the direct path and
   in the SDK; spec section 8 records the queued run message and `$` in expressions.
7. **Empty input (decision 9).** Stays allowed; no change.

Then the three gates run again, one after another, with `--base origin/main`.

## Phase R2: Second review fixes

A second review on 2026-11-02 found three issues (spec decision 11). Each fix is TDD in the
branch's own new test files.

1. **SDK redirect.** `_artifact_path` matches the raw `Location` against the exact signed form
   `/artifacts/<hex id>?exp=<digits>&sig=<token>`. Tests: dot segments to `/classify`, nested,
   single and encoded dot segments, an encoded slash, a backslash, an absolute and a network-path
   URL, an extra segment, an unsigned path and a fragment are refused with one request sent; the
   Engine's own signed form is still fetched.
2. **Gateway nested body.** `RecursionError` from `request.json()` is the malformed-body `400`.
   Route test: 10,000 nested arrays get `400`, with no provider lookup, key read or upstream
   request, and the input in neither the answer nor a log record; a control call proves the spies.
3. **SDK overflow.** Already fixed by decision 10. Tests add a negative overflow and the integer
   scores `0` and `1`.

Then `git fetch origin`, a fast-forward if main moved, and the three gates again.

## Phase R3: Third review fixes

A third review on 2026-11-02 (spec decision 12) found ten issues; the owner chose eight for this
PR. Each fix starts from a test that fails, in the branch's own new test files.

1. **SDK artifact after an Access login.** `_artifact` sends the fetch once more after the auth
   layer's `access_reauthenticated`, and turns every other failure into `result_unavailable`.
   Tests: one challenge then the result, with one `/classify`; two challenges, an artifact past
   the read limit.
2. **SDK admission timeout.** The `admission_timeout` branch goes. Its case in
   `test_a_refusal_before_anything_ran_is_retryable` goes; a new test pins both spellings as
   not retryable.
3. **SDK gone result.** `result_unavailable` at any status is the post-run `ExecutionError`.
4. **Engine percent-escapes.** `rest/mounts.py` refuses a `/classify` query whose percent-escapes
   are not UTF-8 as `malformed_source`, through `world.classification.refuses_query`. Test: three
   escapes refused with no Gateway request, a valid one classified.
5. **Gateway log level.** The `provider_queue_timeout` `503` logs at WARNING, an upstream `503`
   at ERROR.
6. **Gateway field names.** A lone surrogate in an unknown field name is `400 invalid_request`
   without echoing names.
7. **Gateway grant order.** A test pins one answer for an ungranted caller across three aliases.
8. **Engine access log.** A test drives uvicorn's own `h11` and `httptools` protocols in process
   and finds no query in the access record. The filter is unchanged: cutting every argument would
   change `test_a_record_of_another_shape_or_logger_is_untouched`.

Not in this PR: the publish-phase `503` (section 8) and the model ID in telemetry.

## Phase D: Close-out

1. `git fetch origin`. If origin/main moved, rebase first and, where a pinned file changed on
   main, redo that edit and refresh both blobs of its manifest (preconditions). Then run the three
   gates again with `--base origin/main`, so the append-only check sees the whole branch and both
   manifests match.
2. Review the actual diff. Check file sizes, that code has no Cyrillic and only the `WHY:`,
   `INVARIANT:`, `FEATURE:` and `STORY:` anchors, that
   no secret or input is logged, and that every prior test is unchanged except the two pinned
   ones.
3. Fill the ledger Outcome: files, commits, gates with counts, and deviations.
4. Write the PR body with `Refs: OME-1794`, `Refs: OME-1795` and `Refs: OME-1796`, a
   not-hosted-ready note, and the residual risks of spec section 8.
5. Staging, commit, push and PR-open each happen only with the owner's go-ahead.
6. Close-comments go on all three leaves at finish.

## New and changed files

| File | Change | Expected size |
|---|---|---|
| `apps/aigateway/src/aigateway/plugins/remote_endpoint/definitions.py` | classifier target | under 450 lines, or a split |
| `apps/aigateway/src/aigateway/plugins/remote_endpoint/classification.py` | new | about 120 lines |
| `apps/aigateway/src/aigateway/plugins/remote_endpoint/transport.py` | generic POST | about 195 lines |
| `apps/aigateway/src/aigateway/plugins/remote_endpoint/plugin.py`, `validation.py` | chat-only listing, `classify`, readiness by task | small |
| `apps/aigateway/src/aigateway/core/plugin_base/_provider.py` | two hooks | about 405 lines |
| `apps/aigateway/src/aigateway/routes/classifications.py`, `classifiers.py` | new | each under 250 lines |
| `apps/aigateway/src/aigateway/routes/providers.py`, `main.py` | predicate, two router lines | small |
| `apps/screamingface-engine/src/screamingface_engine/world/classification.py` | new | about 150 lines |
| `apps/screamingface-engine/src/screamingface_engine/world/factory.py` | registration | about 390 lines |
| `apps/screamingface-engine/src/screamingface_engine/world/serving.py` | two status entries | small |
| `apps/screamingface-engine/src/screamingface_engine/access_log.py`, `app.py` | filter and install | about 50 lines, two lines |
| `packages/screamingface/src/screamingface/classification.py`, `_engine/classification.py` | new | each under 200 lines |
| `packages/screamingface/src/screamingface/client.py`, `_default_client.py`, `__init__.py` | thin entry points | small |

## Risks to watch

- **Pydantic locations.** If the task probe cannot keep the location `targets.M.task`, stop and
  raise it rather than edit the approved test further.
- **Lint limits.** The route's complexity limits: complexity 8, 26 statements, 7 branches,
  3 returns. Split the steps into small functions early.
- **Retry policy reach.** `with_overload_retry` must wrap only the upstream call, never the
  credential steps.
- **Log filter install.** The access-log filter must not be installed in worker processes'
  loggers by accident. It goes in `create_app` only.
- **Capture test shape.** If the real executor cannot run `/classify` under a capture scope
  without a running App, stop and raise it; a simulated open step does not meet decision 6.
