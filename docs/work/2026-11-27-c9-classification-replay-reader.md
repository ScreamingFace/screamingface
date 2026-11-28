---
ticket: OME-2055
stack: aigateway
status: done
started: 2026-11-27
finished: 2026-11-27
---

# c9-classification-replay-reader — read recorded classifications without live I/O

## Intent

Add the dormant Gateway reader half of the Unit 6 C9 classification frozen-copy contract. A replay
request names its Router binding, occurrence and numbered attempt, reads only a sealed copy, and
returns the recorded classification success or error with replay-only Gateway accounting. It never
resolves a provider, plugin, Connection, credential or cache, and adds no capture writer or Engine
writer. Existing chat/tool digests, merged blob-reference semantics and the shared unavailable
response remain unchanged.

## Planned changes

- `apps/aigateway/src/aigateway/core/frozen_copy/headers.py`: add strict classify-only binding and
  attempt headers while leaving the chat/tool call-key parser unchanged.
- `apps/aigateway/src/aigateway/core/frozen_copy/store.py`: add `classify` and the exact
  binding-aware digest/read parameters, preserving the merged reference-aware `files` path and
  byte-identical chat/tool digests.
- `apps/aigateway/src/aigateway/routes/frozen_copies.py`: add only
  `POST /v1/frozen-copies/{id}/classifications`, reusing the sealed-copy resolver and replay
  accounting helpers, with no live fallback.
- `apps/aigateway/tests/unit/test_frozen_copy_classification_store.py` (new): strict headers,
  canonical key shape and store separation by binding, occurrence and attempt.
- `apps/aigateway/tests/unit/test_frozen_copy_classification_replay.py` (new): success/error,
  accounting, authority, availability and zero-live-I/O route cases.
- `apps/aigateway/tests/unit/test_frozen_copy_support.py`: only after owner approval of the exact
  old/new blobs, extend the test-only entry helper to `classify`; do not edit before approval.
- This ledger.

No model, migration, live classification route, capture writer, Engine/SDK writer, middleware,
taxonomy, error-code fixture, config, chart, dependency or lock change.

## Test plan

Each new test is written first and fails for the missing contract.

- **Headers and digest.** Refuse missing/malformed binding and attempt before store lookup;
  `router_N` only; Attempt 1 is absent and later attempts start at 2. Pin the exact canonical
  `{kind, request, binding[, attempt]}` preimage and prove chat/tool digests and #2068 reference
  semantics stay unchanged.
- **Store.** Identical `{model,input}` under two bindings, occurrences and Attempts 1/2 never
  cross-hit. No revision, policy, price, media, credential or auth value enters the key.
- **Success replay.** Preserve scalar fields/status; add `X-AIGW-Replay: hit`,
  `X-AIGW-Upstream-Attempts: 0`, cache-hit accounting and `direct_cost_status=not_applicable`.
  Missing/malformed, measured-zero and positive captured references project exactly.
- **Recorded error.** Preserve status, `detail` and supported `Retry-After`; add replay error and
  zero-attempt headers; reference is null.
- **Authority and availability.** Capture stays owner-write; any authenticated caller holding a
  sealed id may replay. Miss, unknown, malformed, open, abandoned and current expired copies match
  chat replay. Invalid body/key refuses with zero store/provider work.
- **Independence/regression.** A hit works after provider removal and with no Connection,
  credential, plugin or cache. Rerun chat/tool replay, provenance, live classification, upstream
  attempt and #2068 reference-key suites unchanged.
- **Mutation controls.** Mutate binding out of the digest, Attempt 1 into the digest, occurrence or
  attempt forwarding, provider lookup/live fallback, recorded-error metadata, price projection and
  the shared unavailable resolver; every mutant must be killed and restored byte-exact.

## Acceptance

- Exact C9 key and strict headers; success/error replay with Gateway-authored zero-live accounting.
- No live provider/plugin/Connection/credential/cache lookup and no writer/activation.
- Chat/tool/reference digests and shared unavailable semantics unchanged.
- Sole prior-test transition has exact owner approval before edit; no other prior test changes.
- Focused tests and mutations green; full AIGateway gates on Python 3.12 and 3.13 and repo gates
  green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** exactly as planned, seven paths and no others.
  - Product: `core/frozen_copy/headers.py`, `core/frozen_copy/store.py`,
    `routes/frozen_copies.py`.
  - New tests: `test_frozen_copy_classification_store.py` and
    `test_frozen_copy_classification_replay.py`.
  - Approved prior-test transition: `test_frozen_copy_support.py`
    `e297e0c3e1363c7c42c1284702f2f69f5343fb00` to
    `24a6cf7928434b33525fe7aa1cdb6b6df3e7e5ea`. The earlier proposal is superseded because
    its positive helper used invalid `router_0`.
  - This ledger.
- **Commit:** this ledger ships in the same publication commit as the implementation; the branch
  history and PR record its exact SHA.
- **RED first:** the two new files failed collection because C9's `ATTEMPT_HEADER` did not exist.
  The canonical-binding regression then failed six cases because the first candidate admitted
  `router_0` and `router_01` at parser, store and HTTP-route ingress.
- **Gates:**
  - New C9 tests plus gateway-code provenance: 55 passed.
  - Frozen-copy, classification, upstream-attempt and #2068 reference regressions: 698 passed on
    Python 3.12 and 698 passed on Python 3.13.
  - Full `run_gates.py aigateway` on Python 3.12 and 3.13, with only the explicitly deferred
    append-only check skipped: all format, lint, type, no-enterprise, pytest and coverage gates
    green.
  - `run_gates.py repo --skip-append-only`: all repo gates green. `git diff --check` clean.
  - The no-skip gate stops only on the approved prior-test pair because the manifest is added at
    PR-open; bind the corrected exact pair then and rerun the unskipped gates. Never publish the
    superseded proposal.
- **Mutation controls:** 11 of 11 killed and restored byte-exact: binding/attempt grammar, binding
  and Attempt 1 digest fields, capture/find binding forwarding, route occurrence/attempt forwarding,
  error-reference nulling, success price projection and the shared sealed-copy resolver.
- **Deviations:**
  - Correctness review required one-based canonical Router bindings. Parser, store and route now
    accept only `router_[1-9][0-9]*`; zero, leading zero, plus, space and Unicode digits refuse.
  - Both replay paths use the existing reviewed `replay_chat_completions` error-projection site, so
    the exact gateway-code provenance contract remains satisfied without another prior-test edit.
  - Classification replay reuses the live route's pre-credential `_model_and_input`; no provider,
    grant, credential, limit or dispatch work is reached.
  - `routes/frozen_copies.py` is exactly 429 lines, below the 450-line card limit.
  - Python 3.14.2 alone makes one existing deep-JSON test expect `RecursionError` after the decoder
    instead returns the decoded list; the same failure reproduces on a clean base worktree. The
    required Python 3.12/3.13 matrices are green and no prior test was changed for this baseline.
