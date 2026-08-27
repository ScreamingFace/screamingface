# OME-1013 — Local Client diagnostic receipts (spec)

Status: approved by the owner on 2026-08-26 after the Client diagnostics design session; notebook
presentation amendment approved on 2026-08-26.

Related: `OME-1003` (Client-side reporting epic), `OME-967` (Client trace creation and retention),
`OME-1002` (report-intake service), `OME-1004` (settled intake wire contract), and `OME-1014`
(report-card/send adapter).

## Outcome

When a public Client Evaluation raises or is interrupted by its user, ScreamingFace leaves the
ordinary Python exception behavior intact and stages one bounded, privacy-safe diagnostic receipt
in memory. A user can inspect or explicitly export that receipt without sending data or writing a
file automatically.

This is a local domain artifact, not the report-intake wire envelope. A later adapter may project a
receipt into the service contract once the service decides whether one submission represents one
top-level operation or one candidate failure.

The settled intake envelope carries one `correlation` and one candidate context, while this local
artifact intentionally retains every candidate execution in one failed top-level Evaluation.
Choosing the relevant execution or producing multiple wire envelopes is therefore an `OME-1014`
adapter decision; the Client does not discard evidence early to imitate the narrower wire shape.

## Identity model

The identities describe different scopes and are never substituted for one another:

```text
Client/kernel session                     session_id
└─ one failed public operation            diagnostic_id
   ├─ candidate URL4 execution            run_id + trace_id, when observable
   │  └─ relevant failed Gateway request  gateway_call_id, when observable
   └─ candidate URL4 execution            run_id + trace_id, when observable
```

- Every real failed or interrupted top-level operation receives a new `diagnostic_id`.
- Receipts are not fingerprint-deduplicated. Two failures are two facts even when their shapes
  match.
- `session_id` groups receipts produced by one Client/kernel lifetime. It is not an OpenTelemetry
  trace and grants no authority.
- A `trace_id` represents one bounded URL4 execution tree. One notebook session is never one
  long-lived trace.
- One Evaluation may contain multiple candidate execution records. Each may have its own trace.
- `run_id` is the existing public execution id carried by `Event`/`CandidateResult` and sourced
  from the CloudEvent subject. Retain it when observed, but do not confuse it with a trace, a
  notebook session, an authorization credential, or an idempotency key.
- A `gateway_call_id` identifies only the relevant concrete Gateway request when that fact is
  already observable. The diagnostic does not enumerate every Gateway call; the execution trace
  is the retrieval key for the tree.
- Until `OME-967` lands, missing trace evidence remains absent. `OME-1013` never fabricates it.

## Public local API

```python
receipt = sf.diagnostics.last()
receipt = sf.diagnostics.get("diag_...")

receipt.to_dict()
receipt.to_json()
receipt.export("screamingface-diagnostic.json")
```

- Lookup returns an immutable `DiagnosticReceipt` or `None` when no matching in-memory receipt
  exists.
- `to_dict()` returns a fresh JSON-compatible tree; mutating it cannot alter the receipt.
- `to_json()` is deterministic UTF-8 JSON with the same compact encoding as `Report.to_json()`.
- `.export()` follows `Report.export()`: `.json` only, creates parent directories, replaces the
  selected file, and returns its `Path`.
- Preview bytes and exported bytes are identical.
- Export is the immediate recovery action, not a secondary convenience. Because the ring dies with
  the process, terminal guidance names the exact export command on every retained receipt and the
  notebook panel makes Export its primary local action.
- No public count or byte-limit tuning is introduced in v1. The store's limits are private and
  test-pinned so capacity can be tuned without a compatibility promise.

## Capture boundary

Capture happens once per private Evaluation mode. Recipe evaluation owns one boundary in the
runner, shared by `sf.evaluate()`, `Client.evaluate()`, and `AsyncClient.evaluate()`. Direct URL4
replay owns one equivalent boundary because it bypasses Recipe preparation and enters through a
separate private workflow. Public facades never add parallel wrappers. Together the two boundaries
cover input validation, Benchmark loading, model discovery, preflight, compilation, execution, and
final Report decoding.

