---
ticket: OME-1378
stack: analytics
status: done
started: 2026-09-25
finished: 2026-09-25
---

# analytics-colab-bridge — Colab consent and browser continuity

## Intent

Implement the service-only bridge approved by the owner, following OME-1124.
Keep SDK integration in its own subsequent unit. Worktree starts at freshly
fetched origin/main e8c7d262. Existing SDK work remains in its separate worktree.

## Planned changes

- apps/analytics/src/analytics_service/bridge.py and bridge assets: consent,
  partitioned cookie ID, validated parent messaging and opt-out.
- apps/analytics/src/analytics_service/settings.py and api.py: explicit optional
  bridge settings and router composition; existing ingestion behavior preserved.
- New bridge tests, deployment notes and app guardrails updated for approved scope.
- Service spec and implementation plan before production code.

## Test plan

- Consent-only requests never mint an analytics ID or emit events.
- Unknown/stale consent denies ID; accepted consent preserves ID; decline expires it.
- Secure, HttpOnly, SameSite=None, Partitioned, host-only cookies; no-store responses.
- Reject foreign/null origins, malformed messages, oversized bodies and stale results.
- Verify revocation behavior across instances and replicas against the selected model.
- Run all analytics gates; real Colab ancestry and Chrome/Safari browser acceptance
  remain required before deployment claims.

## Acceptance

A specified, tested service bridge preserves remembered choice and opted-in browser
identity without account login, with honest cross-notebook revocation semantics.
No SDK changes, ticket filing, PR creation or deployment in this unit by default.

## Outcome

- Worktree created; audited existing service and parent spec/plan.
- Existing service is stateless. Parent spec requires cross-notebook stale-runtime
  revocation via an expiring capability and server revocation check; no concrete
  shared-state or browser-mediated delivery design exists yet.
- Owner approved browser-mediated delivery. Implementing consent checks per browser
  request without shared server revocation state. New tests failed before implementation.


## Final outcome and review

- **Actual files:** bridge HTTP adapter and packaged iframe script; optional settings
  and API wiring; Helm values/deployment/ingress; app README/guardrails; new Python
  and Node protocol tests; additive chart checks; CI Node setup; spec and plan.
- **Gates:** normal analytics gate runner passed after the final change: lock,
  lint/format, types, 93 Python tests (including eight Node protocol tests),
  99.04% branch-aware total coverage, and wheel/sdist build. Bridge Python module
  has 100% measured line/branch coverage. Helm lint and chart wiring checks pass;
  wheel contents explicitly verified to include bridge.js. No prior tests changed.
- **Commit:** `feat(analytics): add consent-gated Colab browser bridge`.
- **Deviations:** owner selected iframe-mediated delivery instead of runtime
  capabilities/shared revocation state. Consent and delivery use separate bounded
  admission budgets so disabling upstream delivery cannot prevent consent changes.
  Unknown/stale consent clears orphan identity on fresh acceptance. Cookie lifetime
  defaults to renewable 180 days, independent of the agreed 90-day event retention.
- **Wisdom:** no database, dependency or product auth introduced. Core ingestion
  remains adapter-independent; API composition injects the shared event handler.
  Browser requests validate source/origin/schema; HTTP cookie values never enter
  logs, URLs or page HTML. Old queued identity cannot silently join a new cookie.
  Decline cancels local frame work, with already-sent/concurrent requests explicitly
  excluded from instantaneous-revocation claims. Control disconnects are sanitized.
- **Remaining acceptance:** not deployed. Real Colab ancestry/pattern and Chrome/
  Safari partitioned-cookie behavior must be revalidated for these exact routes.
  Exact-origin allowlists are deliberately closed by default; per-notebook manual
  configuration is not an acceptable public rollout. SDK nonblocking integration
  and dev PostHog browser smoke remain subsequent steps, not passed tests here.
- No PR, Linear issue or deployment created. The existing local SDK worktree and
  its pending snapshot approval remain untouched.

## PR preparation

Owner authorized the draft PR and accompanying ticket. Filed OME-1378 under
OME-1305, self-assigned, analytics/agentic/autonomous, High priority.
Draft review does not imply deployment or browser acceptance.

## Local HTTPS browser smoke — 25 September 2026

Ran the unmodified service on https://127.0.0.1:19443 and a disposable parent
page on https://localhost:19444, using the machine's already trusted local CA.
No trust-store or browser privacy settings changed. The Codex in-app browser
loaded the actual packaged iframe script over HTTPS and passed 13 assertions:
remembered decline, no ID before consent, consent-only acceptance, server-issued
ID, second-iframe continuity, iframe-reload continuity, start/finish delivery,
cross-iframe opt-out, new ID after re-enable, stale-ID rejection, exactly two
forwarded batches, and no cookies serialized in PostHog payloads.

The real PostHog adapter used a mock HTTP upstream; this did not post events to
dev PostHog. The test used local parent/child origins, not Colab, and did not
exercise full Chrome/Safari restart persistence. Remote acceptance remains open.
No production code changed as a result of this test.
