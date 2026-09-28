---
ticket: OME-1195
stack: aigateway
status: done
started: 2026-09-14
finished: 2026-09-14
---

# OME-1195 — Gateway execution access discovery

## Intent

Expose the missing execution-access configuration fact for OME-1042 using existing model discovery. Owner approved the Gateway implementation and draft PR in conversation on 2026-09-14.

## Planned changes

- Extend `apps/aigateway/src/aigateway/routes/model_parameters.py` with a caller/profile-bound execution-access status derived from the already resolved credential target and provider declarations.
- Add `apps/aigateway/tests/unit/test_model_execution_access.py` with behavioral coverage; preserve existing tests.
- Document the response field in `apps/aigateway/README.md`; record spec, plan and task mirrors for the linked Gateway-first delivery.

## Test plan

- First prove missing default credentials and Gemini environment access cannot currently be distinguished in discovery.
- Cover stored API-key/OAuth targets, no-auth provider, absent/present Gemini key, named-profile failures and caller isolation.
- Assert discovery never invokes inference or credential injection and returns no secrets; existing datasheets and cache/error contracts remain intact.
- Run the full aigateway gate runner.

## Acceptance

- Existing model-details discovery exposes configured/missing execution access without new endpoints, inference, refresh, credential validation or secret disclosure.
- Credential-target errors retain their existing response types. No Engine or Client implementation in this unit.

## Outcome

- Production delta: 13 added lines in the existing model-details route; no new endpoint or dependency. Added README contract guidance and 11 parameterized behavioral test cases.
- RED: six new cases failed on missing `execution_access`; one test import was corrected. Existing error-path cases already passed.
- Targeted assertions: 28 passed across the new tests and existing model-details suite. The initial run lingered because the new connection test used a separate database event loop. Seeded its connections through TestClient.portal instead; the corrected run passed 28 tests and exited 0 in 9.50 seconds.
- Gate attempt 1: lint/format passed; typecheck caught a missing AuthType annotation in the new test helper. Corrected. Attempt 2 was interrupted at 43% to include the test-cleanup correction; final full run underway.
- Wisdom review: reuse target resolution and provider hooks; no duplicated provider inventory. Additive context field leaves static contracts available and does not imply credential validity. No secret payload is exposed; discovery errors stay typed. No ORM implementation/schema/migration or prior tests changed.
- Full gate attempt 3: 4,249 passed, 58 skipped, coverage 92.61%; only existing `test_unknown_user_timing_close_to_wrong_password` failed (14.1% timing difference versus 10% tolerance). No auth code or existing tests changed. The unchanged isolated timing test also failed, this time with the opposite ordering (missing user slower by 38.5%, versus faster in the suite), indicating timing instability on this host. Full unchanged gate rerun underway. Commit pending.
- Deviations: existing endpoint extension replaces the earlier separate-preflight proposal in PR #928.

- Scope simplification: verified existing Engine model-details adapter/REST proxy forwards response bytes and accepts unknown fields, with byte-preservation tests already present. Canceled planned OME-1196; Client now depends directly on Gateway. No Engine changes needed.

- Final full rerun: `uv run .claude/scripts/run_gates.py aigateway` exited 0, ALL GATES GREEN (append-only, lint, format, typecheck, no-enterprise, full pytest with 80% coverage floor). Previous complete run measured 92.61% coverage. No test exclusions, threshold changes or auth changes.
- Commit: `feat(aigateway): expose execution access in model discovery` (Refs: OME-1195). Delivery is a draft PR; Linear Gateway unit stays open for review.
