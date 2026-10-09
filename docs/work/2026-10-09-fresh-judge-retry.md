---
ticket: OME-1533
stack: screamingface-engine
status: done
started: 2026-10-09
finished: 2026-10-09
---

# fresh-judge-retry — a hand-built judge retry gets a fresh reply, not the cached garbled one

## Intent

healthbench, gdpval-text and draco grade each rubric item by asking a judge model. When the
judge's reply does not parse, the verdict route fails with `judge_reply_invalid` and url4's
`;retry=` asks the judge again. That retry sends the same bytes under the run's own cache
policy, and the AI Gateway's global request cache already stored the garbled reply, so every
retry gets the same garbled reply back and the Case fails anyway. This unit makes the retry
that follows an unparseable judge reply leave the cache for that one call, reusing the
existing per-request opt-out (`CachePolicy(participate=False)` → body
`{"cache": {"use-cache": false}}`), so the retry gets a fresh sample.

## Planned changes

- `packages/url4/src/url4/dag/nodes/guard.py` — the guard publishes which try of the guarded
  source is running and the error code that ended the try before (`GuardAttempt`,
  `current_guard_attempt()`), via a ContextVar bound around each try. Generic: no cache words.
- `packages/url4/src/url4/dag/nodes/__init__.py`, `packages/url4/src/url4/dag/__init__.py` —
  re-export the two names.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/failure_classes.py` — one
  named constant for the `judge_reply_invalid` code.
- `apps/screamingface-engine/src/screamingface_engine/world/fresh_judge_retry.py` (new) — the
  scope a model call runs under: the run's own, or the same scope with a cache opt-out when
  this call re-asks a judge whose last reply did not parse.
- `apps/screamingface-engine/src/screamingface_engine/world/connector.py` — the model endpoint
  reads url4's retry and the scope, and passes both through that helper.
- Comments that promised "a fresh sample": `healthbench/revision_inputs.py`,
  `healthbench/runtime.py`, `healthbench/variant.py`, `gdpval/runtime.py`,
  `shared_grading/judge_evidence.py`, `draco/variant.py`.

## Test plan

- url4: the guard reports try 0 with no previous failure on the first ask; try k carries the
  code that ended try k-1; outside any guard there is no attempt; the inner guard's attempt
  shadows the outer one.
- Engine, through a full DRACO world with a fake gateway (MockTransport):
  - garbled then valid → the retry body carries `cache: {"use-cache": false}` and the Case grades;
  - the first ask carries no `cache` field;
  - a transient 5xx on the judge → the guard's retry carries no `cache` field;
  - the retried call's accounting books to the same Case (same request key, one grading owner).
- Unit: the helper leaves the scope untouched outside a guard, on a first try, and after any
  other failure code; keeps identity/origin/seed on an opt-out.
- Revision pin: healthbench-worst30, healthbench-professional, gdpval-text, draco, draco-3pass
  revisions and rendered protocol bytes unchanged.

## Acceptance

- A retry after `judge_reply_invalid` sends `use-cache: false`; nothing else does.
- No Benchmark revision or route byte moves.
- Free replay/failure-tape tests for these Benchmarks still pass (or skip with their stated
  reason when Docker is not available).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `gdpval/revision_inputs.py` and `gdpval/variant.py`
  (two more "fresh sample" comments), minus `draco/variant.py` (its "a retry that succeeds is
  cached normally" stays true: draco retries only after 429/5xx/transport failures). Names changed during the work: the url4 API is
  `GuardRetry(number, failure_code)` / `current_guard_retry()` (not "attempt": Attempt is a
  glossary word for a Candidate's independent answer), and it binds only on a retry, so a
  first send reads exactly like unguarded code and a nested guard's first send still sees the
  outer retry. Tests: `packages/url4/tests/unit/test_guard_retry.py` (7),
  `apps/screamingface-engine/tests/unit/test_fresh_judge_retry.py` (15). No prior test edited.
- **Commits:** `571c58a05` feat(url4): tell a guarded subtree which retry it runs and why;
  `81e121c06` fix(screamingface-engine): give a judge retry after an unparseable reply a fresh
  reply; plus the docs commit that closes this ledger and the mirror.
- **Gates:** `run_gates.py url4` ALL GATES GREEN (1367 passed, cov ≥ 95%);
  `run_gates.py screamingface-engine` ALL GATES GREEN (4691 passed, 86 skipped). Free e2e
  replays (Docker, prepared assets): `test_boards` golden replays for draco-3pass,
  healthbench-worst30 and gdpval-text match their goldens; all 21 `test_failures` tests pass
  (incl. the judge cut-off, token-cap and 429 tapes); draco and healthbench-professional skip
  (no recorded fixtures, pre-existing). Revisions unchanged: healthbench-worst30
  `39cfd96b068f7230`, healthbench-professional `d8fb037307f35415`, gdpval-text
  `cacfc3e6b83765f6`, draco `62718f04ea1a980f`, draco-3pass `2634cec91fd0f19a`; the rendered
  protocol of each is byte-identical to main (sha256 compared before/after).
- **Deviations:**
  - draco is pinned, not changed. Its verdict route RETURNS a garbled reply as invalid Evidence
    (counted in `verdicts_invalid`) instead of raising, so its `;retry=` fires only on
    429/5xx/transport failures and a garbled pass is never re-asked: no cache echo exists there.
    The ticket's draco claim was read from the seed wiring, not the verdict route.
  - url4 changed (one generic seam). The Engine cannot observe url4's retry loop: the guard
    re-runs the subtree with nothing changed, and the only Engine-only alternative was shared
    mutable state keyed by reply text plus an extra cache round trip per retry. url4 exposes
    only "retry k, caused by code X"; it knows nothing about caches.
  - The url4 read sits in `connector.py`, not the new module: only Runner adapters may import
    the url4 engine (`test_only_engine_extensions_import_url4`), so the connector reads the
    retry and hands its code to the Engine-owned policy.
- **Owner-verify:** the first paid run of healthbench or gdpval-text after merge, with the
  hosted cache on, should show no Case failing `judge_reply_invalid` with the same reply echoed
  across all three tries; a retry after a garbled reply shows up as a gateway cache bypass
  (`opted_out`) on that Judge request.
