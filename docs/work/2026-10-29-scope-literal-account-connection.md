---
ticket: OME-1781, OME-1782, OME-1783   # gateway, SDK fixtures, Engine fixture; parent epic OME-1138
stack: aigateway, screamingface, screamingface-engine
status: done
started: 2026-10-29
finished: 2026-10-29
---

# scope-literal-account-connection — rename the model-parameter contract scope to account_connection

## Intent

The `/v1/model-parameters` document publishes `context.scope = "account_profile"`, a Profile-era
name for what is now a Connection-bound contract. The owner decided on 2026-10-29 to rename the
literal to `account_connection` (close-out leaf L6 of epic `OME-1138`; spec
`docs/spec/2026-10-29-ome-1138-closeout.md` §4.6, §6 and §8; plan
`docs/plan/2026-10-29-ome-1138-closeout.md` §2 and §3 "L6a/b/c"). `scope` is a digest input, so
`contract_id` and `context.revision` rotate once; the owner accepted that rotation. Nothing in the
repo persists either identity. The SDK decodes `scope` as free text, so an old SDK accepts the new
value. The gateway, SDK fixtures and Engine fixture move in one PR (one release train), filed as
three sub-issues, one per landing.

## Planned changes

- Gateway (L6a, `aigateway`):
  - `apps/aigateway/src/aigateway/routes/model_parameters.py` — the one producer passes
    `scope="account_connection"`.
  - `apps/aigateway/src/aigateway/core/model_parameter_contract.py` — the composer docstring
    "(model, profile)" becomes "(model, connection)".
  - Tests carrying the literal (§4.6): `tests/unit/test_model_parameters_route.py`,
    `tests/unit/test_model_execution_access.py`, `tests/unit/core/test_model_parameter_contract.py`,
    `tests/unit/core/test_auth_applicability_contract.py`,
    `tests/unit/core/test_contract_source_revision_identity.py`,
    `tests/unit/core/test_provider_contract_conformance.py`,
    `tests/unit/core/test_provider_contract_conformance_hardening.py`, the anthropic, gemini and
    huggingface `*_parameter_overlay.py`, and openrouter `catalog_evidence`,
    `openapi_endpoint_route`, `parameter_overlay`, `routing_policy` and `top_p_promotion`.
- SDK fixtures (L6b, `client-sf`): `packages/screamingface/tests/_model_parameter_fixtures.py`,
  `tests/e2e/harness/fake_gateway.py`, `tests/test_model_parameter_discovery.py`,
  `tests/test_panels_opt_out_of_maths.py`, `tests/test_rich_display.py`. No src change.
- Engine fixture (L6c, `screamingface-engine`):
  `apps/screamingface-engine/tests/unit/test_model_parameters_proxy.py`. No src change.
- `.claude/test-change-approvals/OME-1781.json` covering every changed prior test file (§6).
- `docs/tasks/` mirrors for the three sub-issues.
- Release note (plan §3 "L6a/b/c"): the squash title is a visible `refactor(aigateway)` commit,
  and the PR body states that the scope literal is renamed and `contract_id` and
  `context.revision` change once.

## Test plan

- RED: `test_model_parameters_route.py` expects `context.scope == "account_connection"` on the
  served document (fails against the current producer).
- New contract test in `test_model_parameter_contract.py`: both digests move when only the scope
  changes, so the rename rotates `contract_id` and `context.revision` exactly as the release note
  says (holds today; pins the stated consequence).
- GREEN: producer and docstring; then the remaining fixtures switch to the new literal with no
  assertion weakened.
- Full stack suites through the gates: `aigateway`, `screamingface`, `screamingface-engine`.

## Acceptance

- The gateway serves `context.scope = "account_connection"`.
- After this unit, `account_profile` appears only in history docs (`docs/work`, `docs/tasks`,
  dated specs and plans).
- All three stack gates green; every changed prior test file is in the manifest.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Gateway: the producer, the composer docstring and 15 test modules
  (the new test lives in `test_model_parameter_contract.py`). SDK: 5 test files. Engine: 1 test
  file. Plus `.claude/test-change-approvals/OME-1781.json` (21 files, base and approved blobs),
  this ledger, and the mirrors `docs/tasks/2026-10-29-OME-1781-…-gateway.md`, `…-OME-1782-…-sdk.md`
  and `…-OME-1783-…-engine.md`.
- **Commits:** see branch `OME-1781-scope-literal-account-connection` —
  `refactor(aigateway): rename the contract scope to account_connection`.
- **Gates:** `run_gates.py <stack> --base origin/main`, each ALL GATES GREEN with the append-only
  check passing on the OME-1781 approvals:
  - `aigateway`: ruff, format, pyright, no-enterprise, pytest cov>=80 (full suite on this code:
    7274 passed, 107 skipped).
  - `screamingface`: ruff, format, pyright, pytest cov>=95 (4936 passed, 38 skipped), notebooks,
    build, distribution.
  - `screamingface-engine`: ruff, format, pyright, layering, pytest cov>=80 (5879 passed,
    153 skipped).
- **Deviations:**
  - Spec §4.6 and §6 say "16 gateway test modules"; its own list and the grep give 15.
  - `test_model_execution_access.py` carried the old literal only in a test name; the test is
    renamed to `test_other_account_connection_does_not_grant_access`, body unchanged.
  - Left as is (outside this leaf): the module docstring of `core/model_parameter_contract.py`
    still says "FEATURE: profile-bound detailed parameter contract", and test fixtures still use
    `prof:` tokens in `context_identity` strings. Profile vocabulary there belongs to the later
    vocabulary leaves (L4b/L5).
  - Gate environment: the SDK suite's e2e harness (`tests/e2e/harness/inspect_stack.py:38`) runs
    `uv sync --extra benchmarks` inside `apps/screamingface-engine`. Run in the same checkout
    before the Engine gate, it installs 77 extra packages into the Engine venv, and the Engine
    gate then fails pyright on untouched `tests/unit/inspect/` modules. `uv sync --locked` in the
    Engine restores it; the Engine gate above ran after that. Pre-existing; reported, not fixed
    here. Separately, the Engine pytest step stalled twice under heavy machine load (every xdist
    worker idle on its control channel, once while the SDK gate ran concurrently); the cause was
    not isolated, and the identical step later passed in about 30 seconds.
  - Two timing-sensitive tests failed once under heavy machine load and passed on rerun:
    `aigateway` `test_unknown_user_timing_close_to_wrong_password` and two SDK
    concurrent-interrupt tests in `test_client_run.py`. No code here touches them.
