# OME-1124 — implementation plan for review

Status: draft, no implementation approval. Prerequisite: [phase-one spec](../spec/2026-09-09-OME-1124-analytics-spec.md). Base inspected: 0dc1b845. This plan follows the spec and does not authorize new tickets or code. OME-1124 coordinates SDK delivery; OME-1060 owns shared decisions. Keep OME-1128 website implementation separate.

## 1. Resolve design and split ownership

Apply the owner-confirmed session, activity, outcome and retention definitions. Benchmark/provider/cost/cache-hit and discovery/review events are deferred. Consent-only bridge requests are already approved by the owner; do not ask again. Assign analytics service deployment/retention ownership and select a test PostHog project. No production keys in notebooks or SDK.

Implementation order approved in conversation; each unit touches one layer:

| Unit | Landing and deliverable | Depends on |
|---|---|---|
| OME-1152 ingestion/PostHog service | apps/analytics only plus registration; no bridge yet | Docs PR approved/merged; analytics label already registered |
| SDK local foundation/events | packages/screamingface; consent, local IDs, sessions, evaluation/submission events | OME-1152 |
| Service Colab bridge | apps/analytics; consent/ID endpoints and revocation | Separate approved service contract |
| SDK Colab adapter | packages/screamingface; bounded notebook integration | Service bridge |

Scoreboard database aggregates, website instrumentation and identity linking are deferred, not prerequisites for this slice. Client submission-success events provide the observed funnel. The [service contract](../spec/2026-09-09-OME-1152-analytics-service-spec.md) governs initial wire schema and delivery semantics; future discovery/review events require an additive contract review.

Never implement apps/analytics inside the SDK issue as an untracked second landing. Shared schemas can be a versioned HTTP contract; do not introduce a new shared package until needed. Engine internals and public website are not changed by this plan. A new service requires CODEOWNERS, toolchain/lockfile, CI, release lane, dependabot entry and deployment registration per repository routing rules.

## 2. SDK foundation (after OME-1152) — meaningful TDD slices

Invoke sdlc-python before any Python code. Use a worktree per approved implementation unit from current origin/main; recheck source drift. Preserve existing tests and add behavior tests rather than assertions mirroring implementation.

1. Add core ports and a clock-injected session/consent coordinator with a null sink. Test import/constructor/configure with blocked networking: no analytics file, ID or request. Test process sharing, async task isolation, worker context propagation, no rotation after idle periods or long active operations, including kernels spanning reporting windows, Client replacement and fork reset.
2. Add explicit origin=colab/local_jupyter/python/cli and usage_mode=byok/hosted. Verify valid combinations, missing/invalid metadata and rejected unknown/mixed values. Missing metadata drops events with a local debug diagnostic and never blocks evaluation. Never serialize endpoint hosts or run network probes for analytics.
3. Add persistent per-user configuration adapter and proposed analytics controls. Test two processes racing first enable, malformed/unwritable state, atomic persistence, restrictive permissions, stable IDs beyond 90 days, no scheduled consent re-prompt, storage loss, material consent-version changes, reset and disable visibility. Temp homes/config paths only. Neither virtualenv nor runtime --data-dir should accidentally become identity scope.
4. Test consent precedence: process disable/DO_NOT_TRACK, saved decline, accepted version, stale consent, explicit session-only acceptance. No retroactive event capture. Interactive choice must not wait in evaluate; headless defaults off. CLI administration alone never qualifies as WAS.

Primary existing seams/tests: client.py, _default_client.py, _environment.py, _runtime/config.py, _runtime/cli.py; tests/test_client_configuration.py, test_default_client_local_discovery.py, test_runtime_cli.py. Proposed new _analytics core/adapters remain shallow at the wiring boundary, not direct core imports of PostHog or Colab.

## 3. Hosted bridge and ingestion

The ingestion-only subset is OME-1152 and comes first. The consent/bridge work below is a separate later service-only unit, after SDK local analytics. Verify the bridge contract before notebook integration:

- Consent-only page/state requests receive no analytics-ID cookie, issue no ID and produce no PostHog events. Include existing-ID-but-unknown/stale-consent tests, not just a clean browser.
- Explicit enable stores consent first; identity endpoint checks it and returns a server-set partitioned ID. Decline is a low-cardinality consent value, never a unique denied-user marker. Cookie path, attributes, headers and no-store behavior checked by integration tests.
- Cross-origin nonce/source/schema checks, ancestor CSP, stale-response invalidation and no arbitrary redirect/URL commands. Validate against real Colab ancestry. Path/HttpOnly JSON-return variation needs fresh tests; earlier HTTPBin tests are evidence, not acceptance of this new protocol.
- Revocation: two active notebooks; disable in one while another has queued/in-flight work. Service rejects stale capabilities, local queues stop, and a later notebook reads decline. Test expiry and lost browser storage honestly. Define bounded propagation and already-accepted-event semantics in disclosure.
- Strict event schema, request limits, duplicate delivery, rate limits, PostHog outage and retention expiry. Service IDs/capabilities never authorize product access. No raw bodies/cookies/IPs in routine logs. Scan test capture output for forbidden fields.

