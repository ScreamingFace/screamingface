---
ticket: OME-2042
stack: screamingface
status: in_progress
started: 2026-11-26
finished:
---

# sdk-runtime-upstream-attempts - packaged runtime compatibility proof

## Intent

Complete the Client SDK half of Router Recipe extension Unit 5.1 by proving that the packaged
`runtime` extra preserves physical upstream-attempt evidence for the generic Hugging Face and Ollama
LiteLLM paths. The proof must detect an unobserved send or hidden resend while keeping provider
traffic, credentials and product behavior out of scope.

## Planned changes

- Add `packages/screamingface/tests/e2e/test_runtime_router_transport_attempts.py`.
- Add the OME-2042 task mirror and this ledger at PR-open.
- Do not modify Gateway source, workflows, manifests, locks or prior tests.

## Test plan

- Boot the real SDK runtime Gateway under the exact `runtime` lock in fresh Python 3.12 and 3.13
  environments.
- Exercise Hugging Face and Ollama with taxonomy accounting enabled and disabled.
- Assert one physical send reports `1` and a real LiteLLM hidden resend reports `2`.
- Compare the header with requests observed at the fake physical transport and pin the provider URL.
- Remove both Gateway injection paths as a negative control and require the false-zero check to fail.
- Run static checks, E2E discovery and the complete Client SDK quality gate.

## Acceptance

- The runtime lock resolves LiteLLM `1.104.5` and the Gateway imports from the packaged checkout
  source selected by the SDK runtime.
- The full positive and negative matrix passes under Python 3.12 and 3.13 without external provider
  traffic.
- The existing E2E Replay workflow discovers the test without modification.
- Client SDK project gates pass and the diff remains additive and test-only apart from this ledger and
  mirror.

## Outcome

- **Actual files:** the planned runtime E2E test, this ledger and the OME-2042 task mirror.
- **Commits:** this PR; one conventional test commit referencing OME-2042.
- **Gates:** Python 3.12 and 3.13 runtime matrices each passed 20 tests; static checks passed; E2E
  discovery collected all 20 cases; `run_gates.py screamingface` completed with all gates green.
- **Deviations:** LiteLLM attempts a synchronous Hugging Face model-metadata lookup outside the
  observed inference client. The test refuses that lookup, permits no connection, and treats it as a
  separate follow-up rather than an upstream inference attempt.
