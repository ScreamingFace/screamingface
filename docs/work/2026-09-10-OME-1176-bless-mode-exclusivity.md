---
ticket: OME-1176
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-09-10
finished:
---

# OME-1176 — Bless-mode exclusivity, two-way golden field policing, and deduplication

## Intent

Close the post-merge review findings on PR #870 (the OME-1098 goldens). Two bugs and
a cleanup batch in the bless tool + golden schema:

1. `--refresh-golden --dump-fresh` silently drops `--dump-fresh` (boolean flags dodge
   the `is not None` exclusion guard) — the one silent path in a tool whose whole job
   is refusing loudly.
2. Golden field policing is one-directional: loop fields refuse on other kinds, but
   `recipe`/`synthesizer` ride a loop golden as silently dead fields.
3. Duplication: `_loop_candidate` mirrors `build_candidate`'s loop branch; the
   BLESS-REFUSED status-drift block and the report→`_ReplayEvidence` construction are
   copy-pasted (2× and 3×).
4. Minor: `FreshReportFacts.revision` parsed but never read; `_loop_candidate`
   docstring missing (moot once deduplicated).

## Planned changes

- `packages/screamingface/tests/e2e/fixtures/slice_snapshot.py` — explicit refusal for
  the boolean mode-flag pair in `_run_gated_bless`; share the loop-candidate
  construction with `harness.goldens`; extract the status-drift refusal and the
  evidence construction into single helpers; drop the dead `revision` field.
- `packages/screamingface/tests/e2e/harness/goldens.py` — mirrored `elif` refusing
  fusion-only fields on a corrective_loop golden (and keep the existing direction).
- `packages/screamingface/tests/e2e/test_fresh_dump_contracts.py` — RED tests for both
  bugs (carried over from the review session) + adjustments for the dropped field.

## Test plan

- RED (already failing on this branch): the flag pair raises a named SystemExit; a
  loop golden with `recipe` or `synthesizer` refuses validation.
- Existing 17 fresh-dump contract tests + full suite stay green (refactors are
  behavior-preserving; the four committed goldens still load).

## Acceptance

- No silent mode combination remains; field policing is symmetric; each formerly
  duplicated block has exactly one home.
- Gates: `uv run .claude/scripts/run_gates.py screamingface` all green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `packages/screamingface/tests/e2e/fixtures/slice_snapshot.py` — explicit
    `--refresh-golden`+`--dump-fresh` refusal in `_run_gated_bless`; `_loop_candidate`
    deleted in favour of `harness.goldens.loop_candidate`; `_refuse_status_drift` +
    `_evidence` extracted (2× and 3× copies folded); dead `FreshReportFacts.revision`
    dropped.
  - `packages/screamingface/tests/e2e/harness/goldens.py` — mirrored refusal
    (`recipe`/`synthesizer` on a corrective_loop golden) + `loop_candidate` (the ONE
    spec→CorrectiveLoop builder, used by `build_candidate` and the fresh-dump bless).
  - `packages/screamingface/tests/e2e/test_fresh_dump_contracts.py` — 2 new tests
    (flag-pair refusal; fusion-fields-on-loop refusal).
- **Commits:** single commit on `OME-1176-bless-mode-exclusivity`.
- **Gates:** `run_gates.py screamingface --skip-append-only` ALL GREEN (96 e2e
  contract tests incl. the 2 new; full suite; cov ≥95). Append-only skip disclosed:
  harness/tool files extended, no test function changed.
- **Deviations:** `FreshReportFacts.revision` dropped rather than cross-checked — a
  revision mismatch already fails the expression rung (the revision is embedded in
  the rendered url4 path), so a second check would be a restatement.
