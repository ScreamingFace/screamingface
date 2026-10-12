# F-B1 — gateway: frozen copy store, capture on chat, replay endpoints

- **Worktree:** `.claude/worktrees/e14-b1-gateway-frozen-copy` · **Branch:** `e14-b1-gateway-frozen-copy`
- **Base:** `e14-reproducible-submission-spec` · **Stack:** `aigateway`
- **Design:** `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` §3, §4, §9 (binding).
  Rules: `00-common.md`. This replaces the old cache-revision B1 entirely (branch `e14-old-b1-cache-revision`
  is history only; do not copy from it).

## Files

| File | Change |
|---|---|
| `src/aigateway/core/frozen_copy/__init__.py`, `models.py` | `FrozenCopy`, `FrozenCopyEntry` (design §3) |
| `src/aigateway/core/frozen_copy/store.py` | `FrozenCopyStore`: `open(account_id)`, `get(id)`, `seal(id, account_id)`, `capture(copy, kind, request, response, status_code)`, `find(copy, kind, request, occurrence)`; digest via `core/request_cache/canonical.py` `canonical_digest` |
| `src/aigateway/db.py` | register `aigateway.core.frozen_copy.models` in the model list |
| `src/aigateway/migrations/00NN_frozen_copies.py` | next number after the latest; exemplar `0002_oauth_connections.py` |
| `src/aigateway/config.py` | `frozen_copy_max_entry_bytes: int = 2_000_000` |
| `src/aigateway/routes/frozen_copies.py` | the five routes of design §4.3; include in `main.py` next to `chat.router` |
| `src/aigateway/routes/chat.py` | capture hook (design §4.2) |
| `tests/unit/test_frozen_copy_*.py` | new files only |

## Decisions (pinned)

- **Digest point (chat):** the `body` dict right after the gateway-level dispatch-control strip
  (`chat.py`, after `parse_global_cache_controls` pops `cache` and `strip_dispatch_controls` runs; before
  provider lookup). Factor that preparation into one helper used by both `/v1/chat/completions` and the
  replay route, so the two digests can never drift. Digest material: `{"kind": "chat", "request": body}`.
- **Copy check (capture):** after the body is parsed and before the cache stage. Valid = exists, owner is
  `current.id`, status `open`, and `body.get("stream")` is not true. Invalid → serve normally,
  header `X-AIGW-Capture: refused`.
- **Capture points:** the cache-hit return and the live-success return (store the body exactly as returned,
  after `attach_*_metadata`). Errors: wrap the part of the route after the copy check so that an
  `HTTPException` raised by dispatch/provider/parameter steps is captured (`status_code`,
  `response_json = {"detail": exc.detail}`), gets the `X-AIGW-Capture` header added to `exc.headers`, and is
  re-raised unchanged. Await the insert; catch every exception from it → `failed`, log one line (copy id,
  digest prefix 12, kind; never the prompt). Size over the cap → `failed`.
- **Ownership:** `account` FK to the caller (`CurrentAccount`). Seal and tool-results by a non-owner → 404
  (do not reveal existence). Replay routes are open to any authenticated account (design Q16).
- **Seal:** idempotent; sets `entries` (count) and `sealed_at`. Capture against a sealed copy → `refused`;
  tool-results against a sealed copy → 409 `frozen_copy_sealed`.
- **Replay (chat):** same request model as `/v1/chat/completions` (raw JSON body); apply the shared
  preparation helper; header `X-AIGW-Replay-Occurrence` (non-negative int, default 0; malformed → 400
  `malformed_replay_occurrence`). Lookup rule exactly as design §4.4. Copy unknown or not sealed → 404
  `{"code": "frozen_copy_unavailable", "message": …}`; no entry → 404 `{"code": "frozen_copy_miss", …}`.
  A found error → `HTTPException(status_code=<captured>, detail=<captured detail>)`. A found success →
  the captured body with its `_aigw` call cost set to 0 and `"frozen_copy_replay": true` added there
  (read `attach_success_metadata`/`attach_hit_metadata` to find the exact `_aigw` shape; do not invent a
  new block). Header `X-AIGW-Replay: hit|error`. No credential, plugin, provider, model check or cache use.
- **Tool routes:** body `{"description": object, "result": str}` for capture (digest material
  `{"kind": "tool", "request": description}`), `{"description": object}` for lookup; lookup also takes
  `X-AIGW-Replay-Occurrence`.
- **Order of capture rows:** `(created_at, id)`.
- **No list or read-back endpoint** for stored requests (design F2).

## TDD list (risk order)

1. `replay_never_resolves_credentials_or_calls_a_provider` (spy on dispatch and credential resolution).
2. `capture_and_replay_digest_match_for_the_same_body` (property over a few bodies; cache control and
   dispatch controls present or absent).
3. `capture_stores_a_cache_hit_and_a_live_success_identically_shaped`.
4. `capture_failure_never_fails_the_call` (store raises → 200 + `X-AIGW-Capture: failed`).
5. `capture_refused_for_unknown_foreign_sealed_copy_or_stream`.
6. `provider_error_is_captured_and_replayed_with_the_same_status_and_detail`.
7. `replay_lookup_rule`: occurrence n, past the end → last, no success → latest error, nothing → 404 miss.
8. `replay_of_open_or_unknown_copy_is_404_unavailable`.
9. `replay_body_reports_zero_cost_and_marks_frozen_copy_replay`.
10. `seal_is_owner_only_idempotent_and_counts_entries`; `capture_after_seal_is_refused`.
11. `tool_results_capture_and_lookup_round_trip`; sealed → 409; non-owner → 404.
12. `entry_over_the_size_cap_is_failed_not_stored`.
13. `no_capture_without_the_header` (the chat route is byte-identical to today: no new header, no row).
14. Migration applies on SQLite; model ↔ migration match (`makemigrations` reports no changes).

## Verify

`uv run .claude/scripts/run_gates.py aigateway --base e14-reproducible-submission-spec`
