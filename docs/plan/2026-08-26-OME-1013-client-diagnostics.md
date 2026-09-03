# OME-1013 — Local Client diagnostic receipts (plan)

Spec: `docs/spec/2026-08-26-OME-1013-client-diagnostics.md`

Implementation starts only after explicit approval of the linked spec.

## Design

Keep the public surface shallow and the implementation deep:

- `diagnostic.py` owns the immutable public `DiagnosticReceipt` value and deterministic
  serialization/export convention.
- `diagnostics.py` is the small public lookup facade behind `sf.diagnostics`.
- `_diagnostics/` owns allow-listed capture, bounded storage and mutable in-flight Evaluation
  context. It has no HTTP client and no report-intake dependency.
- `_evaluation/runner.py` owns the single Recipe integration boundary shared by default, explicit
  sync and async Clients; `_evaluation/url4.py` owns the equivalent boundary for direct URL4 replay,
  which bypasses Recipe preparation. Public facades do not each grow their own exception wrapper.
- `_evaluation/observers.py` owns the fail-open progress, callback and diagnostic event fan-out so
  both private Evaluation modes reuse one observer contract and the runner remains focused.
- `_ui/diagnostic_view.py` owns optional notebook presentation. Capture knows only that a retained
  receipt can be attached to its original exception; the adapter owns IPython and ipywidgets.
- Future `OME-1014` maps the receipt into the intake envelope and adds explicit send behavior
  without changing Evaluation execution.

## Batches

### 1 · receipt and bounded local store

- RED first: deterministic immutable value, schema validation and Report-shaped export behavior.
- RED first: `last()` / `get()`, unique refs, deterministic count/byte eviction, oversize decline.
- GREEN: public `diagnostic.py`, `diagnostics.py`, private store, and exports from `__init__.py`.

### 2 · privacy-safe capture primitives

- RED first: structured ScreamingFace and unknown-exception projection; sanitized exception-chain
  frames; allow-listed environment and host-only Engine identity.
- RED first: explicit negative assertions for tokens, URL4, prompt/response text, log bodies,
  source lines, locals, absolute paths and environment dumps.
- GREEN: private capture helpers returning immutable receipt inputs rather than serializing
  exception objects.

### 3 · Evaluation context and execution evidence

- RED first: one context per top-level sync/async Evaluation, multiple candidate execution slots,
  validated effective model configuration, bounded safe breadcrumbs and optional trace evidence;
  private stream topics never become public run ids.
- GREEN: one observer-compatible context that can see lifecycle events without consuming or
  changing user/progress callbacks.
- Before compilation, retain only caller candidate name/kind. After compilation, replace that
  fallback with the compiler-produced models and operation topology instead of recursively
  reconstructing every concrete Recipe subtype in diagnostics.
- Do not mint traces here; retain only evidence made available by `OME-967` or existing events.

### 4 · workflow boundary and interruption

- RED first: failures at validation, loading, preflight, transport and Report decoding each create
  one receipt while preserving exception identity/cause.
- RED first: interruption and async-cancellation capture/re-raise; `SystemExit`/`GeneratorExit`
  bypass; partial Report success path creates nothing.
- GREEN: one fail-open sync wrapper and one parity-equivalent async wrapper for each private
  Evaluation mode, with no wrappers at the public facades.

### 5 · minimal local handoff

- RED first: terminal guidance names the reference/export API without replacing the exception.
- GREEN: minimal Python representation and exact local export guidance.
- Run the full `screamingface` gate lane and the mandatory wisdom/confidence review.

### 6 · per-exception notebook panel

- RED first: retained typed and raw Evaluation failures attach one renderer to the original
  exception; unrelated exceptions and declined receipts remain untouched.
- RED first: Jupyter/Colab leaves the native exception summary as the only failure presentation and
  adds one accessible, transparent SFDS receipt footer with explicit View details/Save JSON actions.
- RED first: JSON, runtime-lifetime disclosure and `%tb` guidance are absent before View details;
  no file exists before Save JSON; save success/failure is reported locally; missing or broken
  notebook dependencies fall back to the prior renderer.
- RED first: the nested root does not use Colab-collapsing shrink-wrap, hidden rows reserve no
  vertical space, and a successful rich render does not repeat terminal-only export guidance.
- GREEN: a private `_ui` adapter lazily imports notebook dependencies and composes the existing
  exception renderer rather than installing `set_custom_exc`.
- Keep HTTP submission and browser fact collection in `OME-1014`.
- Run the full `screamingface` gate lane and the mandatory wisdom/confidence review.

### 7 · review hardening

- RED first: successful and repeated per-exception rendering returns the native traceback lines
  while displaying the local receipt toolbar once.
- RED first: internal Event stream topics are absent while valid trace ids remain observable.
- RED first: the receipt construction boundary is a typed evidence aggregate and rejects unsafe
  top-level error fields rather than accepting arbitrary mappings assembled by tests or callers.
- GREEN: preserve the native exception as the sole error presentation; keep the widget additive,
  use SFDS danger styling for export failures, and remove diagnostics-owned Recipe recursion.

## Risks and controls

- **Secret leakage through generic serialization:** no `vars(exc)`, exception pickling or
  environment dump; only named projectors with negative tests.
- **Changing exception semantics:** capture in a guarded side path and use a bare re-raise for the
  operation error; test object identity and causes.
- **Async/sync drift:** shared pure capture/store logic with thin parity wrappers and parametrized
  behavior tests.
- **Service-contract churn:** no intake types or HTTP dependency; the local receipt is projected by
  a later adapter.
- **Unbounded memory:** enforce count and encoded-byte budgets before insertion.
- **Notebook-global interception:** attach the IPython protocol only to exceptions with a retained
  receipt; never register a process-wide handler.
- **UI scope creep:** only local Preview/Export here; send, consent, intake authentication and
  browser fact collection remain blocked behind `OME-1014`.
