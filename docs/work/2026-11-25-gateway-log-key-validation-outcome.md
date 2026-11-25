---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: aigateway
status: done
started: 2026-11-25
finished: 2026-11-25
---

# gateway-log-key-validation-outcome — log which validation call refused a provider key

## Intent

Before the AI Gateway stores a provider key it checks the key with two outbound calls:
authentication, then readiness (a minimal inference). Seven outcomes share four HTTP statuses,
and `unavailable` and `misconfigured` both answer 503. The response body names the stage and
state, but the gateway logged nothing, so when a client flattens the body the operator has a
bare `POST /v1/oauth/connections/api-key 503` in the access log and no cause. Paid smoke run
[45538646440](https://github.com/ScreamingFace/screamingface/actions/runs/45538646440) died on
exactly that line: the SDK reported "AI Gateway is unavailable" and neither log said which
OpenRouter call had failed. Fix: one log line per refused validation, naming provider, state,
stage and probe model.

## Planned changes

- `apps/aigateway/src/aigateway/routes/api_key_validation.py` — `run_api_key_validation` logs
  one `api_key_validation_refused` line for every result that is not `valid`.
- `apps/aigateway/tests/unit/test_api_key_validation_writer_integration.py` — three tests
  through the real route, service, validator and bounded session.

## Test plan

- An unavailable validation (a non-JSON body on the first call) logs one WARNING naming
  `stage=authentication`.
- A rejected key logs one INFO line; the key and the provider's own words never reach the log.
- A valid key logs nothing.

## Acceptance

- A 503 on connecting a key is traceable to one of the two calls from the gateway log alone.
- No response body, status or error code changes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** one commit on `gateway-log-key-validation-outcome`.
- **Gates:** relevant tests only, per owner rule: the 78 gateway test files that touch the
  key-validation or connection routes → 1,126 passed, 22 skipped (they include
  `test_api_key_validation_writer_integration.py`, `test_api_key_validation_contract.py` and the
  error-code check `test_gateway_error_codes.py`); ruff check + format and pyright clean on the
  two touched files. Full suite left to CI.
- **Deviations:** (1) The line is written in `run_api_key_validation`, not only on the write
  path, so the `/validate` route logs it too: one site covers every caller. (2) The line does
  not carry the provider's HTTP status: the validation result does not hold it, and adding it
  means changing every provider's validator. Stage plus state answers "which call"; the status
  is a follow-up only if a 503 is still ambiguous in practice.
