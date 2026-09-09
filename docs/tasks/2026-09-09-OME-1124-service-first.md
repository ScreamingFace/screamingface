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
* Implement the approved session lifecycle with a distinct `session_id`. Keep persistent browser/installation identifiers separate. Include explicitly supplied origin and local/hosted execution mode.
* Add telemetry consent and controls in the normal user configuration, outside notebook contents and shared working files. Default to no; noninteractive behavior must follow the approved contract.
* Implement consented persistent continuity: a ScreamingFace-hosted server-set partitioned-cookie bridge for Colab, and a random ID in persistent per-user configuration for local SDK/CLI/Jupyter. Inspect actual configuration paths and storage scope; do not store IDs in shared notebooks. Specify expiry, reset, opt-out and deletion behavior. No identity-linking prompt, email association or account linking in phase one.
* Emit top-level evaluation start and terminal outcome (`succeeded`, `failed`, `cancelled`) with coarse duration. Deduplicate logical attempts across internal retries/reconnects; do not count Engine fan-out as separate evaluations.
* Deliver allowlisted events through the proposed `apps/analytics` gateway to the shared PostHog destination. Validate the schema and keep execution logs and error reporting separate.
* Configure session, activation, evaluation-health, workflow-adoption, conversion, returning-browser/installation and identifier-coverage reporting against the parent contract.
* Record SDK submission start/terminal responses for the observed funnel. Scoreboard database aggregates are deferred and are not a prerequisite for this slice.
* Publish telemetry disclosure and controls; schedule the proposed usefulness review after roughly 90 days when implementation is ready.

## Reliability boundary

A successful Engine run only counts after the Client receives and reconciles it into a completed user-facing report. If the Client disappears first, it may not report completion or failure. Document the resulting undercount; do not equate Engine success with completed Client use.

## Acceptance criteria

- [ ] Approved spec maps actual APIs, session boundaries, persistent identifier scope and storage, and the public operation event inventory.
- [ ] No analytics ID is created or analytics event sent before opt-in; decline, disable, remembered consent, identifier reset and opt-out behave as specified. Owner approved consent-only bridge requests on 9 September; they may retrieve remembered consent but must not enter analytics reporting. Explicit disable controls suppress the bridge request as well.
- [ ] WAS counts distinct active sessions; weekly active browser/installation metrics deduplicate sessions using the corresponding persistent ID. Neither metric is labelled as unique people or identified WAU.
- [ ] Local/hosted execution and Colab/local/unknown origin are independent reporting dimensions.
- [ ] Sync/async paths produce equivalent product events; internal retries and Engine runs do not inflate counts.
- [ ] Payload validation, delivery behavior, disclosure, retention enforcement, and deletion handling satisfy the parent contract.
- [ ] Dashboards distinguish observed sessions, browsers/installations, submission totals, and coverage limitations.
- [ ] Relevant tests and repository quality gates pass before delivery.

## Boundaries and next step

Phase one confirmed 9 September 2026: analytics opt-in/opt-out and anonymous continuity only. Verified-account linking and identified WAU are deferred; no identity-linking prompt. The parent records Chrome/Safari feasibility tests, not a production implementation. Combined cookie/consent, production reliability, private mode, longer retention and local persistence require validation.

Public website instrumentation belongs to `OME-1128`. Shared data/identity decisions, including the open benchmark/provider/cost/cache-hit request, remain in `OME-1060`.

Next: inspect code and prepare the spec and plan. Review any further implementation issue split before creating tickets. Creating `apps/analytics` requires the corresponding landing label and repository registration. Implementation requires explicit approval.

## Design review — 9 September 2026

Code inspected at `0dc1b845`; draft artifacts on branch `OME-1124-analytics-design`:

* `docs/spec/2026-09-09-OME-1124-analytics-spec.md`
* `docs/plan/2026-09-09-OME-1124-analytics-plan.md`

The spec maps sync/async Recipe/raw-URL4 evaluation, public discovery and submission, local configuration, current runtime CLI and notebook integration. It includes the approved consent-only bridge exception, proposed cookie-path separation, session/identifier lifecycle, event allowlist, bounded failure, PostHog mapping and a test matrix. The plan proposes separate implementation units per landing; no additional issues created.

Remaining design review: session/retention defaults, completed report versus Report.ok qualification, optional property request, service ownership and implementation split. Production Colab nonblocking initialization and cross-notebook revocation require validation; HTTPBin feasibility is not production acceptance. This issue remains In Progress for design; no product code or implementation approval.

Design artifacts saved in local commit `4fa35df2` on `OME-1124-analytics-design`. Existing-source reference checks and staged whitespace checks passed. Documentation only; no product tests, PR, deployment or implementation. Review the spec/plan before approving implementation.
