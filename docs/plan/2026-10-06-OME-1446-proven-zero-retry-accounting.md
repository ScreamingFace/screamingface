# Plan: OME-1446 — proven-zero OpenRouter retry accounting

Spec: `docs/spec/2026-10-06-OME-1446-proven-zero-retry-accounting.md`. Ledger:
`docs/work/2026-10-05-proven-zero-retry-accounting.md`. Stack: `aigateway` (`sdlc-python`).

## Approved implementation boundary

The owner authorized the narrow cost-only implementation on 2026-10-06. The first unit covers only a
native HTTP 429 with complete OpenRouter metadata proving non-BYOK and no billable pipeline stage.
Tokens remain unknown unless the provider reports them. An all-guaranteed-zero request remains
`partial`; the target guaranteed-zero rejection plus reported success becomes `complete`.

No status code, missing usage field or absent generation ID closes the predicate by itself.

## Steps

1. **Evidence:** retain the official Zero Completion Insurance, Errors, Router Metadata, Logs and
   Generation API references and freeze the minimum safe attempt context.
2. **RED — mapper/status:** add a standalone proven-zero test module covering valid proof, bare
   429/503, forwarded upstream ambiguity, auxiliary/BYOK uncertainty, malformed/conflicting evidence,
   positive billed failure evidence and proof-classifier failure.
3. **RED — route:** exercise native response capture through Gateway retry and finalization. Assert
   both attempts remain, indexes are correct, the success is the only reported subtotal, cost status
   is complete and token behavior matches D2.
4. **RED — contract:** add a standalone schema-valid release fixture. Do not modify the existing
   exact fixture-name/hash matrix or prior test bodies without explicit approval.
5. **GREEN — value/schema:** add the approved status to `DirectCostStatus`, exact-zero validation,
   constructor/factory and `usage_accounting.schema.json`.
6. **GREEN — provider evidence:** add a focused pure OpenRouter rejection classifier and compose it
   after measured normalization. Measured evidence wins; classifier failure preserves it.
7. **GREEN — context:** expose only the native status/bounded facts required by D0. Keep prompts,
   credentials, collector and arbitrary headers outside provider code.
8. **GREEN — renderer:** count reported plus proven-zero statuses for coverage; continue grouping only
   reported amounts; require at least one reported subtotal for `complete`.
9. **Documentation:** update `apps/aigateway/docs/usage-accounting.md` with status semantics,
   provenance and independent token behavior.
10. **Composition:** feed the serialized envelope through existing Engine accounting without changing
    Engine. Verify OME-1463's Candidate/run-cost boundary with existing tests.
11. **Gates:** from repository root, run
    `uv run .claude/scripts/run_gates.py aigateway --base origin/main`.
12. **Validation:** run a separately authorized smoke that actually encounters the covered rejection.

## Implementation record

- Step 4 landed as additive schema-valid and schema-negative regressions in the focused accounting
  modules rather than a separate named release fixture; the existing fixture/hash matrix was not
  changed.
- Step 10 required no Engine production change. Existing request-economics behavior remains the
  boundary: only `direct_cost_status=complete` is priced, and `provider_guaranteed_zero` never creates
  a subtotal. The focused renderer/schema tests exercise the serialized envelope; 56 existing Engine
  accounting/run-cost boundary tests pass without tracked Engine changes.
- The 2026-10-07 independent review changed the evidence step: optional response pipeline metadata is
  no longer treated as proof of absence. The trusted finalizer derives one prompt-free boolean from
  the prepared request before handing only scalar request fields to provider mappers.

## Stop conditions

- Runtime evidence is missing any required non-BYOK/auxiliary-free/error fact.
- The implementation would claim token zero.
- A second app/package requires tracked changes but no landing sub-issue exists.
- An existing test must change without owner approval.
- A second status or consumer interpretation is needed for all-zero requests.

## Expected production files

- `apps/aigateway/src/aigateway/plugins/taxonomy/types.py`
- `apps/aigateway/src/aigateway/plugins/taxonomy/usage_accounting.schema.json`
- `apps/aigateway/src/aigateway/plugins/taxonomy/render.py`
- `apps/aigateway/src/aigateway/plugins/taxonomy/session.py` or a focused context module
- `apps/aigateway/src/aigateway/plugins/taxonomy/collector.py`, only if required by D0
- `apps/aigateway/src/aigateway/plugins/openrouter_provider/rejection_accounting.py`
- `apps/aigateway/src/aigateway/plugins/openrouter_provider/usage_accounting.py`
- `apps/aigateway/docs/usage-accounting.md`
- additive test modules under `apps/aigateway/tests/unit/usage_accounting/`

No Engine production file is planned.
