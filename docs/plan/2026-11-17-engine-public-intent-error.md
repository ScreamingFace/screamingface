# Engine public `intent_error` — Implementation Plan

**Goal:** the sync url4 answer reports `code: "intent_error"` (message withheld) instead of `internal_error`.
**Spec:** `docs/spec/2026-11-17-engine-public-intent-error.md`
**Stack:** python (apps/screamingface-engine), uv, pytest, ruff, pyright.

## Global Constraints

- `ENGINE_ERROR_CODES` and `ENGINE_RESERVED_CODES` do not change.
- The refusal message never reaches the HTTP body.

## Review Focus

1. An `intent_error` whose message carries a provider secret or path: body shows the code, not the text.
2. An upstream `intent_error` still maps through `_raise_for_status` (the code is not reserved).
3. The three sets are pairwise disjoint.
4. Any other unvouched code (e.g. `provider_error`) is still scrubbed to `internal_error`.
5. `permanent: true` survives on the answer.

### Task 1: the set and the boundary

**Files:** `apps/screamingface-engine/src/screamingface_engine/error_text.py`,
`.../rest/routes.py`, test `apps/screamingface-engine/tests/unit/test_terminal_error_detail.py`.

- [ ] RED: add, next to the control-plane tests,
  - `test_intent_error_is_reported_as_itself_without_its_message` (RF1, RF5): terminated `failed`
    with `ErrorInfo(code="intent_error", message=f"openrouter … /srv/engine {PROVIDER_SECRET}",
    permanent=True)` → `body["code"] == "intent_error"`, `body["detail"] == "the run failed"`,
    `body["permanent"] is True`, secret and path absent from the raw body;
  - `test_public_unvouched_codes_are_not_reserved_and_disjoint` (RF2, RF3);
  - `test_an_unlisted_code_is_still_scrubbed` (RF4), if no existing test already pins it.
- [ ] Run: `cd apps/screamingface-engine && uv run pytest tests/unit/test_terminal_error_detail.py -q` → new tests fail.
- [ ] GREEN: add `PUBLIC_UNVOUCHED_CODES` to `error_text.py` (+ `__all__`, WHY docstring), use it in
  `_sanitized_error`, update its docstring.
- [ ] Gates: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q -n auto`.
- [ ] Commit: `fix(engine): report intent_error on the synchronous url4 answer, message withheld`.

### Task 2: proof

- [ ] Re-run the image-input matrix (`e2e-image-input-matrix` worktree) with this diff applied to its
  working tree only; the mistral url4 cells must read `refused`. Record in both ledgers.
