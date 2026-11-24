---
ticket: OME-1822   # Engine; sibling OME-1823 (SDK) lands in the same PR
stack: screamingface-engine, screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-04
finished:
---

# byom-routing-pilot — one routed answer: classify, select one branch, answer

## Intent

A caller names a routing profile and sends one question. One Engine run classifies the question
through the Gateway, picks the single highest-scoring label of that profile, and sends the
unchanged question to the one chat model bound to that label. The caller gets that model's
answer with the scores and the selected label and model. This is a new slice above hosted BYOM
Unit 3 (`/classify`, merged in PR #1638). It adds no synthesizer, no Fusion, no fallback and
no second model call. Spec: `docs/spec/2026-11-04-byom-routing-pilot.md`. Plan:
`docs/plan/2026-11-04-byom-routing-pilot.md`.

## Base

Worktree `.claude/worktrees/byom-routing-pilot`, branch `byom-routing-pilot` from origin/main
`89e6acfeb`, which contains the Unit 3 merge `0a4aa1bef`; renamed to
`OME-1822-byom-routing-pilot` on 2026-11-04 after the leaves were filed, before any commit. The
Unit 3 worktree `.claude/worktrees/hosted-byom-unit3` stays at `e802cff67`, untouched.

Spec approved with edits on 2026-11-04 (spec section 6). Leaves under `OME-1306`: `OME-1822`
(`screamingface-engine`) and `OME-1823` (`client-sf`), filed before Phase 1 at the owner's
direction. Mirrors: `docs/tasks/2026-11-04-OME-1822-engine-routed-answer.md`,
`docs/tasks/2026-11-04-OME-1823-sdk-route-answer.md`.

Locked versions read from `uv.lock`: Engine httpx 0.28.1, fastapi 0.141.1, starlette 1.3.1,
uvicorn 0.52.3, url4 1.5.1 (workspace). SDK httpx 0.28.1. No dependency is added.

## Planned changes

Engine (`apps/screamingface-engine/src/screamingface_engine/`):

- `world/routing_config.py` (new): parse and validate `[routing.profiles.<id>]`.
- `world/routing.py` (new): `/route-answer` endpoint, preflight, selection, result.
- `world/config.py`: `routing` top-level key and `WorldConfig.routing` field only.
- `world/factory.py`: register `/route-answer` before the direct-mount snapshot; nested
  branch dispatch on the same node. After review C3 the registration lives in the new
  `world/gateway_endpoints.py`, which `factory.py` calls.
- `error_text.py`: `ROUTING_CODES` in the reserved set (review C6).
- `rest/mounts.py`: refuse undecodable escapes on `/route-answer` before a run.
- `world/serving.py`: the routing codes join the mount status table.

SDK (`packages/screamingface/`):

- `src/screamingface/_engine/direct_get.py` (new): the one-GET transport `classify` uses today,
  moved without behavior change.
- `src/screamingface/_engine/classification.py`: imports the moved helpers.
- `src/screamingface/_engine/routed_answer.py` (new): request, error mapping, decoder.
- `src/screamingface/routing.py` (new): `RoutedAnswer`.
- `src/screamingface/client.py`, `src/screamingface/__init__.py`: `Client.route_answer`, export.
- `CHANGELOG.md`; `tests/public_surface_snapshot.json` under an approval manifest.

Outside Git: the `model_router_v1` Laya wrapper and the Phase 4 loopback harness (spec 4.3).

## Test plan

New test files only; every prior test stays unchanged except the approved snapshot.

- Engine config: valid profile; each refusal rule; revision stable and sensitive.
- Engine endpoint through the real executor with a fake Gateway: each label selects its branch;
  zero calls to unselected branches; exact input to classifier and branch; caller identity on
  every Gateway call; unknown-cost record kept; tie, invalid scores, preflight refusals,
  classifier and branch failures, cancellation between steps, seed and capture refusals.
- Engine App: `/route-answer` is a mount; escapes refused; statuses per spec table.
- SDK: encoding, size, Unicode, decoding, every error code, artifact path, one request only.
- Classify regressions: `tests/test_classify.py` unchanged and green after the move.

## Acceptance

- Spec acceptance (section 5) met by deterministic tests; Engine and SDK gates green.
- Live pilot only after operator inputs and an approved test window (spec section 7).

## Progress

- 2026-11-04, Phase 2 (Engine, `OME-1822`) green. New tests, 216 in all:
  `tests/unit/test_routing_config.py`, `test_routing_endpoint.py`, `test_routing_preflight.py`,
  `test_routing_mount.py`, `test_routing_world.py`, `test_routing_run_cost.py`, with the shared
  fixtures in `tests/unit/routing_support.py`. Config, endpoint and preflight tests were written
  red first; the world, mount and run-cost tests were written after the implementation.
  `run_gates.py screamingface-engine --base origin/main`: ALL GATES GREEN (append-only, ruff,
  format, pyright, layering, pytest with coverage at least 80 percent); 7061 tests collected.
- The run-cost test is shown to bite: with the classifier's unknown-cost record suppressed in a
  scratch probe, the routed run reports a priced total and the test fails, while the control run
  (the branch's answer alone) stays priced.
- Spec corrections recorded as spec 6.1, C1 to C4; plan Phase 2 aligned.
- 2026-11-04, Phase 3 (SDK, `OME-1823`). The transport moved to `_engine/direct_get.py` first;
  `tests/test_classify.py` stayed unchanged and 104 of 104 passed before and after the move.
  Then `tests/test_route_answer.py` and `tests/test_route_answer_errors.py` (104 tests, helpers in
  `tests/_route_answer_fixtures.py`) were written red, failing on the missing module, and
  `_engine/routed_answer.py`, `routing.py`, `Client.route_answer` and the `sf.RoutedAnswer`
  export made them green. A scratch mutation that accepts a tie for the top score fails exactly
  the tie case. The public-surface snapshot gains 8 lines and loses none, pinned in
  `.claude/test-change-approvals/OME-1823.json`. Spec 6.1 C5 records the wider move.
  `run_gates.py screamingface --base origin/main`: ALL GATES GREEN (approved snapshot
  transition, append-only, ruff, format, pyright, pytest with coverage at least 95 percent,
  notebooks, build, distribution). The first run was red at pyright only because the worktree
  environment lacked the notebook extra that CI installs (`uv sync --extra notebook`); after
  `uv sync --frozen --extra notebook`, with no lock or manifest change, it was green.
- 2026-11-04, review fixes (spec 6.1 C3, C6, C7). Tests written red first: 60 new cases
  failed for the reported reasons while the 106 prior cases in the same files passed; the App
  case reproduced `500 internal_error`, "maximum recursion depth exceeded".
  - C6: `tests/unit/test_routing_relayed_errors.py` (52 cases: every routing code, in a `400`,
    `429` or `502` body, at the classifier and at the branch, plus the App) is green once
    `error_text.ROUTING_CODES` joins `ENGINE_RESERVED_CODES`. The existing reserved-code test in
    `tests/unit/test_aigateway_connector.py`, unchanged, now covers the 8 routing codes too.
  - C7: both metadata readers in `world/routing.py` also catch `RecursionError`; 8 preflight
    cases and 1 App case are green, with no POST.
  - C3: the move to `world/gateway_endpoints.py` made `test_only_engine_extensions_import_url4`
    fail on exactly the new module; the one approved allowlist entry made it green. The
    registration, collision, classification, routing, layering and url4 executor tests: 488
    passed.
  - `run_gates.py screamingface-engine --base origin/main`: ALL GATES GREEN, including the
    approved OME-1822 test transition; 7130 tests collected, 69 more than Phase 2. Run in a
    scratch environment built with `uv sync --frozen --dev`, as CI does. The worktree `.venv`
    had gained the `inspect` extra at 14:38, from no command of these fixes, and with it pyright reports 12
    errors in four `tests/unit/inspect/` files that are unchanged against `origin/main`; CI does
    not install that extra. The worktree `.venv` was left as found.
  - SDK unchanged in this round; `tests/test_route_answer.py`, `tests/test_route_answer_errors.py`
    and `tests/test_classify.py`: 208 passed.
- 2026-11-04, review P3 (spec 6.1 C8). Agreed with the review and fixed in this slice, on
  `/route-answer` only. Tests written red first in `tests/unit/test_routing_relayed_errors.py`:
  48 cases failed, every code the Engine or url4 gives a status other than `502`, at the
  classifier and at the branch, plus the review's four App cases; the codes that already answer
  `502` passed as controls. `world/gateway_endpoints.py` now relays a `_GatewayRefusal` from
  either call with its own code only when the mount answers that code as a Gateway failure, and
  otherwise as `aigateway_http_<status>`; the branch no longer turns a relayed
  `endpoint_not_found` into the hidden-branch refusal. A scratch mutation that drops the branch
  guard fails exactly the two `endpoint_not_found` branch cases. The Engine's own refusals stay
  as they were (`test_routing_endpoint.py`, unchanged and green). SDK unchanged; one new SDK test
  pins that a `502` Gateway code is an execution failure with the rerun hint, green from the
  start.
  - `run_gates.py screamingface-engine --base origin/main` in the `uv sync --frozen --dev`
    scratch environment: ALL GATES GREEN, 7222 tests collected.
  - `run_gates.py screamingface --base origin/main`: ALL GATES GREEN.

- 2026-11-23, landing on main (Router plan section 5). The pilot branch
  `OME-1822-byom-routing-pilot` (head `89e6acfeb`) was 473 commits behind main. Worktree
  `.claude/worktrees/routing-pilot-landing`, branch `OME-1822-routing-pilot-landing` from
  origin/main `5a57d4ba6`. The 36 pilot paths were ported: 24 new files copied, five files main
  had not touched copied as they were, `world/factory.py` merged three-way without conflict, and
  six files merged by hand. Every conflict was two additions side by side, kept both:
  - `error_text.py` `__all__`: main's `PUBLIC_UNVOUCHED_CODES`, then `ROUTING_CODES`.
    `ROUTING_CODES` stays disjoint from `PUBLIC_UNVOUCHED_CODES` (`intent_error` only).
  - `tests/unit/test_url4_executor.py`: main's `world/branch.py` entry, then the pilot's
    `world/gateway_endpoints.py` entry with its comment; +3 lines against main.
  - SDK `client.py` and `__init__.py`: the `RoutedAnswer` import beside main's runs imports. Main
    no longer imports `selection` in `__init__.py`; the merge keeps that removal.
  - SDK `CHANGELOG.md`: the `route_answer` bullet goes after main's E4c and E4b bullets, before
    the `cases=` bullet. Main's docs tests pin the first Features positions (the nine E4c
    bullets, then E4b parts 4, 3, 5 and 6, and 5 before 6 before 7); the bullet placed first
    failed four of them.
  - `tests/public_surface_snapshot.json`: main's snapshot, regenerated with
    `UPDATE_SURFACE_SNAPSHOT=1`; it adds exactly the three OME-1823 entries.
  - `world/factory.py` is 416 lines (main 441). `rest/mounts.py` is 449. SDK `client.py` grows
    from 1476 to 1499 lines, the same `route_answer` delegation as before.
  - Environments: `uv lock --check` passed for both projects. Fresh scratch environments from
    `uv sync --frozen --python <v>`, the SDK with `--extra notebook` as its CI installs it.
    Engine: Python 3.12.9 and 3.13.11, url4 1.5.1, httpx 0.28.1, pydantic 2.14.3, fastapi
    0.162.2. SDK: Python 3.12.9 and 3.13.11, httpx 0.28.1, pydantic 2.14.3, anywidget 0.11.0,
    ipywidgets 8.1.9.
  - `run_gates.py screamingface-engine --base origin/main --skip-append-only`: ALL GATES GREEN
    on 3.12 and 3.13; 11143 tests collected, 385 in the routing modules.
  - `run_gates.py screamingface --base origin/main --skip-append-only`: ALL GATES GREEN on 3.12
    and 3.13; 7946 tests collected; coverage 96.9%.
  - The append-only check against origin/main reports exactly two prior-test changes, the
    OME-1822 allowlist entry and the OME-1823 snapshot. The 2026-11-04 approvals pin the old
    branch and base blobs, so both transitions need the owner's approval again on main's base
    blobs before the check can pass.

- 2026-11-23, landing review, spec 6.1 C9. A relayed classifier or branch failure reached the
  public envelope, the run's events and the runner's log with the upstream text, and with any
  `detail.code` the mount answered as a Gateway failure: a Gateway body with
  `Authorization: Bearer ...`, a path, an origin or a private model ID came back verbatim.
  - RED: `tests/unit/test_routing_relay_redaction.py` (new, 60 cases) drives both sites with
    bearer, API key, absolute and relative path, origin, private model ID and plain private text
    messages, and with path, key, model, header and real Gateway codes, through `run_direct`
    and through the App with every log record captured. 58 of the 60 cases failed on the leak.
  - GREEN: `world/gateway_endpoints.py::_relayed` rewrites every `ResolutionError` from the
    classifier or the branch before it becomes the run's terminal error: the fixed
    `ROUTED_CALL_FAILED_MESSAGE`, the permanence kept, raised `from None` so no logged traceback
    prints the cause. It replaces `_gateway_failure`. This first version kept a Gateway code
    inside a one-entry allowlist (`model_token_cap`); the second review round removed it (below).
  - Four App cases still failed: the connector's own `model call failed ... code=` log line
    reads the lifted code inside the branch's chat call, before any route's policy. A first
    shape screen in `connector._upstream_code` was tried; the second review round showed it is
    not enough and split it out of this slice (below).
  - Two assertions of this branch's own `tests/unit/test_routing_relayed_errors.py` (never
    committed) pinned the leak, `"after-send failure" in str(outcome.error)`; both now assert
    the fixed message. No committed test changed.
  - Main moved to `de16e8e94` (seven commits, none on the local paths). The branch was
    fast-forwarded to it with the work uncommitted; the two approval blob pairs are unchanged.

