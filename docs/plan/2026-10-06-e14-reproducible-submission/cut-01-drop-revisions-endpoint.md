# Cut 01 — drop the revisions endpoint and the engine's pre-check

**Status:** planned, waiting for owner approval · **Date:** 2026-10-07
**Owner decision Q1 is unchanged:** old submissions stay replayable after a cache-key change.

## 1. What changes

The replay keeps using the regular chat endpoint. The only new thing on it stays: an optional
`cache-revision` field next to `only-if-cached`. If no revision is passed, the gateway uses the
current cache version, as on every normal call. The revision registry stays, so an old label still
computes its old key.

The cut removes only the separate endpoint and the engine's call to it:

| Piece | Keep / drop | Reason |
|---|---|---|
| `only-if-cached` on the chat call | keep | A miss is a 504 and never a paid call. |
| Optional `cache-revision` on the chat call (and on the Tavily lookup) | keep | Old evals replay under their old cache version. Absent → current version. |
| Revision registry, golden vectors, frozen key code | keep | Computes the old key for an old label (Q1). |
| Revision label + `X-AIGW-Cache-Revision` header | keep | Recorded on the submission; sent back on a replay. |
| `GET /v1/cache/revisions` | **drop** | The chat call already answers the same question: an unknown label is a 400 `unknown_cache_revision`, before any credential or provider. |
| Engine pre-check of the label (step 5.3) | **drop** | Same reason. The guard against an older gateway that ignores the new fields becomes the deploy rule: gateway before engine. |

## 2. Behaviour after the cut

1. A replay chat call sends `cache: {"only-if-cached": true, "cache-revision": "<stored label>"}`.
2. Known label → the gateway keys with that version: a hit is served, a miss is a 504 → the case
   fails with `replay_cache_miss`.
3. Unknown label (for example, a gateway older than the score) → 400 `unknown_cache_revision` on
   each call, with no provider call → each case fails with `unknown_cache_revision`, and
   `sf.reproduce` reports `failed / unknown_cache_revision`. This is the same result as today; it
   now comes from the chat call instead of the pre-check.
4. A gateway older than B1 does not know the two fields. It treats them as unknown controls and
   bypasses the cache, which can call a provider. The pre-check was the only guard; after the cut
   the deploy rule is the guard (gateway first, then engine workers, then the App). The SDK still
   requires the `cache.replay` statement, and the run still records each call's revision.

## 3. Changes by PR

The stack and the PR count do not change. Each change is one new commit on its own branch, then the
branches above are rebased.

### B1 — gateway (small)
- Remove `routes/cache_revisions.py` (`GET /v1/cache/revisions`), its router line in `main.py`, and
  its tests (TDD #21 / G21).
- Nothing else changes.

### B2 — engine Tavily cache
- No change.

### B3 — engine
- Remove the revisions pre-check: the GET, the per-run memo and its lock, the deadline handling, and
  their tests (the K10 tests, incl. the concurrent "one GET" test).
- Keep: `cache-revision` and `only-if-cached` in the replay chat body; `cache_revision` in the
  replay Tavily lookup; the mapping of a 400 `unknown_cache_revision` and a 504 to case failures;
  the tally, capture attributes, `X-Cache-Replay`, the start-route echo, `cache.replay`, D1–D3.
- README "Replay mode": drop the pre-check; state the deploy rule as the guard.

### A1, B4, A2, B5
- No change. (`sf.reproduce` keeps the reason `unknown_cache_revision`; it now comes from the chat
  call.)

### C1 — docs
- Remove any mention of the engine checking the label before the run; the outcome table keeps
  `unknown_cache_revision`.

### Spec
- `contracts.md`: remove K10; in K1 say an unknown label is the per-call 400 that a replay relies on;
  K3 drops the pre-check.
- `prd/gateway-cache-revision.md`: remove G21 and TDD #21.
- `prd/reproduce.md`: R11 — the 400 comes from each chat call; no pre-check.
- `00-overview.md` §6: B1 and B3 descriptions.

## 4. Order of work

1. Spec docs (this branch).
2. B1 commit → gates.
3. B3 commit (rebased on the new B1 and B2) → gates.
4. C1 commit (after rebasing A1 → B4 → A2 → B5 onto the new B3) → docs build.
5. Final gates at the top of the stack, a design review of the B1 and B3 commits, then update the
   walkthrough artifact.

Model routing as before: a Sonnet implementer from this plan, then an Opus design review.

## 5. Size

Small: about −40 lines in B1 (route and tests), about −250 in B3 (pre-check, memo, lock, deadline and
tests), a few lines of docs. A few hours.

## 6. Risks

| Risk | Mitigation |
|---|---|
| A replay against a gateway older than B1 bypasses the cache and pays a provider. | Deploy rule: gateway before engine. The SDK still requires `cache.replay`; each call's revision is recorded. |
| Every call of a replay with an unknown label makes one round trip that fails. | Each fails fast with a 400 before any credential or provider; the cost is round trips only. |
