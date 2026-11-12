---
ticket: OME-893
stack: aigateway
status: in_progress
started: 2026-11-11
finished:
---

# Provider credit visibility

## Intent

Implement E5 P3 using the actual execution connection, with a prominent BYOK account
balance and separate key allowance. Product confirmed that hosted users execute with
limited OpenRouter keys: hosted allowance is that same key allowance, not a separate
ledger balance. Finish logic before the final UI pass, as the owner requested.

## Planned changes

- Gateway: provider credit adapter, caller-scoped reads, encrypted optional management keys.
- Engine: validated HTTP adapter, hosted key-only reads, no hosted wallet or credential writes.
- SDK: typed sync/async and default-client APIs; existing connection-card integration.
- Regression tests, local end-to-end check, hidden-input owner-key verification.
- Final UI layout and browser-visible refresh after logic verification.

## Test plan and acceptance

Spec: `docs/spec/2026-11-11-provider-credit.md`.
Tests cover caller isolation, execution credential selection, account association,
zero/unknown/stale values, partial failures, malformed responses, bounded retries,
cancellation, shutdown and secret handling. Run stack gates and inspect the final UI
at desktop/mobile sizes in light/dark. Live owner-key verification is a release check.

## Implemented

- Gateway → Engine → SDK credit path, with finite Decimal amounts and observation times.
- Optional management key is encrypted and bound to the caller and inference key.
  Account totals require matching provider-authored account identity. No paid calls.
- Hosted reads require caller identity and a stored execution key. They never read a
  management key or fetch account totals. `hosted` mirrors the key allowance; do not sum them.
- Five-minute cached reads, shared overlapping requests, 5/10/20/30-minute bounded
  failure backoff, explicit refresh bypass, per-caller cache invalidation.
- Independent partial results; transient failures retain same-credential values as
  stale. Rejected association clears old balances. Connection changes discard old results.
- Safe generic failures; cancellation isolation; owned tasks stop before storage closes.
- Hidden-input terminal verification helper, including refusal of visible-input fallback.
- Notebook card now separates account credit from the spending cap, hides optional
  management settings until opened, and shows hosted allowance once. Visibility-aware
  five-minute refresh uses the backend cache/backoff; manual refresh stays immediate.
- OpenRouter evaluations have a factual, nonblocking notice for a verified zero
  observed within five minutes. Stale/unknown/future readings and frozen replays skip it.

## Validation status

- Gateway full gates pass, including coverage >=80% and the hidden-input helper
  regression. Latest log: `/private/tmp/ome893-pr-gateway-gates.log`.
- SDK full gates pass after the owner-approved dependency allowlist update:
  lint, format, types, full pytest coverage >=95%, notebook checks, build, and
  distribution checks. Latest log: `/private/tmp/ome893-pr-sdk-gates.log`.
  Browser lifecycle test passes and is now included in the local gate and CI.
- 150 focused Engine credit/connection/selector tests pass. The existing 21 API
  documentation tests pass after declaring the Credits tag and error-envelope note.
- CI-aligned Engine core environment passes lint, format, types and layering.
  The full rerun with current Helm is recorded in the publication outcome below.
  Earlier optional Inspect environment had 14 type errors identical to baseline;
  all 12 failures in three Inspect test files also reproduced on original code.
- End-to-end real local HTTP check passed with simulated OpenRouter responses:
  BYOK totals, key limits, cache, hosted privacy, caller isolation, rejected key
  association, stale retention, and removal. Harness: `/private/tmp/ome893-smoke/`.
  Temporary loopback servers stopped afterward. No live keys or paid calls used.
- Live provider-adapter check passed with the owner's authorized local inference key:
  OpenRouter returned an available, finite remaining key allowance. Without a
  management key, the account total correctly remained unavailable with
  `management_key_required`. Only a read-only GET was made; no model calls or
  credential persistence. Credential values and personal balances are omitted here.
- Live personal API/management pair verification passed through the production
  provider adapter and credit service, with an ephemeral in-memory store: verified
  account total and key allowance, cache reuse without another provider lookup,
  caller isolation, hosted reads skipping management storage and account totals,
  and removal invalidating the cached account total while preserving key reads.
  Pairing the team API key with the personal management key was rejected before
  storage. All external requests were read-only; no model calls, persistent
  credential writes, or production connection changes were made. Live balances
  demonstrated that key allowance can exceed funded account credit; keep them separate.
- Final real Jupyter UI inspected at 1280px and 390px in light/dark and approved
  by the owner. Fixture screenshots are in `docs/spec/2026-11-11-provider-credit/ui/`.

