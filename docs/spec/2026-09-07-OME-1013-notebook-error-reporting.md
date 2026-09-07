# OME-1013 — Notebook error reporting

Status: owner-directed consolidation, 2026-09-07. This supersedes the split between local
receipts in OME-1013 and notebook sending in OME-1014, including conflicting public-interface
requirements in the 2026-08-26 OME-1013 spec on PR #756. Implementation is not yet complete.

## Outcome and ownership

An evaluation error keeps its original Python exception and gains a compact Copy/Report
interaction. Users need no diagnostic-management interface. OME-1013 owns the complete Client
flow; OME-1014 closes as superseded, with its requirements carried here. OME-1003 remains the
parent. OME-416 owns only Client/notebook version provenance. The existing report-intake service,
operational tracing and opt-in product analytics remain separate work.

## Interaction

- Keep the original error presentation. Add one compact row: **Copy diagnostics** and
  **Report issue**. No full diagnostic panel opens automatically.
- Copy is a local action. Use a supported frontend mechanism; if clipboard access is unavailable,
  reveal selectable text with honest copy guidance rather than a dead button.
- Report expands inline with an optional note, optional reply address for follow-up, a clear
  anonymous/account-associated submission label, a collapsed exact-payload preview, Send and
  Cancel. Opening the form never submits it or automatically writes a file.
- Changes to the note, reply address or browser facts update the payload preview. Send freezes
  that payload; previews/copy/save of a prepared submission use those same bytes.
- Disable repeat submission while sending. Retrying the same logical submission reuses its
  idempotency key and payload. Authentication tokens are headers, never preview content.
- Render **Report received: <ref>** when accepted. Show a ticket link only if the response
  actually carries one. A pending delivery is not a failure to receive the report.
- On failure, retain the draft and offer Retry, Copy and explicit Save. No automatic write.
- A missing widget manager or reopened notebook must have a useful static fallback (selectable
  sanitized diagnostics and an explicit save/download action where supported). Do not publish
  inline event handlers or fake working controls. Never serialize credentials into notebook
  output. A stored preview is allowed only after the user explicitly reveals/copies it.
- Use SFDS's app register: neutral compact layout, blue interactions, square edges, Plex Sans
  controls and Mono diagnostic values. Keyboard focus, accessible labels/status changes, light
  and dark themes, and no focus stealing are acceptance criteria.

## Private diagnostic capture

Keep the allowlisted capture policy from PR #756: error type and safe structured fields,
sanitized stack frames, version/environment facts, Engine host, benchmark/candidate identity,
compiled topology, validated effective parameters and bounded lifecycle evidence when observable.
Prompts, responses, cell source, raw traceback text, locals, paths, credentials, full URLs,
URL4 expressions and internal stream topics are excluded. A freeform user note is explicit input
and is previewed; do not silently add other content sources to it.

Attach a bounded immutable snapshot privately to the relevant exception/view. Retain separate
candidate execution identities without copying the internal topic as run_id. Capture available
client-minted trace IDs from transport failures before frames, as well as observable events.
Do not retain an extra traceback/frame graph for reporting.

No public `sf.diagnostics`, `DiagnosticReceipt`, `last()`, `get()`, or `sf.report(ref)` is required.
Remove the process-global receipt registry unless an observed lifecycle requirement establishes
a need; a view can own its snapshot. Private serialization and explicit UI save remain useful.
Bound both each snapshot and retained view state; dispose widgets/callbacks on teardown. Removing
the ring must not silently replace it with unbounded retained widget snapshots.

Capture remains fail-open and preserves the original exception/cause chain. Diagnostic failures
must not log that original chain, sensitive values, or source lines. KeyboardInterrupt and async
cancellation retain their original semantics. SystemExit and GeneratorExit bypass capture.
Successful and partial returned Reports do not create error cards; OME-1072's proposed change to
raising behavior is outside this work. Do not install a global notebook exception hook.

## Service contract and routing

The development endpoints supplied by the owner are:

- Anonymous: `https://reports.dev.screamingface.ai/v1/reports`.
- Internal: `https://reports-internal.dev.screamingface.ai/v1/reports`.

Both accept the same `screamingface.error-report/v1` JSON contract. Development endpoint values
must not become unconditional production defaults. The notebook kernel submits via HTTP; do not
put a report or credential into a URL, HTML form, browser fetch or notebook-saved token state.

