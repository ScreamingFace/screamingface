---
ticket: OME-962
stack: screamingface
status: done
started: 2026-08-25
finished: 2026-08-25
---

# OME-962 — Rehearse provider failure paths against a scripted fake gateway

## Intent

The e2e replay cache (OME-961) can only replay good news — failed provider calls never
store a cache entry — so the bad-news paths are unrehearsed. This unit adds a
`FakeGateway` stand-in (implements the harness `ReplayBackend` port, failure-injection
only, zero egress) plus hand-authored failure tapes, and proves each provider failure
(429, 5xx, malformed body, blank completion, judge cut off mid-batch) lands exactly
where the board's declared failure policy says — e.g. a 429 surfaces as a
rate-limit/provider error with retryable=True, never as "malformed response".
Requirement R7 of parent OME-956.

## Planned changes

- `packages/screamingface/tests/e2e/harness/fake_gateway.py` — new: FakeGateway
  implementing `ReplayBackend`; serves only its Tape; unmatched request fails loudly.
- `packages/screamingface/tests/e2e/fixtures/failures/*.json` — hand-authored
  `RecordedExchange` tapes (`provenance.authored=True`), raw provider-shaped bytes.
- `packages/screamingface/tests/e2e/test_failures.py` — new: engine+SDK vs FakeGateway,
  asserts each failure lands per declared policy (e2e lane).
- FakeGateway contract tests live in `test_failures.py`'s default-lane section (NOT in
  `test_harness_contracts.py` — the sibling OME-964 worktree may touch that file, so
  the footprint stays in this unit's own files; same style either way).
- No conftest edits needed; no edits to cache_seeded.py/stack.py/ports.py/tape.py/
  goldens.py (OME-964 works in the same tree).

## Test plan

- RED-first unit tests: unmatched request → loud error (no default response);
  authored-flag required on failure fixtures; FakeGateway binds loopback only /
  cannot egress; serves exactly the recorded bytes+status.
- RED-first e2e tests (e2e marker + SCREAMINGFACE_TEST_E2E=1 + docker probe):
  per failure scenario, CaseResult.failures[] carries the declared stage/code/
  retryable — invariant named in each test.
- Fixture validation tests (default lane): failure tapes parse as RecordedExchange,
  authored=True, bodies are raw provider-shaped bytes.

## Acceptance

- Default lane fully green; e2e lane green with the new failure scenarios.
- Every authored failure shape maps to its declared landing (policy table with
  file:line evidence from the engine in the report).
- Zero network egress and zero spend possible by construction.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `packages/screamingface/tests/e2e/harness/fake_gateway.py` (new — FakeGateway,
    stdlib ThreadingHTTPServer on 127.0.0.1:0, tape-scripted, zero egress by
    construction)
  - `packages/screamingface/tests/e2e/fixtures/failures/{rate_limit_429,provider_5xx,
    malformed_body,blank_completion,judge_cutoff}.tape.json` (new — authored tapes,
    `provenance.authored=true`, raw gateway-shaped bytes)
  - `packages/screamingface/tests/e2e/test_failures.py` (new — 11 default-lane
    FakeGateway/fixture contract tests + 5 e2e scenario tests; FakeGateway unit tests
    live here instead of `test_harness_contracts.py` to avoid colliding with the
    OME-964 sibling worktree)
  - No edits to cache_seeded.py / stack.py / ports.py / tape.py / goldens.py /
    conftest.py — zero shared-file footprint.
- **Commits:** uncommitted — pending local owner review
- **Gates:** ruff check+format clean; pyright 0 errors on the new files; default lane
  1121 passed / 1 skipped (includes the 12 FakeGateway/fixture contract tests);
  e2e lane (SCREAMINGFACE_TEST_E2E=1, full `-m e2e`) 9 passed / 5 skipped (board
  goldens not recorded yet — the honest OME-961 skip) — all 5 failure scenarios proven
  against the real engine + SDK, plumbing tests green too. Machine setup note: the
  gitignored `synthetic.manifest.json` had to be regenerated once via the OME-961
  `generate_synthetic.py` (aigateway venv) before the plumbing fixtures could boot;
  no tracked file changed (regenerated snapshot/tape are byte-identical).
- **Deviations:**
  - FakeGateway is a stdlib `ThreadingHTTPServer`, not uvicorn: the SDK test venv
    carries no ASGI server, and uvicorn would have meant a pyproject dep change or
    borrowing another app's venv. Stdlib keeps the footprint to this unit's files and
    is the stronger zero-egress claim (the module holds no HTTP client at all).
  - The fake matches tape exchanges by MODEL, not by cache fingerprint — an authored
    tape cannot pre-compute the gateway `key_hash` of bodies the engine composes at
    run time; the tape fingerprint stays a row identity only.
  - The fake also serves `GET /v1/models` as a projection of EXACTLY the tape's models
    (gateway locked row shape): the SDK's run planning reads the engine catalogue
    (which proxies that route) before any model call, so the discovery half of the
    seam is required to even reach the completions seam.
  - Review nits fixed (owner review, approve-with-nits): (1) every refusal reply now
    sends `Connection: close` — the unroutable POST branch refuses before reading the
    body, and on a kept-alive connection the unread bytes would garble the next
    request and mask the real refusal; closing was chosen over draining because it is
    simpler and also covers chunked bodies Content-Length cannot measure (pinned by
    a new contract test: refused POST → close header, follow-up call still served
    from the tape). (2) `_rehearse` now asserts ALL refusals are empty, not just
    unmatched-model ones — verified strict against all 5 e2e scenarios; the engine
    makes zero off-surface requests today, so no tolerated-probe list was needed.
  - Finding (not fixed here — url4 core is out of scope on benchmark PRs): the
    connector's failure classification (`code`, `permanent`) is dropped at the url4
    `on_error="collect"` boundary (`url4/dag/nodes.py::_error_payload` keeps only
    kind+message), so candidate-stage Failures land with the board default code
    `case_execution_failed` and `retryable=None`; the gateway-authored MESSAGE is what
    distinguishes 429/5xx/malformed today. Candidate ticket for url4 if the code/
    retryable fidelity is wanted end-to-end.