## Outstanding

- Live inference-key, personal account-total, and account-association checks passed.
  Full SDK/Engine/Gateway HTTP integration was tested with simulated provider data;
  the live credential checks exercised the Gateway adapter and credit service.
- Full live SDK/Engine/Gateway end-to-end verification is deferred to dev by the owner.
- Publish the owner-authorized PR; deployment and merge are outside this iteration.

## Decision record

### Notebook and run-notice completion

Owner authorized the final UI/visible refresh and run-start zero notice; full live
HTTP integration is deferred to dev. This iteration is SDK-only. Use a small
anywidget browser bridge in the optional notebook extra for visibility, a five-minute
timer and cleanup; retain existing ipywidgets controls. Automatic reads use the
backend cache/backoff; explicit refresh remains immediate. Keep account credit
prominent, key spending allowance distinct, and avoid duplicate hosted budgets.
Refresh on authentication/connection changes and dispose browser resources on close.

At run registration, check the actual execution connection only for OpenRouter
candidates, excluding frozen replays. Emit a factual, nonblocking notice only for
an available zero observed within five minutes; unknown/stale/future readings and
lookup failures remain silent. Bound the best-effort request and never turn a warning
filter into an execution failure. Test sync/async paths, privacy and lifecycle before
the SDK gate. Inspect the actual card in desktop/mobile light/dark previews and
exercise the browser visibility/timer module with controlled time.

### Hosted allowance

Owner's limited-key confirmation supersedes the earlier deferred hosted ledger/timing
question. Hosted key allowance needs no management key. BYOK account totals remain
separate and require verified management credentials.

## SDK completion follow-up

Owner directed "ok, continue then" after the additive API checklist had been
explained. Applying that continuation to the necessary snapshot additions only,
using the repository's exact-blob approval manifest. A recursive comparison proves
every old API entry is unchanged; no existing assertion is weakened. Complete full
SDK gates and build checks. UI remains deferred. Asked for the local credential
source needed for the owner's read-only live verification; no secret requested in chat.

Local end-to-end smoke check passed across real SDK → Engine → Gateway HTTP
boundaries, with OpenRouter simulated at the provider adapter. Checked BYOK totals,
key allowance, cached reads, hosted account privacy, caller isolation, rejected key
association, stale retention, and management-key removal. Fixture servers bound only
to loopback and were stopped after the check. No live keys or paid calls were used.
Harness is in `/private/tmp/ome893-smoke/`.

SDK gate found two typing defects in the new widget test. Added a non-None assertion
and aligned a callback parameter name with the interface; behavior assertions remain
unchanged. The complete SDK gate rerun passed, including notebook checks, package
build, and distribution validation. Log: `/private/tmp/ome893-sdk-completion-gates.log`.

The owner's-key helper now refuses Python's visible-input fallback when hidden
terminal input is unavailable. Its existing safe-output test and a new fallback
regression test pass. Public result documentation now explicitly states that hosted
and key allowance describe the same budget on the platform and must not be summed.

## Notebook completion validation

Real Jupyter preview: http://127.0.0.1:8931/lab/tree/credits-final.ipynb (fixture data).
Inspected 1280px desktop and 390px mobile in both themes, with connected and
unconnected providers. The credit section has no horizontal overflow. Corrected
mobile provider-row wrapping and column labels; management controls are collapsed
by default and clear submitted input. Hosted layout shows one budget, and the
preview menu also provides absent-management, stale, and zero examples.

Browser-controlled time confirmed that a due five-minute timer reaches the Python
controller and updates the fixture count; another ten minutes with document hidden
makes no read. Reappearing cards refresh when due. The actual notebook exposed a
child-before-parent attachment timing issue; the bridge now waits for attachment
before observing the card. Node lifecycle tests cover that path, overlap, hidden
state, acknowledgements, and cleanup. No live credentials used in this UI pass.

The owner approved the prepared dependency change with the publication request.
The exact-blob manifest now covers anywidget in the notebook dependency allowlist,
plus the earlier additive API snapshot. No additional public API change is needed.

## PR publication verification

Owner reviewed the final notebook and requested publication: "looking good ot me,
let’s publish the PR". Applied the prepared optional anywidget dependency allowlist
addition and recorded its exact-blob approval. Gateway and SDK full gates pass.

