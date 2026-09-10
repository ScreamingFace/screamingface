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

## Approved review follow-up

The user approved fixing PR903 review: strip the entire internal `litellm_trusted_callback_vars` container at ingress. Add regression coverage showing caller-controlled New Relic/Datadog values never reach LiteLLM trusted initialization, retain ordinary metadata, and leave input unmodified. Append the field to the existing exact-set test inventory; this extends the approved filter contract without removing coverage. Run RED before production edit, then focused tests and all gateway gates. Commit and push to the existing PR; do not merge.


## Approved second review follow-up

The owner asked to add the security review fixes now. Comparison of installed 1.97.0 and 1.100.1 shows new native chat dispatch and OTel auth-metadata routing. The complete gateway pipeline already rejects caller `rust` as unknown; the earlier direct-handler reproduction omitted parameter projection and did not establish an ingress bypass. The owner narrowed this follow-up to the confirmed telemetry gap; do not change Rust handling. Strip `user_api_key_auth_metadata` from body and metadata: this container survives projection and reaches the new OTel trusted reader. Preserve other metadata and caller input. Native execution enabled by the operator's `LITELLM_RUST` environment is a separate configuration concern; this change does not claim to disable it.

1. Add regression tests for the full strip/project/prepare pipeline and real OTel auth-metadata reader, including malformed containers and input preservation. Confirm RED.
2. Extend metadata reserved-name set, and the independent exact-set test inventory (additive contract extension; preserve all prior assertions).
3. Run focused tests, full gateway gates, review, commit, and push PR #903 without merging.
