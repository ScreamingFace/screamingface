---
ticket: OME-1198
stack: aigateway
status: done
started: 2026-09-14
finished: 2026-09-14
---

# OME-1198 — Pin AIGateway Profile and Connection resolution behaviour with characterisation tests

## Intent

Stage 0 (gateway half) of the adapter-first convergence (`OME-1138`). Before the resolver cluster in
`routes/chat_credentials.py` is relocated behind the provider-access port (A1, `OME-1200`), pin the
behaviours it exhibits today that no existing test asserts, so the relocation has a parity net.
Legacy behaviour is recorded exactly, not fixed or simplified. No change under `apps/aigateway/src`.

## Planned changes

- `apps/aigateway/tests/unit/test_profile_resolution_characterisation.py` (new; tests only).

## Test plan

- Profile named `default` (authenticated) wins over an active OAuthConnection for the same
  account and provider when both exist (chat resolves to the Profile; the Connection is not used).
- Whitespace-only `X-Profile` behaves as an absent header: it selects the Profile named `default`
  (pinned through the same observable outcome as an absent header).
- After `DELETE` of the Profile, the same selector still reaches the shadow OAuthConnection created
  by the Profile OAuth completion via the label-match fallback (`routes/chat_credentials.py:170-212`)
  — documents current behaviour and its risk (F6).
- A persistent `ProfileIndexStore.get` fault at the resolver read (`chat_credentials.py:224-225`)
  escapes as an unhandled exception (documents today's outcome; class-level patch pattern as in
  `test_chat_global_cache_effective_request.py:536`).

## Acceptance

- All new tests pass at HEAD 17048f5d with `apps/aigateway/src` untouched; existing tests unedited.
- aigateway gates green (ruff, format, pyright, enterprise guard, full suite with coverage).

## Outcome

- **Actual files:** `apps/aigateway/tests/unit/test_profile_resolution_characterisation.py`
  (new, 9 tests, 360 lines). Nothing under `apps/aigateway/src` changed; no existing test edited
  (append-only check vs 17048f5d green).
- **What is pinned (all green at HEAD 17048f5d):**
  1. Profile `default` wins over an active Connection — absent header and explicit
     `X-Profile: default` both dispatch with the Profile token.
  2. Whitespace-only `X-Profile` (`"   "`, `"\t"`, `" \t "`) yields the same status and
     `detail` as an absent header (409 `connection_ambiguous` with two active Connections and
     no Profile); control test proves a named label still selects by label.
  3. After a Profile OAuth completion (mock token exchange) the shadow Connection has label
     `default` and status `active`; `DELETE` of the Profile returns 204, the Profile credential
     is gone, the Connection row and its credential survive, and chat with the `default`
     selector dispatches with the Connection's token.
  4. A persistent `profile_index.get` fault at the resolver read escapes as the raw
     `RuntimeError` (nothing dispatched) and renders as Starlette's bare 500, not the gateway's
     JSON `detail` envelope and not 503 `profile_index_conflict`.
- **Commit:** `test(aigateway): characterize profile resolution` (this commit).
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base 17048f5d` → ALL GATES GREEN
  (append-only test check, ruff check, ruff format --check, pyright, check_no_enterprise,
  pytest with coverage ≥80%). First run failed only on `ruff format --check` for the new file;
  reformatted, re-run green. Counts (separate `uv run pytest --cov=aigateway -q` run, same
  tree): 4190 passed / 58 skipped, total coverage 93%.
- **Deviations:** the blank-header pin compares `detail` bodies rather than whole JSON bodies —
  the `_aigw.usage_accounting.gateway_call_id` envelope field differs per call by design.
  The reachability and fault behaviours are recorded, not fixed (owner constraint).