The CI-aligned Engine core environment passes lint, format, types and layering.
The broad run exposed a missing Credits OpenAPI tag description (existing regression
test failed); add the same error-envelope note as other REST tags and rerun.
The remaining chart failures report local Helm's Kubernetes default version mismatch.
Wire the browser lifecycle test into the SDK gate and CI so future changes exercise it.

Delivery is tracked by OME-893 (Gateway), OME-1891 (Engine), and OME-1892 (SDK),
all under E5 / OME-1294. Full live HTTP verification remains deferred to dev.

## Publication outcome

Gateway, SDK, and Engine core full gates are green. Final Engine log:
`/private/tmp/ome893-pr-engine-final-gates.log`. The Credits OpenAPI description
fix passed the existing regression tests. Helm 4.3.1 was downloaded with its
checksum verified into `/private/tmp/ome893-helm` and used only for this gate run;
the installed Helm 4.0.0 was unchanged. This resolves the local chart-test
Kubernetes-version mismatch. Optional Inspect baseline failures remain separate
from the green CI-aligned core lane and are disclosed in the PR.

Wisdom review: reuse execution credential resolution, encrypted storage, and the
existing card; fail closed on account association; keep funded credit and spending
permission distinct; retain stale timestamps; keep all credit lookups nonblocking
for execution. Owner-approved dependency and snapshot changes are narrow and
recorded in the exact-blob manifest. No database migration is required.

The staged change contains no environment files, live keys, personal balances,
local notebook output, or virtual environments. The owner-approved publication
is a review PR, with merge/deployment and full live HTTP validation still pending.

## Review follow-up — 2026-11-12

Owner requested assessment and fixes for the local and GitHub reviews. Address the
replay fake's missing credit route without weakening refusal assertions, replace
provider-ID regex validation with explicit ASCII character checks, and resolve the
SHA-256 alert with its documented high-entropy-key/encrypted-storage justification.
Add a typed Engine credit port with independent injection, shared vocabulary
conformance tests, graceful absence of anywidget, and a total sync-notice wait bound.
Record Filip Boltuzic as the actual approver. Improve fragile serialized-string
assertions where the review identified them, preserving their behavioral intent.

Preserve documented explicit refresh and exact-zero notice semantics; the Engine
already translates upstream errors before decoding. Live personal key association
was verified; hosted keys' per-key limits were confirmed by the owner. No new
provider calls or production credential changes are needed.

Validation: targeted regressions fail first, then run all touched stack gates plus
the dedicated replay lane (which is separate from the SDK unit gate), and inspect
the fallback notebook card before updating PR #1753. Keep review tickets open.

### Review assessment and outcome

- Repaired the fake Gateway's credit metadata surface for taped providers, including
  hosted key-only reads. Untaped routes remain refused. Added end-to-end regressions
  for exactly one read and unchanged failure output when credit is zero or fails.
- CodeQL #23 dismissed as a false positive by FilipBolt: this is a provider-verified
  high-entropy API-key fingerprint inside encrypted storage, not password storage.
  Replaced provider-ID and credit-token regexes with explicit ASCII validation.
- Added an independently injectable Engine Credits protocol and separated wire
  models from the concrete HTTP adapter. Existing connection adapters still wire it.
- Shared exact state/reason vocabulary fixture is checked in all three components;
  changes to it trigger all three CI workflows.
- Missing anywidget preserves the connection card and manual refresh. Verified the
  actual Jupyter fallback at 1280px/390px in light/dark; no horizontal overflow.
- Sync notice waits at most one second for I/O. At most one daemon lookup can remain
  in flight per process; subsequent notices skip it and late results never warn.
  HTTP phase timeouts still apply to the underlying request.
- Approval metadata names Filip Boltuzic and records dates/scope. Replaced flagged
  substring assertions with parsed JSON/DOM comparisons under the review-fix request.

Retained decisions: explicit sf.credits() remains fresh by default (documented
product behavior); auto-refresh uses caching. Negative amounts remain visible, but
the notice remains exact-zero as agreed. Engine HTTP errors already pass through
raise_for_status before decoding. Provider identity was verified using the owner's
live keys, and hosted per-key limits were confirmed; neither needs weaker validation.

Focused validation: Gateway 60 passed; Engine 24 passed; SDK/replay metadata 49
passed and 2 full-stack cases skipped locally because Docker is unavailable.
SDK and Engine core full gates pass; the optional Inspect import-isolation failures
disappear after restoring the Engine's CI core dependencies. Gateway full gate and
post-rebase CI results are recorded at publication. No existing replay refusal
assertion changed. No new live key use, model calls, or deployment.
