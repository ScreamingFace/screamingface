# B3 — engine: capture the cache version, and replay mode

- **Worktree:** `.claude/worktrees/e14-b3-engine-cache-capture-replay` · **Branch:** `e14-b3-engine-cache-capture-replay`
- **Base:** `e14-b2-engine-tavily-cache` (B2 must be accepted first) · **Stack:** `screamingface-engine`
- **PRDs:** `prd/cache-version-capture.md` (C1–C17; TDD #1, #2, #4–#13) and `prd/reproduce.md`
  (R1, R8, R11, R17, R24; TDD #2–#6, #23). Contracts K1, K2, K3, K10. Rules: `00-common.md`.
- The gateway half (B1) is built on another branch. Code against `contracts.md`; fake the gateway
  with headers and `httpx.MockTransport`.

## Design (pinned)

### 1. A run-scoped replay tally (no change to `packages/url4`)

New shared leaf module `src/screamingface_engine/replay_outcomes.py`, modeled on
`model_outcomes.py` (same ContextVar + recorder + `capture_…()` context manager + `record_…()`
idiom, same file shape and comment density). Shared leaves are importable by `world` and `runner`
(`model_outcomes` is already imported by `world/corrective.py`), so the layering gate stays green.

```python
@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    lane: Literal["chat", "tavily"]
    replayable: bool
    revision: str | None
    reason: Literal["bypass", "write", "revision", "tool", "error"] | None  # set when not replayable

class ReplayTally:  # the recorder; mutable, owned by one run
    outcomes: list[ReplayOutcome]
    def reproducible(self) -> Literal["complete", "partial"]: ...
    def revision(self) -> str | None: ...       # the one label, or None if 0 or >1 labels
    def attributes(self) -> dict[str, str | int]: ...  # cache.revision?, cache.reproducible, cache.partial.<reason> counts
```

- `capture_replay_outcomes() -> Iterator[ReplayTally]` binds the tally. `record_replay_outcome(outcome)`
  appends to the bound tally (no-op when none is bound).
- `reproducible()` is `"complete"` iff every outcome is replayable AND all non-None revisions are
  one label AND no replayable chat outcome has `revision=None`. No outcomes → `"complete"`, and
  `revision()` is `None` (C5).
- **Verify first:** the connector's model calls run in the executor's process and inherit its
  context (this is how `model_outcomes` works). If they do not, STOP and report.

### 2. Recording (capture, normal mode)

- `world/cache_readback.py`: `CacheOutcome` gains `write: Literal["stored", "race_lost", "not_stored"] | None = None`
  and `revision: str | None = None`, read case-insensitively from `X-AIGW-Cache-Write` and
  `X-AIGW-Cache-Revision`. Keep every existing field and default (CHAR test #1 stays green).
- `world/connector.py`: after the final `read_cache_outcome` of each chat round trip (the outcome of
  the response that is consumed, not of a discarded re-issue), call `record_replay_outcome` with:
  hit → replayable; miss + `stored` → replayable; miss + other write → `reason="write"`; bypass →
  `reason="bypass"`; `revision` from the header. A round trip that raises (non-2xx after retries)
  records `reason="error"`. A transport retry counts once (C17).
- `world/web_tools.py`: after B2's lookup/fill, record a `tavily` outcome: lookup hit → replayable;
  lookup miss + fill `"stored"` → replayable; fill `race_lost` / `not_stored` / `None`, lookup
  bypass, or a Tavily failure → `reason="tool"`. The revision comes from the lookup's
  `X-AIGW-Cache-Revision` header (`TavilyLookup.headers`). No cache configured → `reason="tool"`.
- `runner/executor.py`: wrap the run in `capture_replay_outcomes()` where the run's other scopes
  are bound, and merge `tally.attributes()` into `RunSummary.cache_attributes` (and the summary
  `LogData` attributes) next to `cache_counters.attributes()`. Attribute names: `cache.revision`
  (omit when None), `cache.reproducible`, `cache.partial.bypass|write|revision|tool|error` (omit zeros).

### 3. Replay mode

- `RequestScope` gains `replay_revision: str | None = None`.
  - Sync surface: `request_scope_from_headers` reads `X-Cache-Replay` (new constant
    `CACHE_REPLAY_HEADER`); add it to the forwarded-header table next to `ANSWER_SEED_HEADER`
    (`request_scope.py:282`). Value must match `^cr-[0-9a-f]{12}$`, else the same kind of loud
    refusal as a bad `X-Answer-Seed`.
  - Run path: follow `X-Answer-Seed` end to end and copy it. `job_env.py` gets
    `CACHE_REPLAY = "URL4_CLOUD_CACHE_REPLAY"` with `cache_replay_env(...)` /
    `cache_replay_from_env(...)` (mirror `ANSWER_SEED`, `job_env.py:134`, `:273`, `:276`, `:518`);
    `runner/main.py:102` sets `replay_revision`; the start route carries the header into the job
    env the way it carries the seed.
- Ack (K3, R24): when the start route accepted a valid `X-Cache-Replay`, its 202 response (and the
  sync surface's response) echoes `X-Cache-Replay: <label>`. Add it where `_accepted(topic)` builds
  headers (`rest/routes.py`). The run is scheduled after the headers are decided; no case starts
  before.
- Chat calls (`connector.py`): when `replay_revision` is set, the body's cache field is
  `{"cache": {"only-if-cached": True, "cache-revision": <label>}}` instead of
  `policy_to_body_field(...)`, and `requires_revalidation` is skipped (no re-issue, R17).
- Revisions check (K10, R11): in replay mode, before the first chat call of the run, `GET
  /v1/cache/revisions` once (memoize the result on the tally or a run-scoped object; guard with an
  `asyncio.Lock`). 404, an error, or a label not in `known` → every chat call of the run raises
  `ResolutionError(code="unknown_cache_revision", permanent=True)` without sending the chat request.
- Gateway errors (`_raise_for_status`): a 504 whose `detail.code` is `cache_miss` or
  `cache_bypass` → `ResolutionError(code="replay_cache_miss", permanent=True)`; a 400 with
  `unknown_cache_revision` keeps that code. Add `replay_cache_miss` and `unknown_cache_revision` to
  the engine's declared codes in `error_text.py` the way the other engine codes are declared.
- Tavily (`web_tools.py`): in replay mode, the lookup sends `cache_revision: <label>`; a lookup
  `miss` or `bypass` raises the same `replay_cache_miss` failure (it must fail the case, not be
  turned into a `"… failed: …"` tool string), and Tavily is never called. No fill in replay mode.

## Files

`replay_outcomes.py` (new), `world/cache_readback.py`, `world/connector.py`, `world/web_tools.py`,
`world/tavily_retrieval_cache.py` (only to pass `cache_revision`), `request_scope.py`, `job_env.py`,
`runner/main.py`, `runner/executor.py`, `rest/routes.py` (ack + env), `error_text.py`; new tests
under `tests/unit/` only.

Exemplars: `model_outcomes.py` (module shape), the `ANSWER_SEED` path (env + header + scope),
`tests/unit/test_cache_readback.py`, `tests/unit/test_cache_run_counters.py`,
`tests/unit/test_scope_producers.py`.

## Do not

- Do not change `packages/url4` (no new fields on `ModelResponse`).
- Do not change `RunCacheCounters` semantics (hits/misses/bypasses stay as today).
- Do not honour `only-if-cached` from a user's `Cache-Control` (`cache_intent.py:114` stays).

## Verify

`python3 .claude/scripts/run_gates.py screamingface-engine --base e14-b2-engine-tavily-cache`
