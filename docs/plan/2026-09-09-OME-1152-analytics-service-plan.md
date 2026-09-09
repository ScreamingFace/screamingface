# OME-1152 — service-only implementation plan

Status: review proposal. Prerequisite: [service spec](../spec/2026-09-09-OME-1152-analytics-service-spec.md). This docs PR is reviewed and merged first; a separate implementation PR delivers the service. No SDK, Scoreboard, website or bridge changes in that implementation.

## Before code

1. Review the endpoint/schema and bounded forwarding contract with eventual duplicate semantics, applying the owner-confirmed measurement decisions. Select service owner, hostname/port, PostHog test destination and enforceable 90-day raw-event retention. No deployment values fabricated in this draft.
2. Completed: owner-created analytics label applied and registered in the task-board card. Design-session/agentic describes docs work, not autonomous implementation approval.
3. Start a fresh OME-1152 implementation worktree from updated origin/main after docs merge. Invoke sdlc-python and create a new implementation ledger. Do not carry unreviewed changes from the earlier SDK design branch.

## TDD slices within the service layer

### A. App skeleton and pure contract

Create apps/analytics/pyproject.toml, uv.lock, src/analytics_service/, tests/, app guardrails and README. Use FastAPI/Pydantic/httpx and uv/hatchling consistent with report-intake, but do not copy its ORM, authentication or report filing logic. Proposed modules: contract.py (pure schema), ingestion.py (core use case), ports.py (EventDelivery), adapters/posthog.py, settings.py, api.py and main.py (wiring). No core import of concrete adapters.

RED tests: four allowed event variants and every outcome, UUID/scope/time boundaries, strict unknown-field rejection, explicit origin and usage_mode with unknown/mixed/missing values rejected, consent false/missing, forbidden payloads, invalid version grammar, duplicate identical/conflicting events. Freeze time; parse the JSON fixture from the spec. GREEN implementation must not add fields beyond the reviewed allowlist.

### B. HTTP boundary and bounded delivery

Test JSON content type, body cap for both content-length and streamed chunks, compressed rejection, empty/oversized batches, health/readiness, disabled/draining behavior. Assert invalid inputs make zero upstream calls. Inject delivery port/fake clock into tests; never call PostHog from unit tests.

Test total 1.5-second budget across pool acquisition, connect/write/read and one possible retry; 429 Retry-After, 5xx, transport ambiguity, permanent 4xx, malformed/partial upstream response, caller cancellation, inflight exhaustion and process rate cap. Response means upstream HTTP acceptance only. No unbounded background tasks, durable queue or acknowledgement-before-forwarding. No raw upstream error text in response/logs.

### C. PostHog adapter

Map strict schema to /batch with configured project token and exact immutable uuid/event/time/distinct_id mapping. Explicitly disable person profiles and GeoIP, omit sent_at, identify/alias and raw client headers. Pin adapter contract to public docs. Mock-server tests assert serialized bytes, retry identity and no redirects; test malformed settings/secrets redaction. Payload always rebuilt from validated typed fields, not arbitrary input dictionaries.

No cross-request exactly-once test claim: verify eventual PostHog dedup key preservation and explain possible transient duplicates. Same-request duplicate count reflects unique forwarded events. Separate live smoke check uses a confirmed test project, synthetic IDs and known timestamp; inspect ingestion and eventual duplicate behavior. Do not use production keys or assume a successful HTTP response proves the event is queryable.

### D. Operational registration and delivery

Add service Dockerfile and Helm chart/deployment route, health probes, limits, drain behavior and secret references; choose port/host with owner. Add CODEOWNERS, dependabot uv entry, path-filtered analytics-tests.yml, release lane and .claude/sdlc.local.md stack registration. Chart defaults must not contain tokens or enable analytics accidentally. Check report-intake conventions and current CI scripts; do not import its app internals or alter its behavior.

Gates proposed for registered analytics stack: ruff check/format, pyright, pytest with coverage threshold agreed at review (propose 95% for new service), uv build and container startup check. Validate Helm render/lint and existing chart wiring checks when chart files land. Test production configuration fails safely without a destination and that test/development routing cannot enter production reporting.

Document operational counters, process-vs-cluster rate limits, retention enforcement, unsupported guarantees, anonymous input abuse limitations and shutdown. Public ingress protection/log-redaction/retention must be verified before enabling the endpoint publicly. No person identifiers in logs. Docs must explain 202/429/503/502 and client retry policy.

## Acceptance and follow-on

Implementation PR must reference OME-1152 without closing it from this docs PR. Green service gates, reviewed configuration/deployment plan and test-project smoke evidence precede release. Only after service contract/delivery is ready should OME-1124 implement local SDK consent/IDs/sessions and evaluation/submission events. Bridge and SDK Colab work are later layer-specific units. Scoreboard aggregates and identity linking remain deferred.

## Docs PR validation

Check JSON example parsing/required keys, local Markdown links, conflicting first-slice scope statements and git diff --check. No runtime gates are claimed for a docs-only PR. Existing SDK draft is included as context and aligned with the new sequence; first-slice wire/delivery semantics are authoritative in OME-1152.
