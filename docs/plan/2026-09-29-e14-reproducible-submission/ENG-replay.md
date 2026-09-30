---
title: Engine replay-grant carry and cache-version counters
unit: ENG-replay
epic: OME-1307 (E14)
component: apps/screamingface-engine
wave: 3
status: draft (for review)
date: 2026-09-29
spec: docs/spec/2026-09-29-e14-reproducible-submission/prd/replay-pinned-run.md (RP-11 to RP-15), contracts.md (C1, C9, C11)
plan: docs/plan/2026-09-29-e14-reproducible-submission/ENG-replay.md
branch: unit/ENG-replay (from the e14-reproducible-submission-spec HEAD; D1)
---

# ENG-replay — carry the replay grant, count version hits and misses

> **For the implementer (Sonnet).** Follow the `sdlc-python` loop: ledger, RED, GREEN, gates,
> commit. Do not make a design decision. If this plan does not answer a question, stop and ask.

**Goal.** A run can carry an opaque replay grant from the SDK to every AI Gateway chat call.
The engine counts the gateway's version hits, version misses and repeated-key collapses, and
publishes them on the run's closing cache-summary log frame. A grant that the gateway rejects
fails the run with a typed error. The run never becomes a live run in silence.

**Architecture.** The grant takes the same path as the answer seed (OME-1038):

```
GET /?q= (X-SF-Cache-Replay) ──► rest.routes._schedule ──► ReplayAwareJobRunner.schedule(replay_grant=…)
  ──► job env URL4_CLOUD_CACHE_REPLAY_GRANT (queue message or in-process env)
  ──► runner.main.request_scope_from_env ──► RequestScope.replay_grant
  ──► world.connector._headers ──► X-AIGW-Cache-Replay (written LAST) ──► aigateway
```

The version outcome returns the other way. The connector reads `X-AIGW-Cache-Version` into
`CacheOutcome.version`. It reports it to a run-scoped sink (a ContextVar in a new shared leaf,
`replay_outcomes.py`). The executor binds `RunCacheCounters` as that sink for the run. The
counters publish three new `cache.version.*` attributes on the closing summary frame.

Exemplars:

| New or changed piece | Exemplar to imitate |
|---|---|
| grant through REST → port → env → scope | the answer seed: `rest/routes.py:140-156, 608-618, 654`; `job_env.py:124-131, 255-280`; `adapters/inprocess.py:207-211`; `runner_queue.py:217`; `runner/main.py:74-108` |
| shared-leaf ContextVar sink | `src/screamingface_engine/trace_scope.py:29-84` |
| gateway-owned header written last | `world/connector.py:1048-1078` (`_headers`), test `tests/unit/test_identity_header_propagation.py:271-293` |
| response-header parse | `world/cache_readback.py:123-149, 227-240` |
| run counters and summary | `runner/cache_counters.py:186-337` |
| env reset in the in-process runner | `adapters/inprocess.py:196-211` |
| ambient-env drop in the worker | `worker/supervisor.py:200-223` |
| tests: REST edge → recording runner | `tests/unit/test_answer_seed_threading.py:180-268` |
| tests: env → connector end to end | `tests/unit/test_answer_seed_threading.py:338-354` |
| tests: run frames and summary log | `tests/unit/test_cache_run_counters.py:200-300` |

**Delivery (D1).** All E14 units land on the one branch `e14-reproducible-submission-spec`.
There is no per-unit PR, no Linear issue and no per-unit CI merge gate. Build this unit in a
temporary worktree on branch `unit/ENG-replay`, made from the HEAD of the e14 branch after the
wave-2 integration: `git worktree add .claude/worktrees/unit-ENG-replay e14-reproducible-submission-spec`,
then, in that worktree, `git checkout -B unit/ENG-replay e14-reproducible-submission-spec`.
Commit on `unit/ENG-replay` only. After wave 3, the integrator merges the unit branches into
the e14 branch in sequence and runs the gates.

## 0. Integration notes (D2)

- **Wave 3** with SB-submit, GW-replay and SDK-submit.
- **Shared files with other wave-3 units: none.** GW-replay changes `apps/aigateway` only,
  SB-submit `apps/scoreboard` only, SDK-submit `packages/screamingface` only.
- **Files that an earlier unit changed (already merged):** `apps/screamingface-engine/CHANGELOG.md`
  (ENG-freeze, wave 2). Add this unit's line under `## Unreleased` below the ENG-freeze line.
  `.claude/scripts/check_layering.py` (ENG-freeze adds `cache_versions` to `CONTROL_PLANE`); this
  unit does not edit it (`replay_outcomes.py` is a shared leaf and needs no entry).
- **Cross-track contracts (no shared file):** GW-replay (same wave) emits the
  `X-AIGW-Cache-Version` header, the `Cache-Status: aigateway; hit; detail=version; key="<prefix>"`
  member and the `403 {"detail": {"code": "replay_grant_invalid", "reason", "message"}}` body.
  SDK-replay (wave 4) sends `X-SF-Cache-Replay` on the start request and reads the three
  `cache.version.*` attributes of §5.10. This plan and those plans use the same shapes.

## 1. Scope

### 1.1 Test ids this unit owns

| Id | Test (PRD name) | Level | Source |
|---|---|---|---|
| RP-11 | `engine_carries_grant_opaquely_and_writes_header_last` | unit | RP-D2, C1, C9, C11 |
| RP-12 | `identity_header_cannot_inject_replay_header` | unit | RP-D2 |
| RP-13 | `engine_counts_version_hits_and_misses_into_report` | integration | ans:Q13, RP-H5 |
| RP-14 | `grant_rejected_mid_run_fails_run_with_typed_error` | integration | RP-E6, CV-E4 |
| RP-15 | `repeated_key_collapse_counted_in_report` | unit | RP-D5, CV-D6 |

Each id is split into named test functions (for example RP-11a) in §7. All of them belong to
that id. Do not add other PRD ids.

### 1.2 Out of scope

- The freeze route (ENG-freeze, SC-21).
- Grant minting, pin resolution, and the grant claims (SB-grants, RP-1 to RP-10).
- Grant verification, the version lookup, and the `X-AIGW-Cache-Version` header itself
  (GW-replay, CV-16 to CV-21, RP-5).
- The SDK `evaluate(replay=…)`, the grant request, and the report's `replay` block
  (SDK-replay, RP-16 to RP-20). This unit only publishes the counts on the frame stream.
- The Prometheus metric `screamingface_engine_replay_calls_total` (Decided: D7, X-15; §11 item 3).
- Grant carry on the mount routes (`rest/mounts.py`) and on local mode's `/v1?q=` eval path
  (`request_scope.forwarded_headers`). The PRD names only the run path. Do not add the header
  to `_PASSED_REQUEST_HEADERS`.
