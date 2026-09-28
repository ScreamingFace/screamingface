---
ticket: OME-934
stack: screamingface-engine
status: in_progress
started: 2026-09-09
finished:
---

# OME-934 — Review the generic Log seam before implementation

## Intent

Land a focused docs-only design PR before a separate implementation PR. The user authorized this split. OME-934 remains open until the generic infrastructure is delivered; merging these documents is not feature completion.

## Planned changes

- docs/spec/2026-09-09-OME-934-log-seam.md
- docs/plan/2026-09-09-OME-934-log-seam.md
- docs/tasks/2026-09-09-OME-934-log-seam.md
- This ledger.

## Test plan

Compare against the current Linear contract and origin/main executor/bridge/composition code; check document links, whitespace and scope. Run repository hooks and applicable CI. No Python changes or paid tests.

## Acceptance

Generic node-scoped URL4 Log emission, Engine forwarding and targeted safe buffering, with explicit lifecycle/expiry/validation/failure contracts and paired pressure regression requirements. Concrete model-activity schemas and evaluation lifecycle/tracking remain separately owned designs. Reviewable independently of implementation and OME-1153.

## Outcome

- **Actual files:** Four planned Markdown files; no production/test/config changes.
- **Commits:** This docs-only commit, docs(engine): specify the generic run Log seam; Refs: OME-934.
- **Gates:** Four-document whitespace/conflict-marker/local-link validation passed; scope checked against live Linear and current executor. Repository hooks and PR CI run at publish. No Engine gates required for a docs-only diff.
- **Deviations:** None. New worktree from origin/main ad0c965d; no commits imported from closed PRs 689/692.

## URL4 alternative investigation

User requested checking a generic URL4 Log extension before committing to the Engine-only design. PR 876 is draft and must remain draft. Evaluate in scratch only; no production implementation or cross-package ticket creation is authorized by this investigation. Compare node-scoped emission, structured attributes, Engine forwarding, lifecycle/expiry, observer failure semantics and what remains for run-scoped setup.

Scratch probe passed: structured attributes survived actual Engine execution, concurrent runs used distinct node spans, caller mutation did not change queued values, invalid/off-thread submissions were rejected, and existing Log eviction recognized the additive event. Context reset and inactive-sink behavior were exercised. Full cancellation/nesting/publisher/failure tests remain outstanding. Updated the draft with comparison and recommendation; no production changes. The prior Engine-only proposal is explicitly not settled.

## Recommended spec refresh

User authorized pushing the revised spec to the existing draft. Replaced the competing Engine-only implementation narrative with the recommended generic URL4 Log extension, explicit lifecycle/validation/failure rules, Engine forwarding and Client follow-ups. Added design-repository alignment with the limitation that Part D is not yet substantive. Rewrote the implementation plan around separate package/Engine issues, which remain unallocated pending approval. No code, ticket scope or readiness changes.

## Five focused review revisions

Applied the owner-approved clarifications: exact replacement scope for PRs 689/692; optional-Log admission/eviction at both capacity limits with paired lifecycle regression; explicit node/child/nested/expired-accessor semantics; OME-932’s evaluation lifecycle and canonical scoring obligations; and enumerated severity, immutable attributes and production size/rate requirements. Updated plan and removed the stale factory acceptance. This revision remains documentation-only; tests described here are implementation requirements, not claimed passing production tests.

## Design approval and issue allocation

Owner explicitly approved the revised design on 2026-09-09. Recorded approval in spec/plan, created OME-1165 for generic URL4 emission under OME-887 and made it block OME-934. Replaced OME-934's obsolete factory contract with Engine forwarding and targeted safe buffering; corrected the parent's stale package exclusion. Added package and parent task mirrors. Implementation follows the docs merge, URL4 first, in separate worktrees and draft PRs. PR 876 remains draft and unmerged; no production code is included.
