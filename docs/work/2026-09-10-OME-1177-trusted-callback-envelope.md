---
ticket: OME-1177
stack: aigateway
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-1177 — Block caller-supplied trusted callback envelope

## Intent
Implement the user-approved PR903 review fix: do not let callers impersonate LiteLLM proxy-stamped callback settings.

## Planned changes
Request hardening filter; append independent exact-set inventory; new regression tests; spec/plan follow-up and this ledger.

## Test plan
RED: caller-supplied envelope survives filtering and reaches real LiteLLM trusted initializer. GREEN: strip entire envelope irrespective of shape; keep ordinary metadata and input unchanged. Full gateway gates and package-runtime callback tests.

## Acceptance
No caller-supplied trusted callback envelope reaches provider dispatch; existing tests preserved, inventory extended for the approved control field.

## Outcome
- RED: six new parameterized cases failed before production edit.
- GREEN:37 focused tests passed on gateway1.100.1 and packaged-runtime1.100.0.
- Full run_gates.py aigateway passed: lint, format, pyright, no-enterprise, full pytest and80% coverage floor.
- Deviation: append-only gate flagged the intentional one-field extension of the independent exact-set inventory. User approved blocking the whole envelope; its contract mirror necessarily expands. No assertion or existing coverage was deleted/weakened. Remaining gates rerun with --skip-append-only.
- Wisdom: one additional blocked field uses existing boundary; no new abstractions, dependencies, public features, secrets, or mutable input. Tests use real downstream trust readers and malformed inputs. Confidence >=95%.
- Actual files: planned filter/inventory/new tests/spec/plan plus this ledger. Existing review ledger stays local.
- Commit: fix(aigateway): reject caller-supplied trusted callback settings (Refs: OME-1177).
- PR and Linear descriptions updated to distinguish conditional callback effects and the version split. PR remains unmerged.
