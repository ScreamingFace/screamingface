---
id: OME-1060
linear_url: https://linear.app/openmined/issue/OME-1060
status: In Progress
priority: High
labels: [repo, agentic, design-session, decision]
created: 2026-09-01
closed:
---

# OME-1060 — analytics delivery

## Service-first delivery — confirmed 9 September 2026

First child implementation: `OME-1152`, apps/analytics ingestion and PostHog forwarding only. Docs-only PR reviewed/merged first, then separate implementation PR. SDK `OME-1124` depends on it. Later units alternate one layer at a time: SDK local analytics -> service Colab consent/cookie bridge -> SDK Colab adapter. Website instrumentation, identity linking and Scoreboard database aggregates are outside this first slice. SDK successful-submission events provide the initial observed funnel; they are not authoritative counts of new database rows.

## Phase one — confirmed 9 September 2026

Start with weekly active sessions (WAS), weekly active browsers/installations and repeat-usage analysis using consented pseudonymous IDs. Colab uses the server-set partitioned-cookie bridge; local SDK/CLI/Jupyter uses a persistent per-user configuration ID. Keep persistent IDs separate from session IDs. No identity-linking prompt, email association, verified-account linking or identified WAU implementation in this phase. Do not combine browser/installation counts into a unique-person total.

Remembered analytics opt-in and accessible opt-out are in scope; a one-time prompt is a UX target, not guaranteed after storage clearing/expiry. Owner approved on 9 September: consent-only bridge requests may retrieve remembered consent before analytics is enabled, with no analytics ID creation or analytics events. Explicit disable controls suppress bridge requests too. This is a narrow exception to the earlier unqualified no-request wording. Production implementation and the combined bridge protocol still require review and validation.

Current evidence: server-set cookies passed full browser restart and independent notebook/fresh runtime recovery in both Chrome and Safari. Tests used HTTPBin with a one-day expiry, not deployed ScreamingFace infrastructure. Local persistence, combined cookie/consent handling, multi-day retention and private mode remain untested. The experiment sections below are chronological history; earlier failures refer to different approaches.

## Purpose

Define the shared analytics strategy and measurement contract for ScreamingFace. Implementation is split between `OME-1124` (SDK/CLI session analytics) and `OME-1128` (public Scoreboard website analytics).

Analytics should answer whether researchers can complete an evaluation and submit unaided, whether they return, whether leaderboard activity encourages participation, and whether published results are reused.

## Confirmed measurement contract — 9 September 2026

- Activity is an observed evaluation_started event in the trailing seven-day UTC window. WAS counts distinct session IDs; weekly active browsers/installations count their available persistent IDs separately. Failed/cancelled attempts still qualify activity. These are not unique-person counts.
- One session per Python process/notebook kernel, shared across clients and wrappers; no idle rotation. Restart/fork creates a new session. Persistent IDs remain stable while consent is valid, with reset on opt-out, explicit reset or storage loss.
- Remember consent without a scheduled re-prompt; ask again only when purpose/data materially changes or the choice is lost. Consent-only Colab bridge reads are approved before consent is known, but create no analytics ID or events; explicit disable suppresses those reads too.
- Four initial events: evaluation_started/finished and submission_started/finished, with coarse duration on finish. Evaluation outcomes: succeeded only for a returned reconciled Report with Report.ok=true, completed_with_failures for Report.ok=false, failed for exceptions, cancelled for user cancellation. Submission outcomes: succeeded/failed/cancelled. Missing terminal events are not inferred.
- Explicit origin=colab/local_jupyter/python/cli and usage_mode=byok/hosted. No unknown or mixed values. Missing/invalid integration metadata drops the event with a local debug diagnostic; evaluation proceeds. The service rejects invalid payloads. No endpoint guessing.
- Best-effort background delivery, bounded retries, occasional loss accepted, no durable queue first phase. Analytics must never block evaluations.
- Raw events retained for 90 days. Longer-lived aggregates contain no browser/installation/session IDs; individual retention beyond 90 days is unavailable.
- Discovery/review events and benchmark/provider/cost/cache-hit fields are deferred. No identity linking, email prompts, website instrumentation or Scoreboard database aggregates in this first slice.

