---
ticket: OME-1205
stack: repo
status: done
started: 2026-09-15
finished: 2026-09-15
---

# OME-1205 — Make the engine execution-flow doc render as real diagrams and match the code

## Intent

The engine's execution-flow reference (`apps/screamingface-engine/docs/execution-flow-diagrams.md`)
draws its flows as hand-authored ASCII boxes: unreadable on GitHub, expensive to edit, and a
verify pass found four stale references. Convert the two flows and the call sequence to mermaid
(GitHub renders it natively, diffs as text) and fix the stale references in the same pass.

## Planned changes

- `apps/screamingface-engine/docs/execution-flow-diagrams.md` only:
  - §1 end-to-end flow → mermaid flowchart, three subgraphs (control plane / run mode / JetStream)
  - §2 run-mode flow → mermaid flowchart; call sequence → mermaid sequenceDiagram
  - §3 tables + §4 invariants stay prose
  - Fix: `testing/memory_stream.py` → `adapters/memory.py`; drop `_forwarded_credential` step
    (now `X-Profile`/`X-User-Email` + `rest/connections.py`); control plane uses
    `valid_traceparent` not `parse_traceparent`; §1 heading two→three modes.

## Test plan

- Docs-only: no code tests. Verify each mermaid block parses (mermaid-cli or GitHub preview)
  and every file/symbol the doc names exists in the tree (re-run the grep pass).

## Acceptance

- Doc renders on GitHub with mermaid diagrams; no ASCII flow boxes remain in §1/§2.
- All file paths and symbols named in the doc exist in the code (verified by grep).
- Rides the OME-1102 branch/PR (owner-approved in session).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `apps/screamingface-engine/docs/execution-flow-diagrams.md` (as planned)
- **Commits:** 6bc9145c — docs(screamingface-engine): render the execution-flow doc as mermaid and fix stale references; 8cb98102 — restore the SubscriberGate step lost in the conversion (found by the old-vs-new re-verify)
- **Gates:** docs-only; all 3 mermaid blocks validated with mmdc; every file/symbol the doc names re-verified by grep against the tree
- **Deviations:** §3's ASCII "file purpose" box folded into the run-mode table as a Layer column (it duplicated the table); added the missing `rest/connections.py` row
