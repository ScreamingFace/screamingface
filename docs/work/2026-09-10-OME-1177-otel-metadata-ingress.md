---
ticket: OME-1177
stack: aigateway
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-1177 — close reserved telemetry metadata ingress

## Intent

Implement the owner-approved PR903 follow-up. Block caller impersonation of LiteLLM auth metadata only. Correct the review: parameter projection already rejects caller rust, so the initial direct-handler repro did not establish a caller-accessible bypass.

## Planned changes

- request_hardening.py: strip user_api_key_auth_metadata at body and metadata.
- New test_otel_auth_metadata_ingress.py: real downstream reader and full pipeline regressions.
- test_request_hardening.py: add one name to independent exact inventory; retain all prior assertions.
- Existing spec, plan, task mirror and this ledger.

## Test plan

- RED on reserved metadata removal.
- Valid, empty and malformed reserved containers; ordinary metadata and input preservation.
- Real get_litellm_params/auth_metadata consumer through the Anthropic strip/project/prepare pipeline.
- Full gateway gates and focused checks on runtime LiteLLM 1.100.0.

## Acceptance

- Caller data cannot populate the new OTel auth metadata reader.
- Ordinary chat remains valid. Rust handling is unchanged; projection already rejects it.
- No new dependencies or live provider traffic.

## Outcome

- **Actual files:** planned files; regression file named test_otel_auth_metadata_ingress.py.
- **Commits:** this commit — fix(aigateway): strip proxy-owned telemetry auth metadata.
- **RED:** all 12 new ingress cases failed before production edit.
- **Focused GREEN:** 50 passed on LiteLLM 1.100.1; the same 50 passed with 1.100.0 first on PYTHONPATH.
- **Gates:** ALL GATES GREEN: lint, formatting, pyright, no-enterprise, full pytest (4,259 collected, including opt-in/skipped cases), 93% coverage against the 80% threshold. The initial runner flagged the one-line exact-set inventory extension. The approved additive contract change retains every prior name/assertion; rerun uses the PR's documented --skip-append-only exception. Pyright initially rejected the deliberately partial closed-call test payload; an explicit typed cast documents the fixture without suppressing diagnostics.
- **Wisdom/review:** reuse existing pure filter, no new abstraction or dependencies; actual downstream reader plus full parameter pipeline avoids the earlier Rust reachability mistake. Independent standards/spec reviews found no actionable issue.
- **Deviations:** telemetry only, per owner steering. No Rust handling change. No live telemetry/provider traffic; configured export behavior is not exercised by these ingress tests.
