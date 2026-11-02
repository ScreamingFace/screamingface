---
ticket: OME-1794   # Gateway; siblings OME-1795 (Engine) and OME-1796 (SDK) land in the same PR
stack: aigateway, screamingface-engine, screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-30
finished:
---

# hosted-byom-unit3 — classification inference through the hosted Engine

## Intent

Hosted BYOM Unit 3. An authenticated caller sends a classifier model ID and a text to the hosted
Engine; the Engine's worker asks the Gateway, which calls the configured classifier endpoint with
that account's own Connection and returns the model's labels and scores unchanged. Classifiers are
BYOM models like chat ones. This unit adds inference only: no routing decision, no downstream model
call, no Taxonomy accounting. Unit 2 (chat) is merged; its hosted check is still pending.

## Planned changes

Fixed by the spec (`docs/spec/2026-10-30-hosted-byom-unit3-classification.md`, owner decisions
2026-10-30); exact files and steps come from the plan before any code:

- Gateway: a typed classification target in the configured-endpoint definition, a classification
  transport and readiness validator, a typed catalog and one classification route, and a provider
  listing predicate based on supported inference capabilities.
- Engine: one stable classification ingress handled by a worker connector that sends only the
  model ID and the input to the Gateway, and query redaction for every access-log record.
- Client: a narrow typed call and decoder helper (own `client-sf` leaf; no public SDK path calls
  the ingress today). It states its own wait to the Engine and allows a longer read timeout.
- Approved prior-test changes in two files, each pinned by its own approval manifest: in
  `test_definitions.py`, one value in `test_unsupported_tasks_and_contracts_are_refused` and two
  type assertions in `test_two_endpoints_become_ordered_definitions_with_canonical_targets`
  (`OME-1794.json`, spec decisions 1 and 1a); and the public surface snapshot regenerated on the
  current base for the new SDK call and result types (`OME-1796.json`).
- One PR, three leaves under `OME-1306`.