- 2026-11-23, landing review, second round (spec 3.5, 3.6, 6.1 C9 and C10, 9).
  - Connector split. A screen of a code's shape cannot tell a private model or deployment ID,
    an origin with a port, or a token such as `hf_...`, `ghp_...` or `sk_live_...` from a plain
    Gateway code. The owner moved the connector change out of this slice into a separate
    security unit this pilot depends on, `gateway-code-provenance` (its own worktree and ledger
    `docs/work/2026-11-23-gateway-code-provenance.md`; a closed Gateway-owned code vocabulary or
    a status-derived fallback is the owner's open choice). `world/connector.py` is back to main
    here and `tests/unit/test_gateway_code_screen.py` left with it. Until that unit lands, the
    connector's model-call log line and its observation still carry the lifted `detail.code`;
    this slice claims no log closure for that line (spec 9).
    `test_routing_relay_redaction.py` asserts the log for every message marker and for the
    classifier's codes, and the envelope for every case.
  - No Gateway code is kept. `RELAYED_GATEWAY_CODES` is removed: every `_GatewayRefusal` from
    the classifier or the branch takes `aigateway_http_<status>`, so a body naming
    `model_token_cap` no longer passes for the Engine's own diagnosis. The Engine's
    `model_token_cap` from a `length` answer is not a Gateway refusal and keeps its code. Tests:
    a Gateway body naming `model_token_cap`, `aigateway_bad_response` or `provider_refusal`
    answers `aigateway_http_400` at both sites; a real `length` answer at the branch answers
    `model_token_cap`; both with the fixed message. `test_routing_relay_redaction.py` has 64
    cases. Routing and url4 executor tests: 525 passed.
  - SDK hint (C10). An unknown profile and a classifier or branch the caller lost after the
    classifier ran share one `404 routing_profile_not_found`, and the SDK cannot tell them apart
    without the answer leaking which. RED: a new case in `tests/test_route_answer_errors.py`
    failed on the missing hint; `_engine/routed_answer.py` now gives every
    `routing_profile_not_found` the rerun and billing hint, with the `PlanningError`, `404` and
    `retryable` False kept. Three more cases pin that `400`, `409` and `414` refusals carry no
    such hint. The `route_answer` bullet in `CHANGELOG.md` says so. SDK route, classify and
    routing tests: 351 passed; docs and changelog tests: 137 passed.
  - Wording. Spec 3.3, 3.5, 3.6 and 6.1 (C8 now points to C9 and C10), `world/routing.py` and
    the routing tests refer to the relay policy of 3.5 and C9; nothing says "relayed unchanged".
  - Approvals given in chat on 2026-11-23 for branch `OME-1822-routing-pilot-landing`, and the
    historical manifests replaced by the landing manifests (Outcome).

- 2026-11-23, Phase 4 loopback integration (plan Phase 4, spec 4.3), outside Git.
  - Bundle: `.docs/byom-routing-pilot/phase4/` at the root of the main checkout, gitignored
    (`.gitignore:47`) and outside Git, not removed with the worktree. It holds
    `wrapper/model_router_v1.py` and `wrapper/test_model_router_v1.py`,
    `fakes/fake_upstreams.py` (a fake Laya and three fake chat experts), `provision/provision.py`,
    `sdk/run_cases.py`, `run_all.sh`, `RESULTS.md`, `MANIFEST.sha256`, and `run/` with the
    recorded run: `results.json`, `cases.txt`, the generated wrapper, Gateway endpoint and Engine
    world configs, every upstream's request records and every service log.
  - Integrity: `MANIFEST.sha256` pins all 39 files of the bundle and of the recorded run
    (`shasum -a 256 -c MANIFEST.sha256` from the bundle). Its own SHA-256 is
    `5e7cb56f6bb3ded61db8e833b068a586aa3f5c51851e3725709e1e20c964cb1c`. Key files:
    - `run_all.sh` `8d8b364e5b8be1e0acb227cf7bb7b37acfd71cf0f1f1f57b4f410622535ed225`
    - `wrapper/model_router_v1.py`
      `3ff8ec36524a7ed519bdfdc753ecac3a802d99ba1dd542dcd1100e830a958130`
    - `run/wrapper/model_router_v1.toml`
      `52ccff9f85927b211c2b64d6969a80d00795f525efea13a2c6292aa782142da9`
    - `run/results.json` `c412b583c36a30f28facb5f209354bf5d5f534642343869f69bfd108965a8c32`
    - `run/cases.txt` `b439483d1bb32c413756a3302c661789a7441d1002aa3044eeff4e0e71fb3665`
  - Command: from the bundle, `PE=<environments dir> WT=<pilot checkout> ./run_all.sh`. Both
    are optional: `PE` defaults to `../pilot-env`, where missing environments are built with
    `uv sync --frozen --offline`, and `WT` defaults to this worktree. The run exits 0 when every
    case passes. Each service starts
    under `env -i` with explicit variables and its working directory in the bundle, so no `.env`
    file is read; every socket is on 127.0.0.1, proxy variables point at a closed loopback port,
    and every key is a fake. On exit it stops every process and checks that no process or
    listening port is left and that the worktree's `git status --short` is unchanged (37 lines
    before and after).
  - Components: the fakes (`fake_upstreams.py <role> --port`); the wrapper
    (`model_router_v1.py --config --audit`, interim input bound 4096 bytes); the Gateway from this
    worktree (`tortoise -c aigateway.db.TORTOISE_CONFIG migrate`, then `aigateway`, an isolated
    SQLite store, `AIGW_REMOTE_ENDPOINTS_CONFIG` with the router and three expert endpoints
    granted to callers A and C, fake keys attached through the admin API: A on all four, C on all
    but `math`; caller B has no grant); the Engine from this worktree
    (`screamingface-engine serve --local`, a world file with the three private chat routes and
    `[routing.profiles.expert_router_v1]`); and the SDK's `Client.route_answer`.
  - Wrapper offline tests: 88 passed. They cover the exact body, the fixed question, refusal of
    any extra field, auth before any I/O, Laya's order with ties kept, malformed labels and
    scores, the byte bound (`413`), a reported truncation (`502`), no redirect followed, and no
    key or upstream text in any error.
  - Results: 10 of 10 cases passed in each of three runs: the bundle author's and an
    independent rerun, both from a temporary scratch directory, then a third run after the bundle
    was copied to `.docs/`. The copy changed one line, `run_all.sh` reading `PE` from the
    environment. `run/` and the hashes above are from the third run.
    - Caller A, one question per label, each asked twice in one Engine process. Each answer has
      the matching label, that expert's answer, and the scores in Laya's order. Each sent
      exactly one POST to the wrapper, to Laya and to the selected expert, every key matched,
      and the other experts got none. All six answers carry one profile revision.
    - Caller B, no grant: `PlanningError` `routing_profile_not_found`, `404`, not retryable,
      with the rerun hint (C10). No upstream POST.
    - Caller C, no `math` key: `PlanningError` `routing_connection_missing`, `409`, no hint. No
      upstream POST.
    - A tie: `ExecutionError` `routing_ambiguous`, `422`. One wrapper POST and one Laya POST, no
      expert.
    - Laya reports truncation: the wrapper answers `502`, and the routed answer fails with
      `aigateway_http_502` and the fixed message. No expert.
    - No SDK error message, hint or detail carries a fake key, `Bearer`, a `byom_` ID, an
      upstream path or a loopback origin.
  - Cold and warm: a deviation from plan Phase 4, approved by the owner in review on
    2026-11-23. Local mode builds one shared world at startup and hands it to every run
    (`local.py:378`, `:534`), so every local run is warm. A cold run is a runner child that
    builds its own world from its env (`tests/unit/test_endpoint_route_execution.py:80`).
    The approved split:
    - real Gateway and warm: this loopback;
    - fake Gateway, cold and warm, in Git:
      `test_routing_mount.py::test_a_routed_answer_is_served_cold_and_warm_with_one_revision`;
    - real Gateway and cold, through the runner pool: Phase 6.
  - Not exercised:
    - A real Laya.
    - The wrapper's TLS verification. It is configured and unit-tested, but the loopback
      upstream is plain http.
    - The access proxy. A small client transport adds the caller's identity header in its
      place.