The capture context gains facts monotonically as the workflow advances:

1. public operation and caller-supplied Benchmark/candidate inputs;
2. compiled candidate identity and recipe topology;
3. validated effective model configuration after preflight;
4. bounded lifecycle evidence and execution identities while events arrive;
5. structured terminal error or interruption state.

If the workflow returns a `Report`, including a partial Report with benchmark Case failures, no
diagnostic error receipt is created. The Report and its existing failure presentation remain the
authoritative result.

## Allow-listed receipt content

### Client and environment

- ScreamingFace distribution version;
- Python implementation and version;
- OS family and machine architecture;
- host kind detectable by the kernel: notebook or CLI;
- Engine mode and host only, never path, query, fragment or credentials;
- the installed versions of exactly `httpx`, `websockets`, `pydantic`, and `ipywidgets` when
  present. Missing optional packages remain absent.

Browser user agent and frontend name/version are absent until an explicit widget communication
channel supplies them. Kernel-side guessing is forbidden.

### Error

- exception type and safe structured fields already exposed by `ScreamingFaceError`: code,
  status, retryability/permanence, hint, and safe typed details;
- structured WebSocket close information from the cause when already modeled;
- a sanitized exception chain;
- structured traceback frames containing package/module, function and line number only.

No raw traceback string, source line, frame local, or absolute filesystem path enters the normal
receipt. For an unknown exception, the type and sanitized frames are retained; arbitrary exception
attributes and messages are not serialized automatically.

`ScreamingFaceError.code` is best-effort in v1. Many existing raise sites use only their class
default (`planning_failed`, `execution_failed`, and peers), so code is useful evidence but not a
complete grouping vocabulary. OME-1013 does not invent a second code catalogue. Intake-side
triage must combine it with error type, structured fields and correlation ids.

Plain `TypeError`, `ValueError`, and other non-ScreamingFace exceptions still create a degraded
receipt at the same public-operation boundary. Their receipt contains type, sanitized exception
chain/frames and available operation context, but no fabricated code, hint, retryability or raw
message.

### Reproduction context

- Benchmark id and revision when known;
- candidate name/kind and recipe topology;
- exact **validated effective** supported model parameters used for execution;
- for a preflight rejection, rejected parameter name, model and reason, but not the unvalidated
  value;
- bounded safe lifecycle breadcrumbs such as stage transitions, event kind, relative operation
  name and outcome.

Breadcrumbs never include Event log bodies, payloads, URL4, prompts or responses.

## Interruption

- `KeyboardInterrupt` during an active Evaluation stages a receipt with outcome
  `interrupted_by_user`, then re-raises the same interrupt.
- `asyncio.CancelledError` during an active asynchronous Evaluation stages a receipt with outcome
  `cancelled`, then re-raises the same cancellation. The Client does not claim whether the caller,
  notebook, timeout or parent task initiated it.
- The receipt states only observable facts: elapsed time, last safe lifecycle event, and known
  candidate states. It never labels the operation as hung.
- `SystemExit` and `GeneratorExit` bypass diagnostic capture and retain ordinary Python behavior.

## Privacy and consent

The normal receipt never contains:

- prompts, model responses, rubric/check material, notebook cell source or file attachments;
- canonical URL4, Event log bodies, arbitrary exception attributes, or raw server payloads;
- environment variables wholesale, access tokens, API keys, secrets, credential files, or
  `~/.screamingface/*`;
- full Engine/Scoreboard URLs or query strings;
- source lines, frame locals or absolute filesystem paths.

An exact canonical URL4 may be offered later as a **separate**, explicit, content-bearing local
reproduction attachment. It is neither part of this receipt nor accepted by the v1 intake service.
It is requested only when a responder cannot diagnose from the safe receipt, and the user must
preview and approve it separately; it is never a default attachment.