Authoritative docs review: [ScreamingFace analytics docs PR](https://github.com/ScreamingFace/screamingface/pull/871). Docs approval/merge precedes a separate service implementation PR; this update implements no product code.

## Consent and association

Telemetry is opt-in and off by default, with no analytics identifier creation or analytics events before consent. Owner-approved exception: the Colab bridge may make consent-only requests to retrieve remembered consent; those requests must not enter analytics reporting. Identity association is a separate optional choice and must not block normal use.

Future identity-association phase only: reuse identity verified during normal product authentication. Hosted connection and verified Scoreboard login/submission are candidate association points; inspect the actual flows before implementing. A supplied email alone is not proof. Do not initiate Google login solely for analytics.

Future identity-association phase only: use an opaque pseudonymous analytics identity; do not send raw email to PostHog. Logging out or switching accounts clears the active association. Turning association off stops future association; historical deletion is a separate disclosed support path. Specify backend behavior so these controls work in practice.

Respect telemetry-disable controls, including `DO_NOT_TRACK`. Declined consent is stored only as preference state (local file or future bridge consent cookie), never analytics, so a global telemetry opt-in rate cannot be inferred from received events.

## Shared reporting and data contract

Use one shared PostHog destination for SDK/CLI/app product events and public Scoreboard page views, benchmark drill-downs, and URL4-copy clicks. Distinct event names and surface properties keep the sources clear. Shared reporting does not automatically link website visitors to notebook users; linking identities remains separate and consented. Website activity alone does not qualify for identified WAU.

The Client owns user-facing product events; the Engine supplies execution facts. Proposed delivery is through `apps/analytics`, which validates allowlisted payloads, handles pseudonymous identifiers, and delivers to PostHog. Future app workflows reuse Client events, adding only UI-specific events.

The baseline contract includes session identity, persistent browser/installation identity, schema/consent versions, SDK version, surface, origin, usage_mode, sync/async interface, workflow, outcome, duration bucket, and timestamp. Exact names and properties belong in the reviewed spec.

Exclude prompts, outputs, credentials, URL4 expressions, model names, score values, raw email, execution run/trace IDs, exception text, stack traces, hostnames, dependency inventories, IP-derived location, and fingerprints. Keep analytics separate from `report-intake`. Development and automated-test events must not enter production reporting.

**Deferred properties:** Irina's benchmark/provider/cost/cache-hit request is preserved for later review; the owner confirmed excluding it from the first slice.

Raw-event retention is 90 days; verify enforcement before production. Provide access controls, disclosure, opt-out and historical-deletion handling.

## Reporting outcomes

* Weekly active sessions and weekly active browsers/installations, with identifier scope and coverage limits. Identified WAU is deferred.
* Activation and evaluation-to-submission funnels for observed opted-in activity.
* Evaluation outcomes and coarse duration.
* Workflow adoption and returning browser/installation activity.
* Website engagement and authoritative submission aggregates are separate later work.

Session telemetry cannot expose activity before opt-in or reliably report terminal failures after a hard Client crash. These limitations must be visible in metric definitions.

## Deferred

Verified-account identity association, identity-linking prompts and identified WAU are deferred beyond phase one. Login solely for analytics, silent cross-device identification, fingerprinting, analytics/error-report joins, researcher reputation and a person-level build-on-top graph remain out of scope. The consented browser-to-runtime cookie bridge is now in phase-one design scope.

## Acceptance criteria

- [ ] Review actual Client and submission flows, local configuration and Colab integration; document session boundaries and persistent identifier scope.
- [x] Owner confirmed session lifecycle, evaluation activity/success, identity/coverage definitions and reporting windows.
- [x] Owner confirmed initial events/properties, consent and persistent identifier behavior, retention and deferred properties.
- [ ] Validate retention enforcement and historical-deletion controls before production.
- [ ] Confirm the shared PostHog delivery/configuration ownership across the two child issues.
- [ ] Produce the spec and implementation plan, with explicit approval before coding.

This parent owns shared decisions. Child issues reference this contract and own their implementation scope; they do not duplicate the strategy.

## Experiment history

Chronological Chrome/Safari experiment evidence is preserved in Linear and summarized in the SDK spec. Production cookie/consent integration remains untested.