Use an isolated test destination and recorded synthetic fixtures. No live synthetic data in production PostHog.

## 4. SDK integration and operation inventory

First prove real Colab evaluation nonblocking while bridge initialization stalls or fails. An output.eval_js timeout alone is insufficient: test kernel scheduling, thread support, pending task bound, late completion after disable and both sync/async evaluations. If that cannot pass, retain analytics-off Colab fallback and don't promise seamless measurement.

Then instrument a single outer boundary for Recipe/raw-URL4 evaluations in Client/AsyncClient. Test validation error, returned ok report, returned non-ok report, observer reconciliation failure, KeyboardInterrupt/async cancellation, internal fan-out and authentication replay. Exactly one analytics operation and terminal event per invocation where execution can report one. Preserve returned objects and exception identity/behavior. No event serialization via report.to_dict or raw Event callbacks.

Instrument explicit submit calls using the inventory in the spec. Discovery/review events remain deferred. Cover module convenience wrappers without double emission. Critical regression: evaluation preflight calls models.get internally; it must not manufacture discovery engagement. HTML repr or widget rerender must not count review. Submission response replay uses existing product idempotency but distinct analytics attempt IDs; never export run_id or authors. Repeated submit API calls are attempts, not multiple accepted rows.

Validate memory queue limits, immutable operation identity, stable event_id across transport retry, full-queue dropping, per-dispatch consent checks, shutdown deadline and no durable spool. Do not reuse product-authenticated httpx clients for telemetry. New HTTP adapter has separate origin/configuration and credentials policy.

Regressions to preserve: tests/test_client_run.py, test_catalog_discovery.py, test_leaderboards.py, test_report.py, test_evaluation_progress_panel.py, test_example_notebooks.py. Notebook generator/checker must prove no IDs, choices, output, secret values or environment-specific content are committed.

## 5. Reporting and acceptance

In the test PostHog destination, prove:

- Two sessions with evaluation starts under one browser ID yield WAS=2 and active browsers=1.
- A second installation is a separate scope, not a second verified person or an automatic join.
- A returned non-ok report produces completed_with_failures, not succeeded; its start qualifies activity. A returned Report.ok=true produces succeeded.
- A session qualifies when its evaluation start is in the window, even without a returned report. Completion of an evaluation started outside the window does not itself qualify. A long-lived kernel keeps one session ID and counts once in each window containing starts.
- Failed-only, cancelled-only, dropped and session-only cases are shown accurately; no unknown terminal event fabricated.
- Anonymous capture has no person association, no identify/alias, no geographic or raw-request enrichment. Gateway retries preserve all PostHog dedup keys; duplicate events are eventually merged, not immediately unique.
- SDK submission-success events describe observed attempts and temporal funnel sequence, not new database rows or proven causal attribution. Authoritative database aggregate work is deferred.
- 90-day raw-event retention and deletion can be exercised; any longer-lived aggregates have no browser/installation/session IDs. Dashboard access is restricted.

Browser matrix on owned HTTPS origin: Chrome/Safari normal profiles, reload, full quit/relaunch, second notebook/new runtime, opt-out/re-enable, lost/stale consent, browser cookie expiry, blocked cookies, private mode and network outage. Record supported/degraded/unsupported outcomes; do not treat private-mode new IDs as persistence bugs. Multi-day retention needs elapsed real time and a consented scheduled follow-up, not a changed system clock claim. Local matrix: CLI+Jupyter same user, different config/user, fresh virtualenv, concurrent processes, readonly home and remote persistent/ephemeral per-user storage.

## 6. Gates and delivery

For SDK implementation run the screamingface card gates from repository root: `uv run .claude/scripts/run_gates.py screamingface` (ruff check/format, pyright, pytest >=95%, deterministic notebook check, build and distribution check). For Scoreboard run its card gates including portal Node tests when that unit changes it. New analytics service needs a registered gate stack before implementation completes. Re-read current cards at implementation time.

This documentation-only design receives path/reference checks and git diff --check; running the product suite would not validate an unimplemented design. Each implementation unit later needs its own work ledger, tests/gates, conventional commit with Refs, PR and green CI. Do not close OME-1124 when this design is complete; delivery acceptance remains unchecked.

First end-to-end milestone: explicit opt-in -> evaluation start and classified finish -> schema-validated test PostHog event -> second session recognises the same permitted ID -> opt-out blocks further events. Roll out local SDK first if Colab's nonblocking integration remains unresolved; do not add identity linking to solve continuity gaps.
