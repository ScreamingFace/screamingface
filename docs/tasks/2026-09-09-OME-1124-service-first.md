---
id: OME-1124
linear_url: https://linear.app/openmined/issue/OME-1124
status: In Progress
priority: High
labels: [repo, agentic, design-session]
created: 2026-09-04
closed:
---

# OME-1124 — analytics delivery

## Delivery order — confirmed 9 September 2026

Service-only ingestion/PostHog work is `OME-1152`, which blocks this issue. Review/merge its docs PR, then implement it in a separate PR. Next: SDK local consent/IDs/session/events; later service Colab bridge; then SDK Colab adapter. One layer per implementation unit. No Scoreboard aggregates, website instrumentation or identity linking in the first slice. The initial wire contract supports evaluation/submission events; broader discovery/review tracking requires a later additive contract review.

## Outcome

Instrument SDK/CLI use across local, hosted, and temporary notebook environments so the team can report weekly active sessions, evaluation funnels, weekly active browsers/installations and repeat usage under the shared contract in [OME-1060](<https://linear.app/openmined/issue/OME-1060>).

The Client is the software component that emits events. The reporting unit is a session. Shared metric definitions, consent, identity rules, property decisions, and the PostHog destination are owned by the parent.

## Implementation scope

* Inspect all relevant public sync and async Client operations and classify each as tracked directly, represented by a higher-level workflow, or untracked with a reason. Cover Discover, Compose, Evaluate, Review, and Submit.
* Implement the approved session lifecycle with a distinct `session_id`. Keep persistent browser/installation identifiers separate. Include explicit origin and BYOK/hosted usage_mode.
* Add telemetry consent and controls in the normal user configuration, outside notebook contents and shared working files. Default to no; noninteractive behavior must follow the approved contract.
* Implement consented persistent continuity: a ScreamingFace-hosted server-set partitioned-cookie bridge for Colab, and a random ID in persistent per-user configuration for local SDK/CLI/Jupyter. Inspect actual configuration paths and storage scope; do not store IDs in shared notebooks. Specify expiry, reset, opt-out and deletion behavior. No identity-linking prompt, email association or account linking in phase one.
* Emit top-level evaluation start and terminal outcome (`succeeded`, `completed_with_failures`, `failed`, `cancelled`) with coarse duration. Deduplicate logical attempts across internal retries/reconnects; do not count Engine fan-out as separate evaluations.
* Deliver allowlisted events through the proposed `apps/analytics` gateway to the shared PostHog destination. Validate the schema and keep execution logs and error reporting separate.
* Configure session, activation, evaluation-health, workflow-adoption, conversion, returning-browser/installation and identifier-coverage reporting against the parent contract.
* Record SDK submission start/terminal responses for the observed funnel. Scoreboard database aggregates are deferred and are not a prerequisite for this slice.
* Publish telemetry disclosure and controls; schedule the proposed usefulness review after roughly 90 days when implementation is ready.

## Reliability boundary

An observed evaluation start qualifies activity. Success is a separate terminal outcome requiring a returned reconciled Report with Report.ok=true. If the Client disappears first, completion/failure may be unobserved. Best-effort delivery can also lose starts; document this undercount.

## Acceptance criteria

- [ ] Approved spec maps actual APIs, session boundaries, persistent identifier scope and storage, and the public operation event inventory.
- [ ] No analytics ID is created or analytics event sent before opt-in; decline, disable, remembered consent, identifier reset and opt-out behave as specified. Owner approved consent-only bridge requests on 9 September; they may retrieve remembered consent but must not enter analytics reporting. Explicit disable controls suppress the bridge request as well.
- [ ] WAS counts distinct active sessions; weekly active browser/installation metrics deduplicate sessions using the corresponding persistent ID. Neither metric is labelled as unique people or identified WAU.
- [ ] Origin and usage_mode are supplied explicitly using the agreed enums; missing/invalid metadata drops the event without blocking product work.
- [ ] Sync/async paths produce equivalent product events; internal retries and Engine runs do not inflate counts.
- [ ] Payload validation, delivery behavior, disclosure, retention enforcement, and deletion handling satisfy the parent contract.
- [ ] Dashboards distinguish observed sessions, browsers/installations, submission totals, and coverage limitations.
- [ ] Relevant tests and repository quality gates pass before delivery.

## Boundaries and next step

Phase one confirmed 9 September 2026: analytics opt-in/opt-out and anonymous continuity only. Verified-account linking and identified WAU are deferred; no identity-linking prompt. The parent records Chrome/Safari feasibility tests, not a production implementation. Combined cookie/consent, production reliability, private mode, longer retention and local persistence require validation.

Public website instrumentation belongs to `OME-1128`. Shared data/identity decisions, including the deferred benchmark/provider/cost/cache-hit request, remain in `OME-1060`.

Next: review/merge the existing docs PR, then implement OME-1152 separately before SDK work. The analytics landing label is already registered; app registration belongs to the service implementation. Review further layer-specific issue splits before filing them.


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
