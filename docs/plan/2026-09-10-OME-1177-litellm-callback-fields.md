---
ticket: OME-1177
---

# OME-1177 — plan

## Steps

1. Worktree from `origin/main` (`.claude/worktrees/OME-1177-litellm-callback-fields`).
2. Ledger, spec, plan, task mirror (this set of docs). Move OME-1177 to In Progress.
3. From `apps/aigateway/`: `uv lock --upgrade-package litellm`; inspect the resulting diff for
   unrelated transitive bumps. Fall back to `uv lock --upgrade` only if the targeted upgrade
   doesn't resolve cleanly.
4. Confirm RED: run the three target tests against the new litellm before any source edit.
5. Re-verify `_LITELLM_GLOBAL_TRUTHY_FIELDS`, `_LITELLM_GLOBAL_CALLBACK_FIELDS`,
   `_MODIFY_PARAMS_FIELD` still exist as real attributes on the new litellm (`hasattr` check,
   e.g. via a scratch script) before touching the version-pin literals.
6. Fix `_CALLBACK_DYNAMIC_FIELDS` (add the 3 fields, comment per `dd_*` precedent).
7. Add regression tests in `test_request_hardening.py`.
8. Update the two `== "1.97.0"` assertions + prose comment in `test_openai_runtime_guard.py`,
   only if step 5's re-verification is airtight; otherwise STOP and report.
9. Run `uv run .claude/scripts/run_gates.py aigateway`; expect the append-only guard to flag
   the test-file edits — that's expected (OME-735 precedent); document behavioral-equivalence
   reasoning in the ledger, then re-run with `--skip-append-only`.
10. Wisdom/confidence pass. Fill ledger Outcome.
11. Commit (conventional, `Refs: OME-1177`, no `Co-Authored-By` per CLAUDE.md — but append the
    harness-required attribution line per the current session's system instruction, noting the
    resolution in the final report).
12. Push branch, open DRAFT PR (`gh pr create --draft`), base `main`.
13. Close docs/tasks mirror; post Linear close-comment; leave Linear state as-is for GitHub
    automation to move (verify automation status first).

## Files

- `apps/aigateway/pyproject.toml`
- `apps/aigateway/uv.lock`
- `apps/aigateway/src/aigateway/core/request_hardening.py`
- `apps/aigateway/tests/unit/core/test_request_hardening.py`
- `apps/aigateway/tests/unit/openai/test_openai_runtime_guard.py`

## Risks

- `uv lock --upgrade-package litellm` may drag in unrelated transitive bumps (OME-735 saw
  fastapi/pyjwt/idna/pydantic-settings/cryptography/pydantic/uvicorn/ruff move) — if so,
  root-cause any resulting test breakage before touching a pre-existing test.
- If field-existence re-verification (step 5) finds a genuine rename/removal rather than a
  mechanical adaptation, this becomes a real product-behavior question — STOP and report
  rather than guessing.