- 2026-11-23, landing review, third round. No defect in the code, the contract or the tests;
  the merge still waits on `gateway-code-provenance` or the security owner's acceptance (spec 9).
  - Spec 4.1 still described C8's relay rule for `world/gateway_endpoints.py`; it now states
    C9's: the fixed message for every relayed failure and `aigateway_http_<status>` for every
    Gateway refusal, the permanence kept.
  - Not changed in this round: the bundle's `RESULTS.md` still shows the scratch directory in
    its reproduce step (outside Git, pinned by `MANIFEST.sha256`; the location and command in
    the Phase 4 entry above are the durable ones), and the preflight reads, like the
    connector's other Gateway reads, have no byte bound.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** 37 paths on base `de16e8e94`: the 36 pilot paths and the new
  `tests/unit/test_routing_relay_redaction.py`.
  - Engine source: `error_text.py`, `rest/mounts.py`, `world/classification.py`,
    `world/config.py`, `world/factory.py`, `world/serving.py` (changed);
    `world/gateway_endpoints.py`, `world/routing.py`, `world/routing_config.py` (new).
    `world/connector.py` is unchanged (the `gateway-code-provenance` unit).
  - Engine tests: `tests/unit/test_url4_executor.py` (one allowlist entry); new
    `routing_support.py`, `test_routing_config.py`, `test_routing_endpoint.py`,
    `test_routing_mount.py`, `test_routing_preflight.py`, `test_routing_relayed_errors.py`,
    `test_routing_relay_redaction.py`, `test_routing_run_cost.py`, `test_routing_world.py`.
  - SDK: `CHANGELOG.md`, `__init__.py`, `_engine/classification.py`, `client.py`,
    `tests/public_surface_snapshot.json` (changed); `_engine/direct_get.py`,
    `_engine/routed_answer.py`, `routing.py`, `tests/_route_answer_fixtures.py`,
    `tests/test_route_answer.py`, `tests/test_route_answer_errors.py` (new).
  - Process: `.claude/test-change-approvals/OME-1822.json` and `OME-1823.json`; the spec, plan,
    this ledger and the OME-1822 and OME-1823 mirrors.