No identity is inferred from a Cloudflare token. A future optional `reply_to` field is
self-asserted contact information, never authorization.

## Storage and failure behavior

- Receipts live in a process-local ring bounded by both count and serialized bytes.
- Kernel/process exit discards the ring. This is an accepted privacy trade-off: a user who restarts
  before explicitly exporting cannot recover that receipt.
- Eviction removes the oldest receipt first and is deterministic.
- A receipt larger than the entire byte budget is declined without evicting every usable receipt.
- Nothing is persisted or sent before explicit user action.
- Diagnostic capture is fail-open. Any internal capture/store/presentation failure is logged with
  no payload and the original operation exception remains the one raised.
- The original exception object and its cause chain are never replaced, wrapped or suppressed.

## Presentation boundary

`OME-1013` supplies receipt values, lookup/export and a local SFDS notebook panel. HTTP submission,
intake shaping and the final Report action remain `OME-1014`.

After a receipt has been retained, the Evaluation boundary may attach IPython's per-exception
`_render_traceback_` protocol to that exact exception object. It never registers
`InteractiveShell.set_custom_exc`, never handles unrelated notebook failures and never replaces the
exception. IPython terminals retain concise text. In an ipykernel, the renderer delegates to a
private notebook adapter that:

- leaves IPython's native exception summary as the sole local error evidence and adds only the
  diagnostic id and accepted in-memory lifetime as a neutral receipt toolbar;
- exposes Preview and Export as explicit actions;
- keeps receipt JSON hidden until Preview is selected;
- writes only after Export is selected;
- tells the user `%tb` remains available for the original traceback;
- renders with SFDS v2's app register in both light and dark hosts; and
- returns to the pre-existing traceback renderer if imports, widget construction or display fail.

The renderer is attached only after the store accepts the receipt. An oversized or otherwise
declined receipt cannot advertise actions against an id that lookup will not resolve.

In a terminal, the failure guidance may name the diagnostic reference and the exact export call:

```python
sf.diagnostics.get("diag_...").export("screamingface-diagnostic.json")
```

The normal exception remains available through `%tb` in notebooks and remains the ordinary raised
exception everywhere. A diagnostic panel is additive presentation, not a replacement error
contract.

## Non-goals

- Sending a report, retrying a submission, or authenticating to report intake.
- Persisted blanket consent. A future send requires an explicit click after previewing that exact
  report, every time.
- A manual "snapshot now" action for a suspicious but non-raising active operation. That requires
  an active-operation registry and is a separate capability; completed suspicious results already
  have `Report.export()`.
- Freezing the `screamingface.error-report/v1` service envelope.
- SigNoz/Linear persistence or trace retrieval.
- A browser-global exception hook or collection outside ScreamingFace public operations.
- Capturing successful Evaluations or partial Report failures as error diagnostics.
- Inferring a hang, replaying an execution, or proving reproduction from metadata alone.

## Acceptance

1. Sync and async Evaluation failures stage one distinct receipt and re-raise the original object.
2. A user-interrupted Evaluation stages an honest interruption receipt and re-raises
   `KeyboardInterrupt`; asynchronous cancellation stages `cancelled` and re-raises
   `asyncio.CancelledError`; `SystemExit` and `GeneratorExit` stage nothing.
3. A returned partial `Report` stages nothing.
4. Receipt serialization is deterministic, versioned and byte-identical to explicit export.
5. The store evicts deterministically under both count and byte pressure.
6. Candidate execution identities remain separate; missing traces stay absent.
7. Validated execution configuration is present when preflight completed; rejected values are not.
8. Tests prove every forbidden content/secret source is absent from a representative receipt.
9. A capture/store failure cannot change the operation exception observed by the caller.
10. No network request or automatic filesystem write is possible from this unit.
11. A retained notebook failure renders one accessible SFDS panel without a global exception hook;
    Preview and Export require explicit actions and renderer failure restores ordinary traceback
    presentation.
