---
ticket: OME-1044
stack: aigateway
status: done
started: 2026-08-31
finished: 2026-08-31
---

# OME-1044 — Store and serve Tavily retrieval results in the global cache

## Intent

Tavily-backed retrieval (`web_search` / `web_fetch`) runs inside the Runner Job and never
traverses aigateway, so it has no cache. An identical request pays Tavily **and** the model
again on every run. The larger half of that cost is second-order: the global cache hashes
`messages` verbatim, and a tool result is appended to `messages`, so non-deterministic Tavily
output permanently poisons the continuation chat call's key — turn 1 hits cache while the
expensive tool-augmented continuation always misses.

This unit adds the aigateway half: a Tavily retrieval cache lane that derives its key
server-side and stores an opaque result string. aigateway never holds a Tavily credential and
never calls Tavily — the Runner keeps both (owner decision, this session). OME-1045 wires the
Runner to it.

## Planned changes

- `apps/aigateway/src/aigateway/core/request_cache/tavily_retrieval.py` — new. The pure key
  DTO (`TavilyRetrievalCacheKey`), `tavily_retrieval_key()`, target normalization, and the
  contract revision constant.
- `apps/aigateway/src/aigateway/core/request_cache/tavily_store.py` — new.
  `TavilyRetrievalCacheStore` over the existing `request_cache_entries` table
  (`provider='tavily'`, `model=<tool>`, `prompt_hash=key_hash`, `expires_at=NULL`), mirroring
  `TortoiseRequestCacheStore`'s exception discipline.
- `apps/aigateway/src/aigateway/routes/tavily_retrieval_cache.py` — new. The two endpoints.
- `apps/aigateway/src/aigateway/main.py` — register the router + store on `app.state`.
- `apps/aigateway/DEPLOYMENT.md` — document the lane, and that the shared table now holds
  Tavily rows (the "rows never expire" contract stays true: this lane also writes NULL).
- Tests under `apps/aigateway/tests/unit/tavily_retrieval/` plus
  `tests/unit/test_canonical_digest.py`.