- **Approvals:** given in chat on 2026-11-23, both on branch `OME-1822-routing-pilot-landing`,
  and pinned in `.claude/test-change-approvals/OME-1822.json` and `OME-1823.json`, which replace
  the 2026-11-04 manifests. OME-1822: `test_url4_executor.py`
  `4a2ba578bf287b89d721d8329e202774269666a6` -> `6424f96fc2c7cccc88b2da6bd7c44b95d1b06081`,
  exactly the one `world/gateway_endpoints.py` allowlist entry with its comment. OME-1823:
  `public_surface_snapshot.json` `cc6e32c7294c58fe167cd57a9e853b2ab4cb1410` ->
  `e5b423b7e322f7c164b2bcadf6d173c12c871c63`, exactly the `RoutedAnswer` class with its
  `__init__`, the root export and `Client.route_answer`.
- **Commits:** three on `OME-1822-routing-pilot-landing`: `11debbb00` (the Engine route),
  `2ebf9daef` (`Client.route_answer`) and `f136c92e1` (the spec, plan and ledger).
  [PR #2016](https://github.com/ScreamingFace/screamingface/pull/2016) (head `f136c92e1` on
  `de16e8e94`) was squash-merged on 2026-11-24 as `343aea663`, after `gateway-code-provenance`
  (`afe8ec8ea`). The PR head did not contain `afe8ec8ea`; on `main` at `343aea663`, which holds
  both, the Engine run passed on Python 3.12 and 3.13 with the image build, and E2E Replay,
  ScreamingFace Tests and CodeQL passed. OME-1822 and OME-1823 stay In Progress: Phases 5 and 6
  are pending.
