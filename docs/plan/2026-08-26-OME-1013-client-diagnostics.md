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
- `_evaluation/runner.py` is the single integration boundary shared by default, explicit sync and
  async Clients. Public facades do not each grow their own exception wrapper.
- Future `OME-1014` maps the receipt into presentation and intake adapters without changing
  Evaluation execution.

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
  validated effective model configuration, bounded safe breadcrumbs, public run ids and optional
  trace evidence.
- GREEN: one observer-compatible context that can see lifecycle events without consuming or
  changing user/progress callbacks.
- Do not mint traces here; retain only evidence made available by `OME-967` or existing events.

### 4 · workflow boundary and interruption

- RED first: failures at validation, loading, preflight, transport and Report decoding each create
  one receipt while preserving exception identity/cause.
- RED first: interruption and async-cancellation capture/re-raise; `SystemExit`/`GeneratorExit`
  bypass; partial Report success path creates nothing.
- GREEN: one fail-open sync wrapper and one parity-equivalent async wrapper inside the Evaluation
  runner.

### 5 · minimal local handoff

- RED first: terminal guidance names the reference/export API without replacing the exception.
- GREEN: minimal Python representation only. Full SFDS notebook card and send actions stay in
  `OME-1014`.
- Run the full `screamingface` gate lane and the mandatory wisdom/confidence review.

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
- **UI scope creep:** only local values/export here; report-card interaction remains blocked behind
  `OME-1014`.