- **No `config.py` change and no chart change.** The lane is unconditional (owner decision
  mid-iteration: "we don't need another layer of configuration. Tavily cache must be enabled
  always"). A drafted `AIGW_TAVILY_RETRIEVAL_CACHE_ENABLED` setting plus its
  `values.yaml`/`configmap.yaml` wiring was written and then removed.
- Also touched, to share the canonical form rather than duplicate it:
  `core/request_cache/canonical.py` (new leaf) and `core/request_cache/global_keys.py`
  (imports it; public surface unchanged), plus a private→public rename of
  `INFRASTRUCTURE_ERRORS` in `core/request_cache/store.py`.

## Test plan

RED first, in this order:

1. `tavily_retrieval_key` accepts no identity/profile/credential input and performs no I/O.
2. Two different `excluded_domains` sets never produce one key — the leakage guard.
3. A differing `max_results` or `search_depth` keys differently.
4. Target normalization: URL lowercases scheme+host, drops default port and fragment, keeps
   path case, query string and `utm_*`; query is stripped + NFC with case preserved.
5. `web_fetch` ignores `search_depth`/`max_results` entirely (not part of its key).
6. Store: first-fill-wins under a simulated race; the winner's row is kept (`race_lost`).
7. Store: an infrastructure error answers `not_stored` and never raises.
8. Route: a hit returns the stored result plus `Cache-Status: aigateway; hit`; a miss returns
   `status:"miss"` with `fwd=miss`; both are `200`.
9. Route: `enabled=false` ⇒ `status:"bypass"`, `reason:"disabled"`, and nothing is written.
10. Route: `422` for unknown provider/tool, empty target, out-of-range `max_results`,
    malformed `excluded_domains`, oversized `result`.
11. Route: a fill for a key already present answers `race_lost` and does not overwrite.

## Acceptance

- Both endpoints behave as specified, with `Cache-Status` + the `X-AIGW-Cache*` triple so the
  Runner's existing `read_cache_outcome` parser reads them unchanged.
- The key is a pure function of the request description; no identity term exists on its
  signature.
- Cache failure is always a bypass or `not_stored`, never an exception into the route.
- Disabled by default in the app, enabled by default in the chart.
- aigateway gates green (`ruff`, `ruff format`, `pyright`, `check_no_enterprise`, `pytest`
  with `--cov-fail-under=80`).

## Outcome

- **Actual files:** as planned, minus the `config.py` and chart changes (see Deviations), plus
  three files the canonical-form sharing required:
  - new: `core/request_cache/canonical.py`, `core/request_cache/tavily_retrieval.py`,
    `core/request_cache/tavily_store.py`, `routes/tavily_retrieval_cache.py`
  - modified: `core/request_cache/global_keys.py` (imports the leaf; public surface and
    `canonical_key_material` bytes unchanged), `core/request_cache/store.py`
    (`_INFRASTRUCTURE_ERRORS` → `INFRASTRUCTURE_ERRORS`, mechanical), `main.py`,
    `DEPLOYMENT.md`
  - tests: `tests/unit/test_canonical_digest.py`,
    `tests/unit/tavily_retrieval/{test_tavily_retrieval_key,_store,_routes}.py`

- **Gates:** `uv run .claude/scripts/run_gates.py aigateway` → **ALL GATES GREEN**
  (append-only test check, ruff check, ruff format --check, pyright, check_no_enterprise,
  pytest `--cov=aigateway --cov-fail-under=80`). Suite: **4164 collected**, of which **56 new**.

- **Deviations:**
  1. **No configuration and no chart change.** An `AIGW_TAVILY_RETRIEVAL_CACHE_ENABLED` setting
     (app-off/chart-on, mirroring the response cache) was implemented and then **removed**
     mid-iteration on the owner's instruction: "We don't need another layer of configuration.
     Tavily cache must be enabled always." The lane is now unconditional; the store takes no
     availability gate and a test pins that so a config layer cannot creep back.
  2. **`tortoise-dev` companion skill was NOT invoked** — it is `mandatory: true` in the card and
     its `when` clause matches (queryset + transaction work), but the plugin is not installed
     anywhere on this machine. Raised twice; the owner directed the work to proceed regardless.
     Recorded as an **owner waiver**. Mitigating facts: this unit adds no model and no migration
     (stack rule S1 is not engaged), reuses the existing `RequestCacheEntry`, and mirrors
     `TortoiseRequestCacheStore`'s exception discipline and clause ordering verbatim.
  3. **Canonical form extracted to a new leaf module** rather than duplicated. The owner's own
     proposal (one guarded public wrapper instead of three exposed primitives) was adopted and
     is what makes the guard non-optional; the leaf placement was chosen over adding the wrapper
     to `global_keys.py` so the retrieval lane does not import the chat lane's machinery. The
     chat lane's own suite passes unmodified, which is the evidence the move is
     behaviour-preserving.
  4. Two of my own tests written earlier in this same RED step were restated before GREEN (the
     `__all__` surface assertion became "every export applies the guard", and a
     `# type: ignore` was replaced with a typed helper). No test from a prior cycle was touched
     — the gate's append-only check confirms this.

- **Commits:** two, on branch `OME-1044-tavily-retrieval-cache`:
  - `feat(aigateway): cache Tavily retrieval results in the global cache`
  - `docs(work): finalize the OME-1044 ledger outcome`

  AIDEV-NOTE: identified by MESSAGE, not by sha, on purpose. The branch was rebased onto
  `origin/main` before the PR (which rewrote both shas), and the repo squash-merges, so every
  pre-merge sha is ephemeral. The durable one is the squash commit on `main` — recorded in the
  Linear close-comment per the card's `close_template`, which is the right place for it.

---

## Review follow-up iteration — 2026-09-04 (RFC 9211 `key` quoting)

Same ticket, same PR (#782), post-approval. Kept in this ledger rather than a second file,
matching the earlier `fix(aigateway): address OME-1044 review findings` iteration.

### Intent

PR #782's approving review (HupBaHa, 2026-09-04) left one non-blocking nit: the
`Cache-Status` `key` parameter is emitted bare (`key=a1b2c3d4e5f6`). RFC 9211 §2.7 types
`key` as a **String** — "The value of 'key' is a String that conveys a representation of the
cache key" — and an RFC 8941 String is quoted. A bare hex prefix serializes as a Token, so a
strict consumer reads a type mismatch rather than a key.

The nit is narrow and correct: `fwd` is a Token (§2.2) and `detail` is "either a String or a
Token" (§2.8), so `fwd=miss` and `detail=cache_unavailable` are already conformant and do NOT
change.

### Planned changes

- `apps/aigateway/src/aigateway/routes/tavily_retrieval_cache.py` — `_cache_status_value()`
  emits `key="<prefix>"`. The docstring's rationale is wrong today ("every value is an RFC
  8941 Token … so nothing needs quoting"): the RFC fixes `key`'s type regardless of whether
  the content needs escaping. Replaced with the per-parameter citation.
- `apps/aigateway/tests/unit/tavily_retrieval/test_tavily_retrieval_routes.py` — the prior
  test `test_a_hit_publishes_the_rfc_9211_cache_status_header` asserts the bare form; it is
  the test that encodes the defect. **Prior-test edit — see Deviations.**
- `docs/spec/2026-08-31-OME-1043-tavily-retrieval-cache.md:101` — the spec's own example is
  where the bare form came from. The code obeys the spec, so a code-only fix would leave the
  defect in the source of truth.

### Test plan

RED first: change the route test to the quoted form and confirm it fails against the current
emitter for exactly that reason (bare vs quoted), then GREEN with the one-line emitter change.
Coverage of the surrounding contract is unchanged and stays green: `fwd=miss`,
`fwd=bypass; detail=…`, and the 12-character prefix equality with `X-AIGW-Cache-Key`.

No consumer change is needed. The Runner's parser (`runner/cache_readback.py::_unquote`)
returns an undelimited value unchanged and already covers the quoted form at
`tests/unit/test_cache_readback.py:240`, and the legacy `X-AIGW-Cache-Key` fallback is
untouched. `Cache-Status` has no other producer or consumer in `apps/` or `packages/`.

### Acceptance

- A hit emits `Cache-Status: aigateway; hit; key="<12-hex prefix>"`.
- `fwd=miss` / `fwd=bypass; detail=<reason>` are byte-identical to before.
- The spec example and the code agree again.
- aigateway gates green.

### Outcome

- **Actual files:** as planned, plus one sentence of spec prose so the quoting is a stated
  contract rather than a detail readers must infer from an example.
  - modified: `routes/tavily_retrieval_cache.py` (`_cache_status_value` emits
    `key="<prefix>"`; the docstring now cites the per-parameter RFC type),
    `tests/unit/tavily_retrieval/test_tavily_retrieval_routes.py`,
    `docs/spec/2026-08-31-OME-1043-tavily-retrieval-cache.md`
  - `fwd=miss` and `fwd=bypass; detail=<reason>` are byte-identical to before.

- **RED → GREEN:** the route test failed on exactly the two quote characters
  (`- key="fa76935da884"` / `+ key=fa76935da884`) and nothing else, then passed on the
  one-line emitter change.

- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --skip-append-only` →
  **ALL GATES GREEN** (ruff check, ruff format --check, pyright, check_no_enterprise,
  pytest `--cov=aigateway --cov-fail-under=80`).

- **Blast radius — a wire contract changed, and it is safe:**
  - The Runner's parser strips no delimiters it did not find: `_unquote`
    (`apps/screamingface-engine/src/screamingface_engine/runner/cache_readback.py`) returns
    an undelimited value unchanged, so it read the bare form and reads the quoted one. The
    quoted form is already covered at `tests/unit/test_cache_readback.py:240`, which is the
    evidence this is a no-op for the consumer.
  - The legacy `X-AIGW-Cache-Key` fallback is untouched, so an older Runner is unaffected
    either way.
  - `Cache-Status` has no other producer or consumer in `apps/` or `packages/` — this lane is
    the repo's only emitter. No engine-side change was needed and none was made.

- **Deviations:**
  1. **A prior test was edited** — `test_a_hit_publishes_the_rfc_9211_cache_status_header`.
     Normally a Confidence-Gate stop (rule 5). Here the test IS the defect: it pinned the
     non-conformant bare form, so no append-only path to the fix exists. The owner approved
     this specific edit in-session, after the file and line were named. The edit strengthens
     the assertion — it adds the quoting invariant and its RFC citation, and weakens nothing.
     The sanctioned escape `--skip-append-only` was used; every other gate ran in full.
  2. **The spec was corrected, not just the code.** `docs/spec/…-OME-1043-…md:101` is where
     the bare form originated, so the implementation was spec-conformant and the defect lived
     in the source of truth. A code-only fix would have left the two disagreeing.
  3. **No RFC 8941 String serializer was added** (YAGNI). The value is a prefix of a hex
     digest, so no character in it can ever need an escape; an `AIDEV-NOTE` records that
     reasoning rather than a helper nobody else calls.
  4. **`detail` deliberately stays bare.** RFC 9211 §2.8 types it "either a String or a
     Token", so the reason vocabulary is already conformant. The review scoped the nit to
     `key` and that scoping is correct — widening it would have changed a conformant header
     for no reason.
