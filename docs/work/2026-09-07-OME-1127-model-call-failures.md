---
ticket: OME-1127
stack: screamingface-engine
status: in_progress
started: 2026-09-07
finished:
---

# OME-1127 — Diagnose failed model-call classification

## Intent

Reproduce the reported permanent gateway-fault classification without paid model calls, then establish an evidence-backed fix proposal. User authorized continuing the reproduction matrix on 2026-09-07.

## Planned changes

- Task mirror and this ledger.
- Diagnostic reproduction in worktree-local `.docs/`.
- Spec and plan once response shapes and stage attribution are understood.

## Test plan

- Exercise real connector through loopback HTTP: truncated delivery, empty 200, malformed complete body, provider-error JSON, and unusable choice JSON.
- Assert interrupted delivery is retryable and malformed complete HTML remains permanent.
- Inspect COMMIT candidate versus grading attribution.

## Acceptance

- Reproducible classification matrix and explicit distinction between proven behavior and unconfirmed live causes.
- Concrete proposal preserving spend, scores, and existing provider errors.

## Outcome

- Investigation in progress. No production code changes yet.

### Investigation results

- Baseline a72960dd; isolated worktree OME-1127-model-call-failures.
- Diagnostic: `.docs/reproduce_1127.py`, run with `PYTHONPATH=apps/screamingface-engine/src:packages/url4/src /Users/kj/Documents/projects/sf/screamingface/apps/screamingface-engine/.venv/bin/python .docs/reproduce_1127.py` from the worktree root.
- Matrix: true incomplete delivery already retryable; empty complete 200 permanent; error JSON and null error completion reproduce exact issue wording. Expected RED: `BUG: empty 200 classified permanent`.
- Existing checks: 73 passed in 1.64s across test_aigateway_connector.py, test_finish_reason_capture.py, test_grading_error_integrity.py.
- Spec and plan created. Actual live payload not available, so no production policy was changed and no root cause claimed.
- MedXpert inspected read-only on origin/OME-1126-medxpert-mcq; absent from main. COMMIT stage requires deployed-revision reproduction.
- No commit or full gates: investigation artifacts only; implementation not yet performed.

### Scope update — 2026-09-09

User authorized updating OME-1127 after PR #846 merged. Revised Linear description distinguishes delivered work, corrected live-response diagnosis, and remaining acceptance. Original issue retained as explicitly superseded historical evidence. Status, assignee, priority, labels and relations preserved. Updated task mirror; no production changes or issue closure.

### Implementation start — 2026-09-09

User approved implementation. Worktree fast-forwarded to origin/main 0dc1b845. Spec/plan updated before code. Planned files: runner/connector.py plus new Engine integration test module(s). Test-first zero-byte response classification; real local HTTP tests cover final report behavior. No paid calls, no raw response capture, no SDK changes. Code aigateway_empty_response is retryable; automatic replay unchanged. Full Engine gates required before commit.

### Implementation outcome — 2026-09-09

- Completed the approved classification unit: 8-line guard in `runner/connector.py`; no added automatic replay, dependencies, logging, schemas, or Gateway/SDK edits.
- RED: 2 empty-response unit cases failed with `aigateway_bad_response`; 3 nonempty controls passed. GREEN: all 5 unit cases pass.
- Added 17 loopback HTTP integration cases through the real connector, candidate adapter, MedXpert protocol and validated CandidateResult. Both turns preserve candidate stage and source-error retryability for empty/partial disconnects, empty completed replies, HTML, complete reasoning-only outcomes and 429/503. Genuine checker exceptions remain grading failures; successful accuracy/coverage remain 1.0; the run's Usage observer retains $0.25 from completed reasoning after commit fails.
- Test development corrections: aggregate exposes the underlying code in `metadata.source_error` while retaining its existing `missing_case_row` wrapper; tests assert that public contract. Candidate requests deliberately suspend the grading request-accounting collector, so spend is asserted at the run Usage observer, the existing cost-reporting seam.
- Final `uv run .claude/scripts/run_gates.py screamingface-engine`: ALL GATES GREEN (append-only check, lint, format, pyright, layering, full pytest suite with 80% coverage threshold). Focused integration suite: 17 passed. Existing tests unchanged.
- Wisdom/confidence review: smallest behavior change at the JSON boundary; zero-byte evidence does not establish an outage or interception; complete nonempty malformed content stays permanent. Tests use actual incomplete HTTP framing rather than simulated exceptions. No prompt/body logging or secrets. No public schema or dependency changes; new error code is the explicit approved policy. Confidence ≥95% for this scoped fix.
- Deviation: Engine-owned fake-Gateway tests exercise the final report directly; no cross-package SDK harness change required. This verifies accounting already emitted, not comprehensive failure-path evidence retention (OME-784).
- OME-1127 stays In Progress pending logging-ownership and diagnostic-evidence decisions. This PR references the issue and does not auto-close it. Prepared commit: `fix(engine): classify empty model responses as retryable` (`Refs: OME-1127`).

### Acceptance ownership reconciliation — 2026-09-09

User requested resolving the remaining review gaps. Read current OME-1127/784 and existing observability issues. Engine connector logs completion/failure and heartbeats but lacks the Gateway's gateway_call_id pairing. Gateway taxonomy session logs dispatch only. Existing OME-938 owns call correlation, OME-1120 owns trace joining, OME-968 owns terminal failure records. Preserve that requirement rather than declaring Engine logs equivalent. Plan: record two narrowly scoped children under OME-784 (Engine response diagnostics; Gateway successful completion/duration), reuse existing failure/correlation tickets, and keep OME-1127 open with explicit dependencies. Child issues are design preparation, not approval of a wire schema or implementation. Keelan remains coordination owner through OME-1127; new children inherit that owner. No implementation or merge in this reconciliation unit.

Reconciliation outcome: created OME-1153 (Engine) and OME-1154 (Gateway) under OME-784, assigned to Keelan, Backlog/design-session. Linked existing correlation/failure tickets, added blocked-by relations, and updated both parent issue descriptions without deleting prior scope or posting discussion comments. Added task mirrors. Verified CI for reviewed commit 97694f21 is successful; PR remains open/draft. Documentation-only follow-up; diff whitespace check passed, no runtime/test change or new gate run needed.