- **Gates:** on base `de16e8e94` with the landing manifests installed,
  `run_gates.py screamingface-engine --base origin/main` and
  `run_gates.py screamingface --base origin/main`, with no step skipped: ALL GATES GREEN on
  Python 3.12 and 3.13, including the approved OME-1822 and OME-1823 transitions and the
  append-only check. The first Engine run failed only at ruff (one new test line over the
  length limit); the line was split and both Engine runs were repeated green.
- **Phases:** 1 to 3 green on both stacks, the working diff reviewed. Phase 4 done and recorded
  above: 10 of 10 loopback cases passed, in three runs. Phase 5 (live pilot) is pending on the
  operator inputs of spec 7. Phase 6 (hosted proof) is pending.
- **Merge gate (owner review, 2026-11-23):** the pilot does not merge before the
  `gateway-code-provenance` unit lands, or before the security owner explicitly accepts the
  known risk. Until then, the connector's model-call log line and `observation.failed()` can
  record an upstream `detail.code`, such as a private deployment ID, an origin with a port, or an
  `hf_`, `ghp_` or `sk_live_` token, for any chat, classification or frozen-copy call. The
  route's own answer, run events and runner log are closed here (spec 3.5, 9). Released on
  2026-11-24: `gateway-code-provenance` merged first, as `afe8ec8ea`
  ([PR #2025](https://github.com/ScreamingFace/screamingface/pull/2025)).
- **Not claimed:** live and hosted qualification. Local in-process evidence does not establish
  hosted Linux, NATS and JetStream execution; no Router Recipe, Fusion or live claim.
- **Deviations:**
  - `world/factory.py` reached 474 lines (spec 6.1 C3). Resolved: the endpoint registration
    moved unchanged to `world/gateway_endpoints.py`, 102 lines then and 144 with the C9 relay;
    `factory.py` was 406 lines then and is 416 on main's base. The move changes one prior test,
    `tests/unit/test_url4_executor.py`, by exactly one allowlist entry, first approved in chat
    on 2026-11-04 and approved again on main's base blobs on 2026-11-23 (Approvals above).
  - The connector's code screen left this slice for the `gateway-code-provenance` unit at the
    owner's decision; the pilot claims no closure of the connector's model-call log line until
    it lands (spec 9), and does not merge before then without the security owner's acceptance
    (Merge gate above).
  - A classification result for another model or contract is `aigateway_bad_response` from
    Unit 3, not `routing_invalid_scores` (spec 6.1 C1).
  - `classification.refuses_query` is replaced by `undecodable_query`; `rest/mounts.py` maps the
    two direct text routes to their messages, so `_validated` stays within the lint limits and
    the file at 449 lines.
  - SDK `client.py` grows from 1476 to 1499 lines on main's base (1062 to 1085 on the pilot's
    base) with the `route_answer` method. The file was
    over the limit before; the method only delegates to `_engine/routed_answer.py`, and D2 puts
    it on `Client`.
