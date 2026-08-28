---
ticket: OME-1032
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-08-28
finished: 2026-08-28
---

# OME-1032 — Decode retained per-operation accounting in the Client

## Intent

The Engine (OME-1030, PR #762) now emits `accounting` on Candidate `CaseOperation`
and grading `Evidence` — unconditionally, `null` when empty. The Client's strict
decoder rejects the unknown field, so every evaluation against that Engine fails
and PR #762's golden-replay lane is red. This unit teaches the Client to decode
the retained value and round-trip it through the public API and Report JSON —
nothing more. Computed views, `MemberResult.usage` and the completed-Report table
stay in the parent OME-1031.

Landing shape: branch is cut from `OME-901-runtime-accounting-lineage`; its PR
targets that branch, NOT `main`. Engine and Client must land atomically — each
side alone turns CI red in the mirror-image way (unsupported field vs missing
field), and the e2e harness boots the Engine from the same checkout so there is
no version skew.

## Planned changes

- Review follow-up: make the wire decoder enforce the Engine's canonical
  fixed-point `cost_usd` grammar and replace every production `type: ignore`
  with typed boundary validation. Extract the accounting decoder/value seam so
  this feature does not materially deepen the Client's already-large result
  modules.

- `packages/screamingface/src/screamingface/case_result.py`
  - new `OperationCache` value (hits/misses/bypasses/unknown; ≥1 response).
  - new `OperationAccounting` value (provider, request_model, response_model,
    usage, provider_latency_ms, cache) reusing the SDK's existing
    `_report_primitives.Usage` — the six fields match the Engine's
    `OperationUsage` exactly, so no second usage type is introduced.
  - `CaseOperation` gains `accounting: OperationAccounting | None`; `to_dict`
    emits it unconditionally (required-nullable, mirroring the Engine).
  - `Evidence` gains the same field + `to_dict` emission.
- `packages/screamingface/src/screamingface/_evaluation/results.py`
  - `_case_operation` / `_evidence`: `accounting` becomes a REQUIRED key; new
    `_operation_accounting` decoder (strict: unknown fields refuse, negative
    values refuse, blank identity refuses, cost must be fixed-point text).
- `packages/screamingface/src/screamingface/__init__.py` — export the two new
  public values.
- Tests: new `packages/screamingface/tests/test_operation_accounting_decode.py`.

## Test plan

RED first:
- a Case Operation / Evidence carrying full accounting decodes into the typed
  value, cost as `Decimal`, and `to_dict` round-trips byte-equal.
- `accounting: null` decodes to `None` (the common case — deterministic
  evidence, unattributable operations).
- a MISSING `accounting` key refuses loudly (`is missing 'accounting'`) — the
  required-nullable contract, and the reason this must land with the Engine.
- strictness: unknown sub-field, negative tokens, negative `provider_latency_ms`,
  blank provider text, exponent/leading-zero/non-string `cost_usd`, and an
  all-zero `cache` each refuse
  with a named error rather than a silent null or a false zero.
- the invariant the parent spec names: absence stays absence — a null accounting
  never becomes a zeroed value.

## Acceptance

- New tests green; every prior Client test green and unmodified.
- Gates: `run_gates.py screamingface` all green.
- Combined with the Engine branch, both goldens (`draco-3pass`,
  `healthbench-worst30`) replay green with NO re-blessing — #762 touches no
  revision-pinning file, so the expression must not have moved.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus two not foreseen:
  - `src/screamingface/operation_accounting.py` — focused `OperationCache` +
    `OperationAccounting` public values, extracted during review so the feature
    does not materially grow the already-large Case Result module.
  - `src/screamingface/case_result.py` — `accounting` on `CaseOperation` and
    `Evidence` (+ `to_dict`);
    `_validated_evidence_parts` extracted so `Evidence.__init__` stays under the
    complexity gate (rules unchanged, only relocated).
  - `src/screamingface/_evaluation/operation_accounting.py` — focused strict
    wire decoder; canonical fixed-point cost and typed integer/cache boundaries.
  - `src/screamingface/_evaluation/results.py` — `accounting` required on both
    owners and delegated to the focused decoder.
  - `src/screamingface/report.py`, `src/screamingface/__init__.py` — exports.
  - `tests/test_operation_accounting_decode.py` (new, 29 tests after review
    hardening, including exponent/leading-zero/leading-plus/Decimal cost refusal).
  - NOT planned: `tests/public_surface_snapshot.json` regenerated deliberately
    (`UPDATE_SURFACE_SNAPSHOT=1`) for the two new public values.
  - NOT planned: prior-test payload fixtures updated (see Deviations).
- **Commits:** see git log on `OME-1032-decode-operation-accounting`.
- **Gates:** `run_gates.py screamingface --skip-append-only` → ALL GATES GREEN.
  Ruff check, Ruff format, Pyright, full Client suite with coverage ≥95%,
  deterministic notebook check, wheel build, and distribution check all passed.
  Docker e2e lane on the COMBINED tree
  (engine branch + this): **64 passed, 4 skipped, 0 failures** — the
  `draco-3pass` golden replay that is red on PR #762 is green here, with no
  re-blessing, confirming the expression did not move.
- **Deviations:**
  1. **26 prior tests hand-authored the old wire shape** and failed once
     `accounting` became required. Their payload dicts gained
     `"accounting": None`; three `to_dict()` expectations gained the same key
     because the serialized shape now always carries it. No assertion's meaning
     was changed or weakened — this is the sanctioned consequence of the
     owner-approved contract evolution ("pre-release v1 evolves directly, no
     compatibility fallback", spec §0). Two rows of
     `test_a_malformed_operation_entry_fails_closed` needed the key added so
     they still exercise the defect they name rather than tripping on the new
     one first.
  2. Append-only gate run with `--skip-append-only` for the same reason.
  3. `Evidence.__init__` exceeded the complexity gate after one added branch;
     validation extracted to a module-level helper rather than weakening the gate.
  4. The e2e lane needs `SCREAMINGFACE_E2E_ASSETS` and a regenerated
     `synthetic.manifest.json` (gitignored, per worktree) — environment, not code.
  5. The touched `case_result.py` and `_evaluation/results.py` remain above the
     current 450-line target because they already exceeded it before this unit
     (585 and 547 lines respectively). Review extraction removed this feature's
     material growth: accounting now lives in focused 97- and 129-line modules;
     the remaining pre-existing split is deliberately not bundled into this wire
     contract fix.