- Any grant refresh or TTL change (Decided: D4, no refresh; §11 item 2).
- Chart, Secret and deploy wiring (WIRING, wave 5, D6). This unit adds no Helm value.

## 2. Depends on

- **Units (code dependencies):** none. The code does not use ENG-freeze. ENG-freeze is in
  wave 2, so it is already in the e14 HEAD that this unit starts from; the only shared file is
  `CHANGELOG.md` (see §0).
- **Contracts implemented:** C1 (the engine half: accept, carry, never decode), C9 (the
  engine request header `X-AIGW-Cache-Replay` and the reading of the response header
  `X-AIGW-Cache-Version`), C11 row 3 (Decided: D7, X-6: "no `jwt` import outside
  `screamingface_engine/auth/`"; only `world/connector.py` writes the header).
- **Contracts consumed:** C9 response headers and the `403 replay_grant_invalid` body from
  GW-replay (coded body, D7 X-8). Build against a fake gateway (`httpx.MockTransport`). Do not
  wait for GW-replay.
- **Contract produced for SDK-replay (Decided: D7, X-7):** three integer
  attributes on the run's closing cache-summary `LogData` frame:
  `cache.version.hits`, `cache.version.misses`, `cache.version.repeated_key_collapses`.

## 3. Global constraints

- **Append-only test gate** (`.claude/scripts/run_gates.py:380-440`). Put every new test in a
  **new file**. Do not edit any existing test, fixture, or `tests/unit/_fakes.py`. This is why
  §5.3 adds a **new** port subclass instead of a new parameter on `IdentityAwareJobRunner`:
  six existing test fakes override `schedule` with an explicit parameter list
  (`tests/unit/_fakes.py:146-172`, `tests/unit/test_answer_seed_threading.py:190-216`,
  `tests/unit/test_cache_policy_threading.py:229`, `tests/unit/test_queue_admission.py:224`,
  `tests/integration/test_e2e_compose_flow.py:45`, `tests/integration/test_run_control_resilience.py:56`).
  A new parameter on the base port would make pyright report each of them as an incompatible
  override, and the fix would edit protected lines.
- **Layering gate** (`.claude/scripts/check_layering.py`). The new `replay_outcomes.py` is a
  shared leaf: it may import only the standard library. `world/` and `runner/` may import it.
  It must import neither half and not `world`.
- **The engine never decodes the grant** (RP-D2, C11). No `jwt` import. No base64 decode. No
  split on `.`. Treat it as an opaque `str`.
- **The grant is never logged.** It is a bearer-style token bound to one subject. Never put it
  in a log line, a span, a frame, an exception message or a `repr`.
- **No url4 change.** Do not change `packages/url4` (`ModelResponse`, `SpanData`). The version
  outcome travels through the engine-owned sink only.
- **Byte identity when absent.** A run with no grant must send byte-identical requests and must
  publish a byte-identical summary frame to today's run. Every new key and header is omitted
  when absent, never sent blank.
- **AIGateway credentials** stay only in the gateway `credential_blobs`. No OS keychain. The
  engine adds no credential.
- **Identity (D5).** In production the whole system relies on the Cloudflare identity headers.
  The Cloudflare Access/Envoy edge sets the verified `X-User-Email`; the engine carries it in
  `RequestScope.identity_headers` (unchanged); the gateway runs `cloudflare_headers` and checks
  the grant `sub` against that verified email (GW-replay §4.3 step 7). The engine does no subject
  check. RP-12 makes sure that an identity mapping cannot set or displace the replay header.

## 4. Files

| # | Path | Change |
|---|---|---|
| 1 | `apps/screamingface-engine/src/screamingface_engine/replay_outcomes.py` | create (shared leaf: sink ContextVar, literals) |
| 2 | `apps/screamingface-engine/src/screamingface_engine/job_env.py` | change: `CACHE_REPLAY_GRANT`, `MAX_REPLAY_GRANT_BYTES`, `replay_grant_to_env`, `replay_grant_from_env`, add to `WRITTEN_BY_APP` and `__all__` |
| 3 | `apps/screamingface-engine/src/screamingface_engine/request_scope.py` | change: `RequestScope.replay_grant` field |
| 4 | `apps/screamingface-engine/src/screamingface_engine/ports.py` | change: add `ReplayAwareJobRunner` |
| 5 | `apps/screamingface-engine/src/screamingface_engine/rest/routes.py` | change: read `X-SF-Cache-Replay` on `GET /`, validate, pass to `_schedule` |
| 6 | `apps/screamingface-engine/src/screamingface_engine/adapters/inprocess.py` | change: subclass `ReplayAwareJobRunner`; `schedule` and `_env` take `replay_grant`; reset the ambient value |
| 7 | `apps/screamingface-engine/src/screamingface_engine/adapters/queue_runner.py` | change: subclass `ReplayAwareJobRunner`; pass `replay_grant` to `encode_message` |
| 8 | `apps/screamingface-engine/src/screamingface_engine/runner_queue.py` | change: `_env_mapping` and `encode_message` take `replay_grant` |
| 9 | `apps/screamingface-engine/src/screamingface_engine/worker/supervisor.py` | change: `cold_child_env` drops an ambient grant |
| 10 | `apps/screamingface-engine/src/screamingface_engine/runner/main.py` | change: `request_scope_from_env` reads the grant |
| 11 | `apps/screamingface-engine/src/screamingface_engine/world/cache_readback.py` | change: `CacheOutcome.version`; parse `X-AIGW-Cache-Version`; version hit is exempt from revalidation |
| 12 | `apps/screamingface-engine/src/screamingface_engine/world/connector.py` | change: write the header last; report the version outcome; map `403 replay_grant_invalid` |
| 13 | `apps/screamingface-engine/src/screamingface_engine/runner/cache_counters.py` | change: version counters, collapse count, rejection reason, attributes, summary |
| 14 | `apps/screamingface-engine/src/screamingface_engine/runner/executor.py` | change: bind the sink in `_drive`; fail the run on a recorded rejection |
| 15 | `apps/screamingface-engine/tests/unit/test_replay_grant_carry.py` | create (RP-11) |
| 16 | `apps/screamingface-engine/tests/unit/test_replay_header_injection.py` | create (RP-12) |
| 17 | `apps/screamingface-engine/tests/integration/test_replay_version_counters.py` | create (RP-13) |
| 18 | `apps/screamingface-engine/tests/integration/test_replay_grant_rejection.py` | create (RP-14, incl. RP-14e for D4) |
| 19 | `apps/screamingface-engine/tests/unit/test_replay_key_collapses.py` | create (RP-15) |
| 20 | `apps/screamingface-engine/CHANGELOG.md` | change: one line under `## Unreleased`, below the ENG-freeze line; it names the 12 h grant-life limit (D4) |
| 21 | `docs/work/<date>-e14-eng-replay.md` | create (work ledger, repo rule; `ticket: unfiled`) |

## 5. Signatures and data shapes

### 5.1 `replay_outcomes.py` (new shared leaf; standard library only)

```python
"""The run's cache-version outcomes, reported by the world and tallied by the run (E14, RP-13)."""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal, Protocol

VersionOutcome = Literal["hit", "miss"]
GrantRejectionReason = Literal[
    "signature", "expired", "audience", "unknown_version", "subject", "unknown"
]
_GRANT_REJECTION_REASONS: dict[str, GrantRejectionReason] = {
    "signature": "signature",
    "expired": "expired",
    "audience": "audience",
    "unknown_version": "unknown_version",
    "subject": "subject",
}   # the closed CV-E4 set; a LOOKUP (not a membership test) so pyright keeps the Literal,
    # the same idiom as `world/cache_readback.py:79` (`_LEGACY_STATUSES`)


def grant_rejection_reason(raw: object) -> GrantRejectionReason:
    """The closed CV-E4 reason, or "unknown" for anything else. Never raises."""
    return _GRANT_REJECTION_REASONS.get(raw, "unknown") if isinstance(raw, str) else "unknown"


class ReplayOutcomeSink(Protocol):
    def record_version(self, outcome: VersionOutcome, key: str | None) -> None: ...
    def record_grant_rejection(self, reason: GrantRejectionReason) -> None: ...


_sink: contextvars.ContextVar[ReplayOutcomeSink | None] = contextvars.ContextVar(
    "screamingface_engine_replay_outcome_sink", default=None
)


@contextmanager
def replay_outcome_scope(sink: ReplayOutcomeSink | None) -> Iterator[None]:
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


def report_version_outcome(outcome: VersionOutcome, key: str | None) -> None:
    """No-op when no run bound a sink (the sync surface, a bare test)."""
    sink = _sink.get()
    if sink is not None:
        sink.record_version(outcome, key)


def report_grant_rejection(reason: GrantRejectionReason) -> None:
    sink = _sink.get()
    if sink is not None:
        sink.record_grant_rejection(reason)
```

### 5.2 `job_env.py`

Add the constants after the `ANSWER_SEED` docstring (lines 124-131) and the functions after
`answer_seed_from_env` (lines 266-285):

```python
CACHE_REPLAY_GRANT = "URL4_CLOUD_CACHE_REPLAY_GRANT"
"""The run's opaque cache-version replay grant (E14, contracts C1). Per-run, App-written.
INVARIANT: opaque — the engine never decodes it (RP-D2). Never logged.
LIMIT (D4): the grant lives 12 h from issue. The job deadline (57,600 s) plus the queue wait
can be longer. A grant that expires mid-run makes the gateway answer 403
replay_grant_invalid reason=expired, and the run fails with that typed error (RP-14). There
is no refresh."""

MAX_REPLAY_GRANT_BYTES = 2048
"""C1: a grant longer than this (UTF-8 bytes) is refused with 431 at the REST edge."""

def replay_grant_to_env(replay_grant: str | None) -> dict[str, str]:
    """None renders NOTHING, so a plain run's env is unchanged."""
    return {} if replay_grant is None else {CACHE_REPLAY_GRANT: replay_grant}

def replay_grant_from_env(env: Mapping[str, str]) -> str | None:
    """Absent or blank → None. Raises ValueError when longer than MAX_REPLAY_GRANT_BYTES
    (the App refuses that at the edge, so a longer value here is a bug; the loud answer is
    the safe one, as for the answer seed). The value is returned as written, not stripped."""
```

- The `ValueError` message must **not** contain the grant. Use
  `f"{CACHE_REPLAY_GRANT} exceeds {MAX_REPLAY_GRANT_BYTES} bytes"`.
- Add `CACHE_REPLAY_GRANT` to `WRITTEN_BY_APP` (line 501). Do **not** add it to `SECRET`: the
  deployed runner is the queue codec, not a Kubernetes Job spec, and `SECRET` governs Job spec
  literals (`job_env.py:484-495`).
- Add the three names to `__all__`.

### 5.3 `ports.py` — `ReplayAwareJobRunner`

```python
class ReplayAwareJobRunner(IdentityAwareJobRunner):
    """A runner whose `schedule` also carries the run's opaque cache-version replay grant.

    WHY a sub-port and not a new parameter on `IdentityAwareJobRunner`: the append-only test
    gate protects six existing test fakes that override `schedule` with an explicit list.
    Both production adapters implement this port; the REST edge requires it only for a run
    that carries a grant."""

    @abstractmethod
    async def schedule(
        self, topic: str, url4: str, deadline_s: int, *,
        traceparent: str | None = None, credential: str | None = None,
        profile: str | None = None, identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None, answer_seed: int | None = None,
        client_version: str | None = None, shape: RunShape = "expression",
        replay_grant: str | None = None,
    ) -> str: ...
```

### 5.4 `request_scope.py` — the scope field

Add to `RequestScope` (after `deadline`, line 113):

```python
# FEATURE (E14, RP-D2): the run's opaque replay grant. The connector writes it as its
# gateway-owned replay header, last. `repr=False`: it must never reach a log.
replay_grant: str | None = field(default=None, repr=False)
```

`request_scope_from_headers` (the sync producer) does **not** read it. Leave that function
unchanged.

### 5.5 `rest/routes.py` — the REST edge

- Add a module constant `CACHE_REPLAY_HEADER = "X-SF-Cache-Replay"` beside
  `QUEUE_UNAVAILABLE_RETRY_AFTER_S`.
- Carrier (Decided: D7, X-5): the replay header rides the start request `GET /?q=` (the
  `start_run` handler), not `POST /token`.
- Add `_parse_replay_grant(request: Request) -> str | None` next to `_parse_answer_seed`
  (line 140):
  1. `values = request.headers.getlist(CACHE_REPLAY_HEADER)`.
  2. No value, or every value blank after `strip()` → `None`.
  3. More than one non-blank value → `ProblemException(status=400, title="Bad Request",
     detail="send one X-SF-Cache-Replay header", code="replay_grant_ambiguous")`. Reason: a
     replay must never become a live run in silence (R9).
  4. `len(value.encode("utf-8")) > job_env.MAX_REPLAY_GRANT_BYTES` →
     `ProblemException(status=431, title="Request Header Fields Too Large",
     detail="the X-SF-Cache-Replay header exceeds 2048 bytes", code="replay_grant_too_large")`.
  5. Return the value as sent (no strip, no decode).
- Add `_replay_runner(deps: _Deps) -> ReplayAwareJobRunner` next to `_parse_replay_grant`:
  return `deps.job_runner` when `isinstance(deps.job_runner, ReplayAwareJobRunner)`, else raise
  `ProblemException(status=503, title="Service Unavailable",
  detail="this Engine's runner cannot carry a cache-version replay", code="replay_unsupported")`.
  Import `ReplayAwareJobRunner` from `screamingface_engine.ports` beside
  `IdentityAwareJobRunner` (line 35).
- In `start_run`, right after `answer_seed = _parse_answer_seed(x_answer_seed)` (line 654), add:

```python
replay_grant = _parse_replay_grant(request)
if replay_grant is not None:
    _replay_runner(deps)  # refuse (503) BEFORE `_refuse_existing` and before any hold
```

  Pass `replay_grant=replay_grant` to the `_schedule(...)` call inside the local `schedule()`
  closure (lines 667-676). So every refusal (400, 431, 503) happens before `_refuse_existing`
  and before anything is scheduled.
- Document the header in OpenAPI with a declared-only parameter on `start_run`, placed after
  `x_answer_seed`:
  `_x_sf_cache_replay: Annotated[str | None, Header(alias="X-SF-Cache-Replay",
  description="Optional opaque cache-version replay grant (at most 2048 bytes). The Engine never reads its content; it carries it to AI Gateway on every chat call of the run.")] = None`.
  The value is read by `_parse_replay_grant(request)`, not from this parameter (the same
  pattern as `_x_profile`, line 607). Add `431: _problem("The X-SF-Cache-Replay header exceeds
  2048 bytes (`code: replay_grant_too_large`).")` and `503: _problem("This Engine's runner cannot
  carry a cache-version replay (`code: replay_unsupported`), or the runner is at capacity.")` to
  `_START_RESPONSES` (line 522), and add "or states more than one `X-SF-Cache-Replay` header
  (`code: replay_grant_ambiguous`)" to the existing 400 text.
- `_schedule` (line 207) gets the keyword-only `replay_grant: str | None = None` (last). Inside
  the existing `try`, replace the single `await deps.job_runner.schedule(...)` with two explicit
  calls. Do **not** build a `**kwargs` dict (pyright rejects a `dict[str, object]` unpack into
  typed parameters):

```python
deadline = deps.settings.job_deadline_s if deadline_s is None else deadline_s
if replay_grant is None:
    await deps.job_runner.schedule(
        topic, url4, deadline,
        traceparent=traceparent, identity=identity, cache=cache,
        answer_seed=answer_seed, client_version=client_version, shape=shape,
    )
else:
    await _replay_runner(deps).schedule(
        topic, url4, deadline,
        traceparent=traceparent, identity=identity, cache=cache,
        answer_seed=answer_seed, client_version=client_version, shape=shape,
        replay_grant=replay_grant,
    )
```

  WHY the plain call when there is no grant: a runner that is not replay-aware (the test fakes,
  `tests/unit/_fakes.py:138`) must keep working for every plain run. The existing log line
  (`run scheduled topic=%s url4_chars=%d cache=%s`) stays byte-identical. Do not log the grant.
- `rest/mounts.py` calls `_schedule` without `replay_grant`. Do not change it.

### 5.6 Adapters and the codec

- `adapters/inprocess.py`: `class InProcessJobRunner(ReplayAwareJobRunner)`. `schedule` gets
  `replay_grant: str | None = None` and passes it to `self._env(..., replay_grant=replay_grant)`.
  `_env` gets the keyword-only `replay_grant: str | None = None` as its **last** parameter.
  Inside `_env`, after the answer-seed lines (207-211):

```python
# INVARIANT: same reset as the seed — a grant left in `_base_env` would replay one caller's
# version onto another caller's run.
env.pop(job_env.CACHE_REPLAY_GRANT, None)
env.update(job_env.replay_grant_to_env(replay_grant))
```

- `runner_queue.py`: `_env_mapping` and `encode_message` get `replay_grant: str | None = None`
  (keyword-only, last). In `_env_mapping`, after line 217:
  `env.update(job_env.replay_grant_to_env(replay_grant))`. `encode_message` passes
  `replay_grant=replay_grant` on to `_env_mapping` (lines 252-265).
- `adapters/queue_runner.py`: `class QueueJobRunner(ReplayAwareJobRunner)`. `schedule` gets
  `replay_grant: str | None = None` and passes it to `encode_message`.
- `worker/supervisor.py:cold_child_env`: add `env.pop(job_env.CACHE_REPLAY_GRANT, None)` next to
  the `AIGATEWAY_PROFILE` pop (line 221), with the comment "only this queue message may carry a
  replay grant". The warm path already strips it, because `deploy_env`
  (`worker/warm_pool.py:97-105`) strips every `WRITTEN_BY_APP` key.
- Do **not** bump `job_env.CURRENT_SPEC_VERSION`. An absent key keeps a message byte-identical,
  the same rule as `RUN_SHAPE` (`runner_queue.py:222-227`).

### 5.7 `runner/main.py`

In `request_scope_from_env` (line 74): read `replay_grant = job_env.replay_grant_from_env(env)`
inside the existing `try` (so a `ValueError` becomes `RunnerConfigError`), and pass
`replay_grant=replay_grant` to `RequestScope(...)` (line 101).

### 5.8 `world/cache_readback.py`

- Add `_VERSION_FIELD = "X-AIGW-Cache-Version"`.
- Add a field to `CacheOutcome` **after** `retried`, with a default, so every existing
  construction site keeps its meaning:

```python
version: VersionOutcome | None = None
"""The gateway's cache-version answer for a replay call (contracts C9): `hit`, `miss`, or
None when the call carried no grant or the gateway said nothing usable."""
```

- In `read_cache_outcome`, parse it with `_field(headers, _VERSION_FIELD)`: `strip().lower()`,
  then a lookup `_VERSION_OUTCOMES: dict[str, VersionOutcome] = {"hit": "hit", "miss": "miss"}`
  (the `_LEGACY_STATUSES` idiom, `cache_readback.py:79`); anything else → `None`. Never raise.
  Set it on **both** return paths (with and without a reported status, lines 141 and 143).
- In `requires_revalidation`, return `False` when `outcome.version == "hit"`, before the
  `max_age` check. Reason: RP-H1 says each call that the version holds is served from the
  version. A revalidation re-issue would discard the pinned answer and go live.
- Import `VersionOutcome` from `screamingface_engine.replay_outcomes`.

### 5.9 `world/connector.py`

1. Add `_CACHE_REPLAY_HEADER = "X-AIGW-Cache-Replay"` beside `_COMPLETIONS_PATH` (line 84).
   This is the **only** place in `src/` that spells this header (C11).
   Import `grant_rejection_reason`, `report_grant_rejection` and `report_version_outcome` from
   `screamingface_engine.replay_outcomes` (a shared leaf; `world` may import it).
2. `_headers(scope)` (line 1048) becomes:

```python
headers = {k: v for k, v in scope.identity_headers.items()
           if k.lower() != _CACHE_REPLAY_HEADER.lower()}
if scope.profile is not None:
    headers[PROFILE_HEADER] = scope.profile
traceparent = current_traceparent()
if traceparent is not None:
    headers["traceparent"] = traceparent
# INVARIANT (E14, RP-D2): gateway-owned and written LAST; an identity mapping can neither set
# nor displace it. Absent grant → header omitted, never sent blank.
if scope.replay_grant is not None:
    headers[_CACHE_REPLAY_HEADER] = scope.replay_grant
return headers
```

   Extend the docstring INVARIANT with one line about the replay header.
3. In `_observed_round_trip` (line 149), right after
   `resp, outcome = await _fetch_completion(...)` (line 170):

```python
if outcome.version is not None:
    report_version_outcome(outcome.version, outcome.key)
```

4. In `_raise_for_status` (line 1109), after `code` and `detail` are read and **before** the
   final `raise`:

```python
if resp.status_code == 403 and code == "replay_grant_invalid":
    reason = grant_rejection_reason(detail.get("reason") if isinstance(detail, dict) else None)
    report_grant_rejection(reason)
    raise ResolutionError(
        f"aigateway rejected the replay grant (reason={reason})",
        code="replay_grant_invalid",
        permanent=True,
    )
```

   Keep `detail` in scope for this check (today `detail` is local to the `if isinstance(payload,
   dict)` block; hoist it to `detail = None` before that block). Do not include the gateway
   `message` or the grant in the error text.

### 5.10 `runner/cache_counters.py`

Add constants beside `CACHE_HITS` (line 53) and export them:

```python
VERSION_HITS = "cache.version.hits"
VERSION_MISSES = "cache.version.misses"
VERSION_REPEATED_KEY_COLLAPSES = "cache.version.repeated_key_collapses"
```

Add fields to `RunCacheCounters` (after `unpriced_hits`, line 203). No field name may contain
`saved_cost` (`tests/unit/test_cache_saved_cost.py:241-248`):

```python
version_hits: int = 0
version_misses: int = 0
version_repeated_key_collapses: int = 0
grant_rejection_reason: str | None = None
_version_hit_keys: set[str] = field(default_factory=set)
```

Add methods (this makes `RunCacheCounters` satisfy `ReplayOutcomeSink`):

```python
@property
def version_observed(self) -> bool:
    return bool(self.version_hits or self.version_misses)

def record_version(self, outcome: VersionOutcome, key: str | None) -> None:
    """A hit whose key this run already served from the version is a repeated-key collapse
    (RP-D5, CV-D6). A hit with no key counts as a hit and never as a collapse. The key stays
    in memory only; it is never published (spec §7)."""
    if outcome == "hit":
        self.version_hits += 1
        if key:
            if key in self._version_hit_keys:
                self.version_repeated_key_collapses += 1
            else:
                self._version_hit_keys.add(key)
    elif outcome == "miss":
        self.version_misses += 1

def record_grant_rejection(self, reason: GrantRejectionReason) -> None:
    """First rejection wins; later ones state nothing new."""
    if self.grant_rejection_reason is None:
        self.grant_rejection_reason = reason
```

Update the module docstring INVARIANT (lines 26-32): add one sentence that the entry key
also reaches `record_version`, only to find a repeated version hit in memory; it is never
published, logged, or used as a label. Change `observed` (line 216) to
`bool(self.hits or self.misses or self.bypasses or self.version_observed)`.

In `attributes()` (line 277), after the bypass-reason loop, add the three `cache.version.*`
integer entries **only** when `self.version_observed`. In `summary_body()` (line 306), append
`f"; cache version: {self.version_hits} hit, {self.version_misses} miss, "
f"{self.version_repeated_key_collapses} repeated-key collapse"` only when
`self.version_observed`.

Import `GrantRejectionReason` and `VersionOutcome` from `screamingface_engine.replay_outcomes`
(a shared leaf; `runner` may import it; it is not url4, so
`tests/unit/test_url4_executor.py:688` stays green).

### 5.11 `runner/executor.py`

1. In `_run_steps._drive` (line 923), bind the sink in the same `with`:
   `with run_trace_scope(trace), self._scope_context(), replay_outcome_scope(state.cache_counters):`.
2. Right after `eval_result = await task` (line 933), before `_closing_logs`:

```python
rejection = state.cache_counters.grant_rejection_reason
if rejection is not None:
    # FEATURE (E14, RP-E6): a rejected grant fails the RUN, even when a benchmark collected the
    # failed call as a failed case. It never becomes a live run in silence.
    raise ResolutionError(
        f"the replay grant was rejected by aigateway (reason={rejection})",
        code="replay_grant_invalid",
        permanent=True,
    )
```

   `execute` (line 845-868) already turns this into `Terminated(status="failed")` with the
   code, through `url4.streaming.lifecycle._error_info`.

## 6. Migrations

None. The engine has no database.

## 7. TDD order (RED first, risk order)

Before the first RED, add the stubs so each failure is an **assertion**: the new
`replay_outcomes.py`, the `job_env` constants with `replay_grant_to_env` returning `{}` and
`replay_grant_from_env` returning `None`, the `RequestScope.replay_grant` field, the
`ReplayAwareJobRunner` class, the `CacheOutcome.version` field (always `None`), and the
counter fields at zero. There are no CHAR rows in the PRD for this unit. Run the existing
safety net first and see it green: `tests/unit/test_answer_seed_threading.py`,
`tests/unit/test_identity_header_propagation.py`, `tests/unit/test_job_env_contract.py`,
`tests/unit/test_run_queue_codec.py`, `tests/unit/test_cache_readback.py`,
`tests/unit/test_cache_run_counters.py`, `tests/unit/test_cache_saved_cost.py`.

Oracle values: `GRANT = "eyJhbGciOiJFZERTQSIsImtpZCI6ImsxIn0.eyJ2aWQiOiJ2In0.c2ln"` (an
opaque JWS-shaped string) and `NOT_A_JWS = "opaque grant with spaces"` (proves no parsing).

| Order | Id | File | Test function | RED reason |
|---|---|---|---|---|
| 1 | RP-11a | `tests/unit/test_replay_grant_carry.py` | `test_the_replay_header_reaches_the_job_runner_unchanged` | `GET /` with `X-SF-Cache-Replay: GRANT` and `Prefer: respond-async`; a test-local `_GrantRecordingRunner(ReplayAwareJobRunner)` records `replay_grant`. Stub route passes nothing: assert `== [GRANT]` fails. |
| 2 | RP-11b | same | `test_a_run_without_the_header_schedules_no_grant` | (i) `_GrantRecordingRunner` records `[None]`; (ii) the same plain `GET /` on a plain `RecordingJobRunner` (not replay-aware, `tests/unit/_fakes.py:138`) answers 202 and schedules one run. (Green once RP-11a is green; keep it as the absence pin, and say so in the ledger.) |
| 3 | RP-11c | same | `test_an_oversized_grant_is_a_431_and_nothing_is_scheduled` | 2049-byte grant. Assert 431, `code == "replay_grant_too_large"`, zero scheduled runs. Stub: 202. |
| 4 | RP-11d | same | `test_two_grant_headers_are_a_400_and_nothing_is_scheduled` | Assert 400, `code == "replay_grant_ambiguous"`. |
| 5 | RP-11e | same | `test_a_grant_on_a_runner_without_replay_support_is_a_503` | Use `RecordingJobRunner` from `_fakes`. Assert 503 `replay_unsupported`, zero scheduled. |
| 6 | RP-11f | same | `test_the_queue_codec_carries_the_grant_and_renders_nothing_without_it` | `decode_message(encode_message(..., replay_grant=GRANT))[CACHE_REPLAY_GRANT] == GRANT`; without it the key is absent. |
| 7 | RP-11g | same | `test_the_inprocess_env_replaces_any_ambient_grant` | `_base_env` holds a stale grant; `_env(..., replay_grant=None)` has no key; `_env(..., replay_grant=GRANT)` has `GRANT`. Imitate `test_answer_seed_threading.py:154-175`. |
| 8 | RP-11h | same | `test_cold_child_env_drops_an_ambient_grant` | `cold_child_env({CACHE_REPLAY_GRANT: "stale"}, {}, 4)` has no key; with the run env it has the run's value. |
| 9 | RP-11i | same | `test_the_run_producer_binds_the_grant_into_the_scope` | `request_scope_from_env({... CACHE_REPLAY_GRANT: NOT_A_JWS})` gives `replay_grant == NOT_A_JWS`; an over-long value raises `RunnerConfigError` whose text does not contain the value. |
| 10 | RP-11j | same | `test_the_grant_is_not_in_the_scope_repr` | `GRANT not in repr(RequestScope(origin="run", replay_grant=GRANT))`. |
| 11 | RP-11k | same | `test_the_runs_env_reaches_the_gateway_header` | `build_executor(job_env.replay_grant_to_env(GRANT), _declared(), client=gw_client)`, run `/{MODEL}('ctx')!'go'`; assert the mock gateway saw `X-AIGW-Cache-Replay: GRANT`. Imitate `test_answer_seed_threading.py:338-354`. |
| 12 | RP-11l | same | `test_a_plain_run_sends_no_replay_header` | Same, empty env: header absent. |
| 13 | RP-11m | same | `test_the_engine_never_decodes_the_grant_and_one_module_writes_it` | For every `.py` under `src/screamingface_engine` (resolve the root from `screamingface_engine.__file__`): (1) AST-scan `Import`/`ImportFrom` nodes: no module `jwt` (or `jwt.*`) outside the `auth/` package; (2) a plain-text, case-insensitive scan of the file source for `x-aigw-cache-replay`: the set of files that contain it is exactly `{world/connector.py}`. Stub state: no file contains it, so assertion (2) fails (`set() != {...}`). |
| 14 | RP-12a | `tests/unit/test_replay_header_injection.py` | `test_an_identity_mapping_cannot_set_the_replay_header` | `RequestScope(origin="run", identity_headers={"X-User-Email": "a@b.c", "x-aigw-cache-replay": "forged"})`, no grant: outbound has no replay header. Today `_headers` copies it: fails. |
| 15 | RP-12b | same | `test_an_identity_mapping_cannot_displace_the_runs_grant` | Same forged key plus `replay_grant=GRANT`: outbound value is `GRANT`, and only one replay header is sent (`len(request.headers.get_list("x-aigw-cache-replay")) == 1`). |
| 16 | RP-12c | same | `test_an_inbound_gateway_header_on_get_is_never_carried` | `GET /` with `X-AIGW-Cache-Replay: forged` and no `X-SF-Cache-Replay`: the `_GrantRecordingRunner` records `None`. |
| 17 | RP-13a | `tests/integration/test_replay_version_counters.py` | `test_engine_counts_version_hits_and_misses_into_report` | Mock gateway answers call 1 and 2 with `Cache-Status: aigateway; hit; detail=version`, `X-AIGW-Cache-Version: hit`, and call 3 with `X-AIGW-Cache: miss`, `X-AIGW-Cache-Version: miss`. Expression with three distinct calls, `Url4Executor(world.node, request_scope_factory=lambda: RequestScope(origin="run", replay_grant=GRANT))`. Assert the one summary `LogData` has `cache.version.hits == 2`, `cache.version.misses == 1`, `cache.version.repeated_key_collapses == 0`, all ints. Stub: keys absent. |
| 18 | RP-13b | same | `test_a_plain_run_publishes_no_version_keys` | No version header: the summary has no `cache.version.` key (byte identity). |
| 19 | RP-13c | same | `test_a_version_hit_is_not_revalidated_under_max_age` | Scope `cache=CachePolicy(participate=True, max_age=60)`, gateway version hit with no `Age`: exactly **one** request reaches the gateway. Today `requires_revalidation` re-issues: two requests. |
| 20 | RP-13d | `tests/unit/test_replay_key_collapses.py` | `test_read_cache_outcome_parses_the_version_header` (parametrize: `hit`, `HIT `, `miss`, `bogus`, absent) | Stub returns `None` for every case. |
| 21 | RP-15a | same | `test_repeated_key_collapse_counted_in_report` | `RunCacheCounters.record_version("hit", "k1")` twice and `("hit", "k2")` once → `version_hits == 3`, `version_repeated_key_collapses == 1`; attributes carry `cache.version.repeated_key_collapses == 1`. |
| 22 | RP-15b | same | `test_a_keyless_hit_is_never_a_collapse` | `record_version("hit", None)` twice → collapses `0`. |
| 23 | RP-15c | same | `test_the_collapse_key_never_reaches_the_summary` | Record key `"e3b0c44298fc1c14"`; assert it is not in `summary_body()` nor in any attribute key or value. Imitate `tests/unit/test_cache_run_counters.py:253-267`. |
| 24 | RP-15d | same | `test_a_run_publishes_collapses_end_to_end` | Two-call nested run. The mock gateway answers both calls with `X-AIGW-Cache-Version: hit`, `X-AIGW-Cache: hit`, `X-AIGW-Cache-Key: k1` and **no** `Cache-Status` (a `Cache-Status` member without `key=` wins over the legacy triple and yields `key=None`, `cache_readback.py:137`). Summary has `cache.version.hits == 2` and `cache.version.repeated_key_collapses == 1`. Stub: key absent. |
| 25 | RP-14a | `tests/integration/test_replay_grant_rejection.py` | `test_a_rejected_grant_raises_a_typed_permanent_error` | Mock gateway `403 {"detail": {"code": "replay_grant_invalid", "reason": "expired", "message": "gw-secret"}}`. `url4_run` under a scope with a grant raises `ResolutionError` with `code == "replay_grant_invalid"`, `permanent is True`, `"reason=expired"` in the text, `"gw-secret"` and `GRANT` not in the text. Today the code is `replay_grant_invalid` but the text has no reason: the reason assertion fails. |
| 26 | RP-14b | same | `test_an_unknown_reason_reads_as_unknown` | `reason: "rotated"` → `"reason=unknown"`. |
| 27 | RP-14c | same | `grant_rejected_mid_run_fails_run_with_typed_error` (name it `test_grant_rejected_mid_run_fails_run_with_typed_error`) | A test node whose handler calls `report_grant_rejection("subject")` and then **returns** `"ok"` (a benchmark that collected the failure). `Url4Executor(node).execute(...)` must raise `ResolutionError` with `code == "replay_grant_invalid"` and `"reason=subject"`; no `Completed` frame is yielded. Today the run completes. |
| 28 | RP-14d | same | `test_a_rejection_never_falls_through_to_a_live_call` | The fake gateway answers every call 403 `replay_grant_invalid`. Assert the gateway saw no request **without** the replay header (the engine never retries the call without the grant). |
| 29 | RP-14e (D4) | same | `test_a_grant_that_expires_mid_run_fails_the_run_with_reason_expired` | The documented grant-life limit (D4). Two-call nested run (`f"/{MODEL}(/{MODEL}('a')!'x')!'y'"`) under `Url4Executor(world.node, request_scope_factory=lambda: RequestScope(origin="run", replay_grant=GRANT))`. The mock gateway answers call 1 with `X-AIGW-Cache-Version: hit`, `X-AIGW-Cache: hit`, and call 2 with `403 {"detail": {"code": "replay_grant_invalid", "reason": "expired", "message": "gw-secret"}}`. Assert: `execute` raises `ResolutionError` with `code == "replay_grant_invalid"`, `permanent is True`, `"reason=expired"` in the text, `"gw-secret"` and `GRANT` not in the text; no `Completed` frame; the gateway saw exactly 2 requests and both carry the replay header (no live retry). Before §5.9 step 4 the error text has no reason, so the `reason=expired` assertion fails. |

Test wiring notes:

- `_GrantRecordingRunner` in the RP-11 file is `class _GrantRecordingRunner(RecordingJobRunner,
  ReplayAwareJobRunner)` (so it inherits `stop`, `exists` and `status`). Imitate
  `_SeedRecordingRunner` (`tests/unit/test_answer_seed_threading.py:179-216`): its `schedule`
  takes every port parameter plus `replay_grant: str | None = None`, appends `replay_grant` to
  `self.replay_grants`, and calls `super().schedule(...)` without `replay_grant`. Use `FixedGate` and `InMemoryEventStream` as in
  `tests/unit/test_answer_seed_threading.py:217-238`.
- For RP-14c, build the node as `build_aigateway_world` does (`world/connector.py:443-449`):
  `node = Url4Node("t", default_processor="/m")` and `node.endpoint("/m")(handler)`, where
  `handler(request)` is a plain function (imitate `tests/unit/test_benchmark_context_routes.py:44`).
  Drive it with `[f async for f in Url4Executor(node).execute("/m('x')!'go'")]` inside
  `pytest.raises(ResolutionError)`.
- Multi-call runs (RP-13a, RP-14e, RP-15d) use a NESTED expression so the calls are sequential and the
  mock gateway can answer by call index: three calls = `f"/{MODEL}(/{MODEL}(/{MODEL}('a')!'x')!'y')!'z'"`,
  two calls = `f"/{MODEL}(/{MODEL}('a')!'x')!'y'"` (nested sources resolve inner first; see the
  `/nested(/missing)!'read'` form in `tests/unit/test_benchmark_context_routes.py`). If the parser
  rejects the form, stop and ask; do not invent another expression.
- RP-11k and RP-11l define their own `_declared()` and `_MockAigateway` in the new file,
  imitating `tests/unit/test_answer_seed_threading.py:274-310`. Do not import private helpers
  from another test file.
- Each file starts with a module docstring (FEATURE, INVARIANT) like
  `tests/unit/test_cache_run_counters.py:1-23`.

## 8. Edge cases

- **Blank header** → absent (a plain run). **Two headers** → 400. **2049 bytes** → 431.
  **Exactly 2048 bytes** → carried.
- **Non-JWS text** → carried unchanged (the engine does not parse).
- **Ambient env** (local `_base_env`, the worker's own environment) never leaks a grant onto
  another run (RP-11g, RP-11h).
- **Old worker during a rolling deploy.** An old worker ignores the new env key and runs live.
  The queue already uses a drained rollout for new message keys (`runner_queue.py:222-227`).
  Do not bump `CURRENT_SPEC_VERSION` (§11 item 5 records this risk; it is still open, X-17).
- **Judge calls.** The grant rides every chat call of the run, including grading calls. The
  captured version holds them too (same trace). Do not special-case them.
- **Transport retry.** `_post_completion` retries a transport failure once with the same
  headers. The grant stays on the retry. A 403 is not a transport failure, so it is not retried.
- **Version hit plus `max-age`.** Not re-issued (RP-13c).
- **Grant expiry mid-run (Decided: D4).** The grant lives 12 h (`exp = iat + 43,200 s`). The
  job deadline (57,600 s, `config.py:148-151`) plus the queue wait (up to 57,600 s,
  `worker/supervisor.py:833-858`) can be longer. This is a documented, accepted limit: the
  gateway answers `403 replay_grant_invalid reason=expired`, the connector records the
  rejection and raises the typed permanent `ResolutionError`, and the run fails (RP-14 path,
  pinned by RP-14e). The engine never retries the call without the grant and never refreshes
  the grant. The `job_env.CACHE_REPLAY_GRANT` docstring (§5.2) and the `CHANGELOG.md` line state
  the limit.
- **No grant, stray `X-AIGW-Cache-Version` on the response** (a misbehaving gateway): the
  counters count it. Accept; the gateway owns that header.

## 9. What not to do

- Do not decode, verify, split, log, or `repr` the grant. No `jwt`, no `base64`.
- Do not add the replay header anywhere except `world/connector.py`.
- Do not add a parameter to `IdentityAwareJobRunner.schedule`. Use `ReplayAwareJobRunner`.
- Do not edit any existing test file or `tests/unit/_fakes.py`.
- Do not change `packages/url4` (`ModelResponse`, `SpanData`, the lifecycle).
- Do not import `screamingface_engine.metrics` from `runner/` (layering; the run mode has no
  scrape endpoint, `runner/cache_counters.py:16-24`).
- Do not publish a cache key in any attribute, log line or error.
- Do not fall back to a live call when the gateway rejects the grant.
- Do not import `apps/aigateway`, `apps/scoreboard`, or `packages/screamingface`.

## 10. Gates and verification

Run from `apps/screamingface-engine/` in the unit's worktree:

```bash
uv run ruff check
uv run ruff format --check
uv run pyright
python3 ../../.claude/scripts/check_layering.py
uv run pytest tests/unit/test_replay_grant_carry.py tests/unit/test_replay_header_injection.py tests/unit/test_replay_key_collapses.py tests/integration/test_replay_version_counters.py tests/integration/test_replay_grant_rejection.py -q
uv run pytest tests/unit/test_answer_seed_threading.py tests/unit/test_identity_header_propagation.py tests/unit/test_job_env_contract.py tests/unit/test_run_queue_codec.py tests/unit/test_cache_readback.py tests/unit/test_cache_run_counters.py tests/unit/test_cache_saved_cost.py tests/unit/test_url4_executor.py tests/unit/test_scope_producers.py -q
uv run pytest --cov=screamingface_engine --cov=url4.streaming --cov-fail-under=80 -q
```

Then, from the repo root of the unit worktree:
`python3 .claude/scripts/run_gates.py screamingface-engine --base e14-reproducible-submission-spec`
(D1: the base is the e14 branch, so the check sees only this unit's change; the default
`--base HEAD` sees no change after a commit, so the append-only check would pass in silence).

**Done means all of these are true:**

1. RP-11a to RP-15d (all 29 rows of §7, RP-14e included) are green, and each one was seen RED
   for its stated reason first (RP-11b is the one absence pin that may pass at once; say so in
   the ledger).
2. The safety-net tests are green without an edit.
3. `check_layering.py` prints `LAYERING OK`.
4. `run_gates.py screamingface-engine` passes (append-only, pyright, 80 % coverage).
5. `grep -rlni "x-aigw-cache-replay" src/` finds exactly one file: `world/connector.py`
   (comments and docstrings count: never spell the header in any other module).
6. `grep -rnE "^\s*(import jwt|from jwt)" src/screamingface_engine | grep -v "/auth/"` finds
   nothing.
7. `git diff e14-reproducible-submission-spec...HEAD --stat` shows only the files in §4.
8. Conventional commits on `unit/ENG-replay`, no `Co-Authored-By`. No PR and no Linear issue
   (D1). The integrator merges the branch after wave 3.

## 11. Open decisions

One item is still open (item 5, cross-track X-17). The other items are closed. The numbers stay
the same, because other sections refer to them.

1. **Carrier route — Decided: D7 (X-5).** The engine reads `X-SF-Cache-Replay` on the start
   request `GET /?q=` (`start_run`, where the answer seed already rides,
   `rest/routes.py:608-618, 654`), not on `POST /token` (that route only mints a capability,
   `rest/routes.py:495-506`). SDK-replay (RP-16) sends it on the start request
   (`packages/screamingface/src/screamingface/_engine/transport.py:939-960 and 1163-1180`).
2. **Grant life — Decided: D4.** Keep `exp = iat + 43,200 s` (12 h). A3 is "[checked] false,
   accepted". The job deadline (57,600 s) plus the queue wait can pass the grant `exp`; the run
   then fails with the typed `replay_grant_invalid` error, reason `expired` (RP-14 path, RP-14e).
   No refresh. §5.2 and §8 document the limit.
3. **Engine metric — Decided: D7 (X-15).** Counters stay in process. The run mode does not emit
   `screamingface_engine_replay_calls_total`; the counts go on the closing log frame (§5.10).
4. **Engine → SDK counter contract — Decided: D7 (X-7).** Three integer attributes on the closing
   cache-summary `LogData` frame: `cache.version.hits`, `cache.version.misses`,
   `cache.version.repeated_key_collapses`, present only when the run saw a version outcome.
   SDK-replay reads them (`packages/screamingface/src/screamingface/_engine/contract.py:194`).
5. **Rolling deploy — OPEN (X-17, not in the user decisions).** An old worker that gets a message
   with the grant runs the run live and in silence (R9). This plan follows the existing
   drained-rollout rule and does not bump `CURRENT_SPEC_VERSION`. The owner must confirm that the
   E14 deploy uses the drained rollout. This does not block the code of this unit.
6. **Problem codes — Decided: D7 (X-8).** `replay_grant_too_large` (431), `replay_grant_ambiguous`
   (400), `replay_unsupported` (503), in the engine problem shape with a top-level `code`.
7. **Rejection body — Decided: D7 (X-8).** The engine reads `{"detail": {"code":
   "replay_grant_invalid", "reason": "<reason>", "message": ...}}` (GW-replay §4.5 step 3).
8. **Entry key on a version hit — decided (default).** GW-replay §4.5 sends
   `Cache-Status: aigateway; hit; detail=version; key="<prefix>"`. The engine reads `key=` from
   that member (`world/cache_readback.py:137`); an `X-AIGW-Cache-Key` header beside a key-less
   `Cache-Status` is ignored.
9. **Version hit and `max-age` — Decided: D7 (X-7).** A version hit is exempt from `max-age`
   revalidation (§5.8, RP-13c).
10. **`repeated_key_collapses` meaning — Decided: D7 (X-7).** It is an upper bound: every version
    hit whose key this run already served from the version.
11. **Identity — Decided: D5.** Production relies on the Cloudflare identity headers; the gateway
    checks the grant `sub` against the verified email. The engine does no subject check.
