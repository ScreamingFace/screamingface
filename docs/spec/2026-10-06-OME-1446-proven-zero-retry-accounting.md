# OME-1446 — Proven-zero OpenRouter retry accounting

## Problem

When AIGateway observes a retryable OpenRouter rejection without usage, the attempt's cost and token
counts are unknown. A later retry may succeed with complete provider-authored usage and cost, but the
unknown first attempt correctly prevents the call from being published as fully priced. In the
2026-10-01 paid smoke, three retried calls caused two boards to show unknown cost.

The current behavior is honest. The missing capability is a truthful way to say that an identifiable
rejection contributed a proven zero charge without pretending that the zero came from the response's
`usage.cost` or that no tokens were processed.

## Invariants

- A total is complete or unknown; no attempt is silently omitted.
- Unknown is distinct from zero.
- Failed attempts may carry billed usage and cost.
- Cost and token processing are independently evidenced.
- `reported` direct cost is provider-authored response money for this attempt.
- Another provenance is represented by another status. `archive_matched` is the existing precedent.
- Engine consumes complete request economics and never reconstructs cost from attempt records.
- Provider-specific interpretation stays in the provider plugin; generic observation stays neutral.

## Decisions

### D0 — Documentation-backed native 429 predicate

A bare status code, missing `usage`, missing generation ID or blank output is insufficient proof of a
whole-request zero. The first implementation covers only a native OpenRouter HTTP 429 when all of the
following are observed on that attempt:

- complete bounded JSON capture contains an error and no generated output;
- `error.code` is the integer `429` and `error.metadata.error_type` is
  `rate_limit_exceeded`;
- opted-in `openrouter_metadata.is_byok` is exactly `false`, and any present
  `usage.is_byok` agrees;
- the prepared request contains no OpenRouter plugin, OpenRouter server tool or file part;
- `openrouter_metadata.pipeline` is explicitly present, contains no `plugin`, `server_tools` or
  unknown stage type, and any present `cost_usd` is exact zero;
- output-token evidence is absent or exact zero, and any present router attempt chain contains only
  integer 429 statuses;
- provider-authored `server_tool_use_details`, legacy server-tool usage and cost details contain no
  contradictory auxiliary work or charge;
- the response metadata is complete enough to apply those checks without inference.

OpenRouter's Zero Completion Insurance guarantees zero OpenRouter-credit inference charge for a
no-output error even when an upstream provider processed the prompt. Because error router metadata is
optional and may be truncated, the predicate combines explicit provider metadata with one
gateway-owned boolean derived from the prepared request. It therefore proves cost only for the narrow
non-BYOK, auxiliary-free case. It does not prove zero token processing.

HTTP 503, HTTP-200 embedded errors, absent/incomplete router metadata, BYOK and any billable or unknown
pipeline stage stay unknown in this iteration. `X-Generation-Id` is retained only if the observer can
do so safely; asynchronous generation lookup is validation evidence, not mapper I/O.

### D1 — Dedicated zero-provenance status

Approved representation (owner, 2026-10-06): add a canonical direct-cost status named
`provider_guaranteed_zero`.

- It carries `amount="0"`, the covered unit and a bounded proof source.
- It is not `reported` and is excluded from `known_direct_cost_subtotals`.
- It counts as accounted coverage for request-level direct-cost completeness.
- A guaranteed-zero rejection followed by a reported success therefore renders `complete` with the
  success's single reported subtotal.
- Engine remains unchanged.

The schema and value object reject a nonzero amount for this status. Optional/truncatable extension
facts cannot be the sole proof behind the canonical status.

Representing the zero as `reported` under another source is rejected as the default: it launders
provenance, creates a second subtotal and requires cross-unit Engine policy.

An all-guaranteed-zero/no-reported request remains `partial`: the renderer declares complete direct
cost only when all attempts are covered and at least one reported subtotal exists. This preserves the
current consumer contract, where an empty subtotal list is not priced zero, while solving the target
rejection-plus-success retry.

### D2 — Cost-only recovery

Current OpenRouter documentation may support a zero inference charge without proving zero prompt
processing. Therefore a cost can become known while input/output/cache/reasoning token totals remain
unknown.

The owner approved starting the narrow fix on 2026-10-06. This iteration restores complete cost while
leaving token totals unknown unless provider-authored token values already exist. It never synthesizes
token zero from insurance or router attempt count. General token recovery remains outside this unit.

### D3 — Minimal trusted context

The provider classifier may receive only the minimal immutable attempt facts required by the approved
D0 predicate, such as native HTTP status and bounded raw provider evidence. It never receives
credentials, prompts, the mutable collector, transport objects or arbitrary headers. The bounded raw
provider object can contain an error message, but the predicate never interprets or exports that text.

Router metadata is accounting-only evidence. The raw observer sees it, but AIGateway removes it
before the provider-compatible response can reach a caller or the auth-independent request cache.

Before `safe_request_view` drops structured values, the trusted finalizer derives one boolean saying
whether the prepared request asked for a provider plugin, OpenRouter server tool or file part. Only
that boolean reaches the supplement; raw structured request values remain unavailable to mappers.

### D4 — AIGateway-only preferred landing

The preferred representation leaves one reported subtotal and needs no Engine or SDK change. If a
future decision requires changing another app/package, work stops until the cross-cutting epic and
landing sub-issues required by repository policy exist.

## Acceptance

- With an approved whole-charge-zero rejection and a reported successful retry, request cost is
  complete and Engine reports the success's real cost.
- Every attempt remains in the accounting record.
- Uncovered 429/503, upstream ambiguity, auxiliary/BYOK ambiguity, malformed evidence and incomplete
  capture remain unknown.
- Positive provider-reported failure usage/cost is preserved and included.
- Token totals remain unknown unless D2 receives stronger evidence.
- Cache, streaming, hidden resend, bounds and OME-1220 behavior do not change.
- A separately authorized smoke exercises the covered rejection class.

## Validation evidence

The predicate is based on current official Zero Completion Insurance, Errors and Debugging, Router
Metadata, Logs and Generation API documentation. A separately authorized smoke must confirm the real
wire response carries the required metadata. Absence of an Activity row, metadata object or generation
ID is not proof and cannot activate the predicate.

## Out of scope

- Changing Gateway retry count/backoff.
- Skipping failed attempts.
- Engine-side idempotency uncertainty from OME-1220.
- Retrospective repricing of the 2026-10-01 run without evidence applicable on that date.
- Authenticated provider lookups inside request normalization.
