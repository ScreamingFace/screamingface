---
ticket: OME-1152
stack: analytics
status: done
started: 2026-09-09
finished: 2026-09-09
---

# Analytics ingestion implementation

## Intent

Implement the merged OME-1152 service contract, independently of SDK and bridge work. Owner explicitly requested implementation after PR #871 merged.

## Planned changes

apps/analytics: typed contract, core delivery port/use case, PostHog adapter, settings, HTTP boundary, CLI, tests, lockfile, Dockerfile, chart and operator README. Register CI, CODEOWNERS, dependabot and analytics gates. Update issue mirror.

## Test plan

RED first: strict consent/event schema, all outcomes, privacy rejection, age/scope/batch limits, duplicate conflict, HTTP limits, bounded retries and immutable payloads, disconnect, health/drain, configuration/redaction. Mock PostHog only. Run analytics gates at 95% coverage, package build, chart render and image smoke where available.

## Acceptance

Four event types only; explicit origin and usage mode; upstream acceptance semantics; total 1.5-second bounded delivery; no payload persistence, enrichment or logging. Independently packaged service and reviewable PR. Live test-project smoke and public deployment remain pending external configuration, not claimed by mock tests.

## Outcome

- Actual files match the planned service, chart, CI, registry and mirror scope. No SDK/bridge edits.
- RED: initial contract/HTTP/adapter tests failed on absent implementation. Additional tests exposed event-size status ordering, invalid destination ports, and failed-lifespan cleanup; fixed without removing prior assertions.
- Gates: analytics run_gates.py passed lock, lint, formatting, types, 64 tests with 99.03% statement/branch coverage (95% floor), and wheel/sdist build. Helm 3.17.3 lint plus disabled/enabled render-and-wiring assertions passed. Whitespace checks passed.
- Wisdom review: core uses EventDelivery only; HTTP owns admission/response semantics; adapter owns mapping/deadline. No speculative shared package, DB, identity or browser work. Privacy inputs rejected before forwarding; no raw values in response/logs. Cancellation cleans up tasks. Existing product tests remain untouched.
- Commit: f7da4c0b — feat: add bounded analytics ingestion service (Refs: OME-1152). PR: https://github.com/ScreamingFace/screamingface/pull/873.
- Deviations/limits: no local Docker daemon; the CI image build/start passed, along with Python 3.12/3.13 and chart jobs (run 34351299448). Release status explicitly not released; no image publishing or public endpoint configured. Live test-project PostHog smoke, retention enforcement and production ingress remain owner-configured rollout gates. The issue remains open pending those acceptance steps; this ledger completes code/PR preparation only.