Base: the branch had no commits and was fast-forwarded from `f76cacf85` to origin/main
`05a7a6234` on 2026-10-30, before any code or manifest, and again to `fed613da2` after the code
was written. The second move kept the uncommitted work: the two files main also changed
(`routes/model_parameters.py`, `packages/screamingface/CHANGELOG.md`) were saved as a patch,
restored, fast-forwarded and re-applied with a clean three-way apply. During the review fixes
origin/main moved again, to `e915d8037` (#1614), and the branch followed the same way; the one
file main also changed was `apps/aigateway/src/aigateway/main.py`. Neither pinned test file
changed on main, so both manifests kept their blobs. On 2026-11-02, before the second review's
gates, origin/main was at `bc96df570`; no file main changed between `e915d8037` and it is touched
here, so the branch was fast-forwarded with nothing to re-apply. Before the commit it moved
once more, to `969d4e303` (#1612), which changes only Gateway operator docs and their ledger and
mirror; the branch was fast-forwarded again.

Process choice for this unit (owner, 2026-10-30): the leaves OME-1794, OME-1795 and OME-1796 were
filed under epic OME-1306 before any code, instead of at PR-open, because an approval manifest
needs the issue ID and the final branch name. The branch was renamed from `hosted-byom-unit3` to
`OME-1794-hosted-byom-unit3` before its first commit. The general process is unchanged.

The owner approved the spec and the plan in plain words on 2026-10-30, after the review fixes
(capture boundary, wait contract, synced snapshot base). Implementation started then.

## Test plan

- Gateway: a classifier-only provider is listed, connected and validated without a chat model; a
  real handler calls a fake classifier with the exact input, auth and path and returns typed labels
  and scores, ties kept in order; a task mismatch, an unknown or ungranted ID causes no upstream
  I/O; malformed, oversized and non-finite results fail safely; two accounts and two endpoints stay
  isolated. Log checks capture records on the Gateway logger itself and first assert that the
  expected record is present.
- Engine: one ingress serves two targets cold and warm without reconfiguration or prior listing;
  the exact text and caller scope reach the Gateway; a seed is refused before spend; the encoded
  length limit answers 414; private IDs stay out of OpenAPI and metrics. Through the real executor,
  a capture run makes only the existing frozen-copy open and seal and no classification request,
  and a replay run makes no Gateway request. With a 60 second server limit, a short client wait
  still ends in the Engine's own timeout answer.
- Access log: a synthetic marker in a direct call and in a nested `GET /?q=` expression, raw and
  percent-encoded, never reaches a formatted access line.
- Client: encoding round-trips, the size check fires before any request, and an Engine without
  the ingress raises the capability error. For server limits of 10, 30 and 60 seconds the
  Engine's bound stays below the client's read timeout.
- Prior tests stay unchanged (append-only), except the owner-approved changes above.

## Acceptance

- Deterministic checks with fake upstreams and queue and worker substitutes; gates green for every
  touched stack.
- No live keys, paid calls or production actions. A real classifier smoke is Unit 4, separately
  authorized.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - Gateway source, changed: `core/plugin_base/{__init__,_ports,_provider}.py`, `main.py`,
    `plugins/remote_endpoint/{completion,definitions,plugin,transport,validation}.py`,
    `routes/{model_parameters,providers}.py`. New: `plugins/remote_endpoint/classification.py`,
    `routes/classifications.py`, `routes/classifiers.py`.
  - Gateway tests: new `tests/unit/core/test_classification_hooks.py`,
    `tests/unit/remote_endpoint/classifier_upstream.py` and nine
    `tests/unit/remote_endpoint/test_{app_classification,app_classification_failures,app_classifier_catalog,classification_chat_isolation,classification_decoder,classification_definitions,classification_readiness,classification_transport,classifier_only_provider}.py`;
    `fixtures.py` gains one helper at its end; `test_definitions.py` has the two approved changes.
  - Engine source: new `access_log.py`, `world/classification.py`; changed `app.py`,
    `world/factory.py`, `world/serving.py`, and after review `world/connector.py` (one helper),
    `world/publication.py` and `cli.py`. Tests: new
    `tests/unit/test_{access_log_redaction,classification_endpoint,classification_frozen_copy,classification_hosted,classification_world,classification_run_cost,publication_classifier_review}.py`.
  - SDK: new `src/screamingface/classification.py`, `src/screamingface/_engine/classification.py`,
    `tests/test_classify.py`; changed `__init__.py`, `_default_client.py`, `client.py`,
    `CHANGELOG.md`, `tests/public_surface_snapshot.json` (additions only).
  - Approval manifests `.claude/test-change-approvals/OME-1794.json` and `OME-1796.json`; spec,
    plan, this ledger and the three `docs/tasks/` mirrors.
- **Commits** (on `969d4e303`, with the owner's go-ahead on 2026-11-02):
  - `c52b108e8` feat(aigateway): classify text with configured endpoint classifiers
  - `e33cad0ae` feat(screamingface-engine): serve /classify through the Gateway
  - `4b7cd78f0` feat(screamingface): add Client.classify and sf.classify
  - then one docs commit with the spec, the plan, this ledger and the three mirrors.
- **Gates, first implementation** (`uv run .claude/scripts/run_gates.py <stack> --base origin/main`
  on `fed613da2`):
  - `screamingface`: all green, approved OME-1796 transition accepted; pytest 5151 passed,
    38 skipped, coverage 97.09%. New tests: 58 passed.
  - `screamingface-engine`: all green on the second run. The first run had 2 failures in the
    import-isolation tests (`test_run_mode_does_not_import_the_serving_stack`,
    `test_importing_the_run_entrypoint_does_not_load_opentelemetry`). The cause was the local
    venv: the `inspect` extra was installed, which loads starlette and OpenTelemetry. origin/main
    sources in the same venv loaded the same modules. After `uv sync --dev`, the set CI installs,
    the probe loads none and the gate is green. New tests: 92 passed.
  - `aigateway`: all green on the second run, approved OME-1794 transition accepted. The first
    run's pytest had 7564 passed, 107 skipped, 1 failed, coverage 94.09%. The failure was
    `test_unknown_user_timing_close_to_wrong_password`, a wall-clock comparison, on a machine at
    load average 30 to 44. Run alone and alternated, it failed 2 of 3 times on origin/main
    sources and 1 of 3 on the branch. No auth file is changed. New tests: 236 passed.
- **Review:** a read-only review of the first implementation found one blocker, one major
  issue, four minor ones and three nits. The owner decided on 2026-10-30 (spec section 6,
  decisions 7 to 10, plan Phase R):
  - Decision 7, cost: a dispatched classification reports one usage record with no cost, so a
    run with a priced chat call and a classification ends unpriced. Before the fix, the
    real-executor test of that run failed with a priced total (`openrouter-credits-1usd`).
  - Decision 8, SDK retries: retryable only after a confirmed refusal before sending (connect
    failure, `429`, `503` with `Retry-After`, `503` with `admission_timeout`). Every other
    answer, any transport failure after sending and a failed artifact fetch are not retryable.
  - Decision 9: an empty input stays allowed.
  - Decision 10: a lone surrogate is refused before I/O at all three layers; `check-publication`
    refuses a classifier declared as an Engine model; a score past the float range is
    `engine_contract_error` in the SDK; spec section 8 records the queued run message, `$` in
    expressions and the proxy `503` inference.
- **Gates, review round** (same command, run one stack at a time on `e915d8037`; on success
  the runner prints only its check lines, so this round has no test counts):
  - `aigateway`: all green, approved OME-1794 transition accepted.
  - `screamingface`: all green, approved OME-1796 transition accepted.
  - `screamingface-engine`: all green on the second run. The first run failed only at pyright,
    with 11 errors in the existing `tests/unit/inspect` files: the `inspect` extra had been
    installed into the local venv again. After `uv sync --dev`, pyright had 0 errors and the
    gate was green.
  - The added code and docs use only the `WHY:`, `INVARIANT:`, `FEATURE:` and `STORY:` anchors
    and hold no Cyrillic text.
- **Second review** (2026-11-02, spec decision 11, plan Phase R2):
  - SDK redirect: `Location: /artifacts/../classify?q=...` passed the prefix check, and httpx
    resolved it to `/classify`, so a second classification was sent and its result returned.
    Reproduced first: the new test failed for 9 of 12 locations. The raw `Location` must now
    match the Engine's exact signed form; all 12 are refused with one request sent.
  - Gateway nested body: 10,000 nested arrays raised `RecursionError`, logged as an unhandled
    error, and answered `500`. Reproduced first through the real app. `RecursionError` is now the
    malformed-body `400`, with no provider lookup, key read, upstream request or log record of
    the input; a control call proves the spies see what a refusal skips.
  - SDK overflow of `10**400`: already fixed in the first review (decision 10), with its test
    since then. The new negative overflow and integer `0` and `1` tests passed before any change.
  - Same class elsewhere, not changed here: `routes/chat.py:480` and `routes/frozen_copies.py:133`
    on main also catch only `ValueError` around `request.json()`.
- **Gates, second review** (same command, one stack at a time, on `bc96df570`):
  - `screamingface-engine`: all green; no Engine file changed in this round.
  - `aigateway` and `screamingface`: the first run failed only at `ruff check`, one line of 101
    characters in each new test. After the fix and `ruff format`, both are all green, with the
    approved OME-1794 and OME-1796 transitions accepted.
  - Targeted runs: the SDK's `tests/test_classify.py` 98 passed; the Gateway's two classification
    route modules 44 passed.
- **Deviations:**
  - Decision 1a: a second approved prior-test change, two `ChatTarget` type assertions in
    `test_definitions.py`, because `targets` now holds both target kinds as the spec requires.
  - Files already over 450 lines that grew: `apps/aigateway/src/aigateway/main.py` 498 to 503,
    Engine `world/serving.py` 492 to 500, Engine `app.py` 773 to 784, Engine
    `world/connector.py` 1768 to 1794 (the E8 helper), SDK `client.py` 1000 to 1034.
  - New test files over 450 lines: the SDK's `tests/test_classify.py` reached 651 lines in the
    first implementation and 736 after the second review. Every test in it drives `classify`;
    the redirect tests sit beside the existing artifact tests.
  - Base: moved from `05a7a6234` to `fed613da2`, `e915d8037`, `bc96df570` and then
    `969d4e303` after the code was written (see Base above).
  - Gateway: a new `ClassifierEntry` port type instead of `ModelEntry`, since a classifier row
    has a task and a contract, not LiteLLM parameters. The result contract constant
    `classification-scores-v1` lives in `core/plugin_base/_ports.py`. A6 is split into two test
    modules. The decoder keeps only `label` and `score` of each item. The failure record also
    names the exception type. `execution_access` moved out of the model-parameters handler and
    is shared with classifier details. Catalog rows carry `object`, `id`, `owned_by`, `task`,
    `contract`; details add `result_contract` and `execution_access`. The plan's lint limits
    did not match `pyproject.toml`; the code follows `pyproject.toml`.
  - Engine: helpers `_configure_logs` and `_gateway_world` keep the statement limit. A query
    string on `/classify` is refused as `malformed_source`. The result is re-serialized with
    the four contract fields only. A model ID without a provider or an alias is refused
    without a Gateway call. The unknown-cost record is also reported when every transport
    attempt failed at connect, which a failed run tolerates. `cli.py` folds two statements into
    one to stay under its statement limit.
  - SDK: a malformed result raises `engine_contract_error`. A 303 is followed only to
    `/artifacts/`. The SDK does not range-check scores; the Gateway does. A transport failure
    after sending gets the new code `classification_outcome_unknown`; a lone surrogate gets
    `malformed_source`, the code the Engine answers for the same input.
- **Not done here:** the hosted check through Linux, NATS and JetStream. Until it passes, no
  hosted readiness is claimed and this unit stays open.
