---
ticket: OME-2052
stack: screamingface
status: done
started: 2026-11-27
finished: 2026-11-27
---

# sdk-engine-capability-reader — read Engine capabilities before a gated submission (C12, Unit 6)

## Intent

Add the SDK side of the C12 capability gate
(`docs/spec/2026-11-16-router-recipe-extension/contracts.md`, C12). The Engine already serves
`GET /v1/capabilities`, the closed `engine-capabilities-v1` document. This unit adds the SDK's one
strict codec for that document and a fresh sync and async reader. It also adds a private
pre-submit check in the Evaluation runner. The check runs after compilation and before the model
preflight, the token mint, `POST /runs`, the root `GET /?q=`, registration and the follow.

The reader is dormant: every current caller requires no capability, so no request is made. A
later Router writer derives the required IDs; this unit adds no public type, writer or
activation.

## Planned changes

- `packages/screamingface/src/screamingface/_engine/capabilities.py` (new): the strict codec,
  the requirement check and a sync and async reader bound to the Client's Engine GET.
- `packages/screamingface/src/screamingface/_evaluation/runner.py`: two private parameters on
  `evaluate_sync` and `evaluate_async`, `required_capabilities` (empty by default) and
  `require_capabilities` (the injected reader). The check sits right after compilation.
- `packages/screamingface/src/screamingface/client.py`: `Client` and `AsyncClient` build one
  reader over their existing Engine GET and pass it to the runner. They pass no requirement.
- `packages/screamingface/tests/test_engine_capabilities.py` (new): codec and reader cases.
- `packages/screamingface/tests/test_evaluation_capabilities.py` (new): runner, composition and
  no-request cases.

No change to `errors.py` (`EngineCapabilityError` exists), the package exports, the public
surface snapshot, the default client, the run client, the run transport, the Engine, the Gateway,
the chart, CI or any lock file.

## Test plan

Each case is written first and must fail first.

- **Codec.**
  - The exact dormant document decodes to an empty `frozenset`.
  - Unique IDs in lexical order decode; unknown IDs are kept and ignored unless required.
  - Refused, each as `EngineCapabilityError`:
    - a repeated key;
    - an extra or missing key;
    - a wrong `object` or `contract`;
    - `capabilities` that is not a list;
    - an ID that is not a string, or is empty;
    - a duplicate ID, or IDs out of lexical order;
    - a non-finite number;
    - text that is not JSON, including bad UTF-8 and nesting too deep to decode.
- **Reader.**
  - 404 and other non-success answers raise `EngineCapabilityError`.
  - 401/403 raise `AuthenticationError`, and a transport failure raises
    `EngineUnavailableError`, in the same categories as the Model catalogue on the same answer.
  - A missing required ID raises `EngineCapabilityError` naming it.
  - Each call is a fresh GET with no conditional header. A positive answer followed by a
    withdrawn one fails the second call.
- **Runner, sync and async.**
  - An empty requirement never calls the reader, and the request sequence is unchanged.
  - A missing ID refuses after the benchmark load and one capability GET. There is no Model
    listing or details call and no registration or follow, including with `detach=True`.
  - A present ID costs exactly one GET, after compilation and before the Model listing; the run
    then proceeds once.
  - Two submissions read twice.
  - A requirement with no reader fails closed.
- **Composition and capability-free flows.**
  - `Client.evaluate` and `AsyncClient.evaluate` pass a reader bound to their Engine and no
    requirement.
  - Ordinary Recipe evaluation, a raw URL4 and `route_answer` make no capability request.
- **Regression.** The existing evaluate, default-client, frozen-copy, route-answer, outcome-runner
  and follow suites, and the public-surface snapshot, are rerun unchanged.

## Acceptance

- The strict decoder refuses every malformed and duplicate case.
- Two submissions read twice, and an empty requirement makes no GET.
- Every refusal comes before model discovery, the token mint, registration, the root GET and the
  follow. Auth and transport failures keep their categories.
- Ordinary evaluation, legacy URL4, `route_answer` and replay/follow are request-identical.
- No prior test changes. New files are at most 450 lines.
- The SDK gates are green on Python 3.13 and 3.12, and the repo gates are green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, and no others.
  - New: `_engine/capabilities.py` (143 lines), `tests/test_engine_capabilities.py` (289
    lines), `tests/test_evaluation_capabilities.py` (366 lines).
  - Modified: `_evaluation/runner.py` (+65/-1) and `client.py` (+9).
  - No prior test changed.
- **Commit:** one, `573f4a462` on `OME-2052-sdk-engine-capability-reader`, holding the
  implementation, this ledger and the task mirror, on base `456b9cba`.
  [PR #2097](https://github.com/ScreamingFace/screamingface/pull/2097) was squash-merged on
  2026-11-27 as `7ec6329e2`. At the merged head, 22 CI checks passed and 14 were skipped; none
  failed or remained pending.
- **RED first:**
  - The codec file failed collection: the module did not exist.
  - The runner file had 16 failures:
    - the Clients had no reader;
    - the runner refused `required_capabilities`;
    - `evaluate` passed no `require_capabilities`.
  - The 5 capability-free guards passed before and after, as intended.
- **Gates:**
  - `run_gates.py screamingface` on Python 3.13: ALL GATES GREEN.
  - Python 3.12 (the CI matrix floor), with `--extra notebook` as in CI:
    - ruff check and format clean;
    - pyright 0 errors;
    - pytest 8729 passed, 54 skipped, total coverage 97.01%.
  - The same pytest on 3.13 gives the same counts and coverage.
  - The new module has 100% line coverage. Every added line in `runner.py` and `client.py` is
    covered.
  - `run_gates.py repo`: ALL GATES GREEN. `git diff --check` is clean.
- **Mutation controls:** 20 behavioral mutants, each run against the two new test files; all 20
  were killed. The files were restored byte-exact, and their sha256 was verified. The mutants
  covered:
  - codec: repeated keys, extra keys, unchecked object or contract, an empty ID, unchecked
    order, a leaked `RecursionError`;
  - reader: 404 folded into other statuses, 5xx marked permanent, auth turned into a capability
    error, the missing set reversed, the sync or async reader keeping its first answer, an
    unmapped async transport error;
  - runner: an empty requirement asking, no reader failing open, the async check not awaited,
    the sync or async check moved after the model preflight;
  - composition: either Client passing no reader.
- **Deviations:**
  - **Port shape.** The runner takes a `require` callable, not a loader of the advertised set.
    The codec and the requirement check therefore live in one module, and `_evaluation` never
    imports `_engine`.
  - **No reader.** A nonempty requirement with no reader fails closed with
    `EngineCapabilityError` (`details.missing`); it never submits unchecked.
  - **Lexical order.** The reader enforces it, so a reordered list is refused as
    `engine_contract_error`. C12 says the Engine emits lexical order; reading that as a rule
    the reader enforces is a strict, fail-closed choice. Reviewers should confirm it.
  - **ID validity.** Only the empty string is refused as an ID. Whitespace-only IDs are
    accepted, because C12 asks only for nonempty strings.
  - **Status mapping.** 404 maps to `engine_capability_missing` with a hint naming
    `GET /v1/capabilities`. Any other non-success answer also maps to
    `engine_capability_missing`, retryable from 500 up.
  - **Order of calls.** The check runs after compilation, so a capability refusal follows the
    benchmark load. It precedes the model listing, details, mint, registration, root GET and
    follow, as the acceptance requires.
  - **Out of scope.** No public Router writer, required-ID derivation or capability activation
    is in this unit. Every current caller requires nothing, so no capability request is made.