Use the internal route when a usable report-service Access credential is available. An Engine
login flag or browser session alone is insufficient: the current Access token store shares tokens
only across matching audiences. Resolve the report audience and reuse only credentials valid
for it, without triggering a login just to submit a report. Otherwise prepare anonymous submission
with a fresh browser-produced Turnstile response in `CF-Turnstile-Response`. Show the selected
identity mode before Send. If it changes after a failed attempt, require another explicit Send;
do not silently resubmit under a different identity. Never forward internal credentials to the
anonymous hostname or across redirects.

Private projection is mandatory: PR #756's `screamingface.diagnostic/v1` document is not the intake
document. The service requires `occurred_at`, `client`, and `error.type`/`error.message`; it has one
primary candidate and one nullable correlation. It forbids unknown top-level fields. Carry a
known failing candidate/trace into that primary context; never pick an arbitrary candidate from a
multi-candidate operation. Any additional safe execution context must fit the existing extensible
context, depth/size limits and classifier. Required error.message must come from reviewed safe
error facts, with a non-content fallback for arbitrary exceptions; do not serialize str(exc)
wholesale merely to satisfy a required field. Pin this choice in projection contract tests.

The total body limit is 64 KiB. The backend bounds fields, rejects content, and stores only accepted
reports. Client preview/send equality refers to outgoing bytes; the backend may truncate accepted
fields according to its documented caps. No service schema changes are assumed by this ticket.

## Backend behavior

POST authenticates/admit-checks the caller, checks content type and JSON/schema/size, applies
content classification, persists and deduplicates, renders safe ticket content, then attempts
delivery. Persistence precedes delivery. A new accepted submission returns 202 and a server-minted
ref; an idempotent replay returns 200 and the original record without a new delivery attempt.

QueueSink is the code default: the report table itself is the queue, and an operator/agent later
files it. The stored state `queued` is returned as delivery.state `pending`, ticket null. If the
deployment selects LinearSink, successful delivery supplies a ticket; retryable failures remain
pending for the worker, and permanent failures become failed. Verify the actual dev configuration
rather than inferring the sink from its hostname or the existence of LinearSink code.

Missing/rejected Turnstile is 403; rate limiting is 429; invalid schema/content is 422; oversized
body is 413; pre-persistence storage failure or unevaluable bot gate is 503. An Access challenge
must be handled as authentication, not parsed as a JSON success. After an ambiguous timeout,
reuse the original submission key and bytes; do not assume nothing was stored.

## Verification required before calling the flow complete

1. Deterministic Client tests cover capture/privacy, sync/async and multi-candidate failure
   attribution, before-frame trace IDs, original exception preservation, capture logging, exact
   projection/preview/send bytes, bounds, copy/save fallback, and one submission per click.
2. Route-selection tests cover matching/mismatched/expired/missing Access credentials, anonymous
   token acquisition, no credential leakage and no silent identity change. Never stub a token
   as valid in the deployed acceptance test.
3. Service contract tests cover authentication, schema, classification, persistence, idempotency,
   queue/Linear success and delivery failure/retry without changing deployed service settings.
4. In a real supported notebook, test the full UI in light/dark, keyboard-only, missing-widget
   and reopened-output cases. Verify frontend support for clipboard and Turnstile token transfer;
   a Python callback test cannot establish either.
5. Submit one clearly labelled synthetic test report through each dev route using a real fresh
   Turnstile token and real report-service Access authentication respectively. Confirm 202/ref,
   persisted rows, anonymous caller_email absent versus internal verified caller_email present,
   and the actual configured delivery outcome. Never put a user's failure content into smoke data.
6. Replay each payload with the same idempotency key (and fresh Turnstile token where needed):
   expect 200, the same ref, one row and no additional immediate ticket delivery. Exercise bad
   schema/content and rejected authentication safely; simulate outages in isolated tests.
7. Use operator queue/DB inspection to verify persistence/delivery. There is no GET-by-ref API;
   do not add one merely for tests. For LinearSink, verify the linked test ticket. For QueueSink,
   verify queued content and distinguish that from completed Linear filing.

Observed on 2026-09-07: public GET returned 405; empty unauthenticated public POST returned 403
and explicitly said nothing was stored; internal unauthenticated GET/POST redirected to Access.
These establish admission behavior only. Successful live submissions, persistence, sink
configuration and delivery are not yet verified.
