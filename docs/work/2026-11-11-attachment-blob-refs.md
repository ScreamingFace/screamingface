---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-11
finished:
---

# attachment-blob-refs — spec: attachments by blob reference, engine to gateway

## Intent

Write the design spec for carrying url4 attachments from the engine to the gateway as blob
references instead of inline base64, so memory stops growing with the number of parallel model
calls and the per-run attachment cap can rise to about 20 MB. Spec only; no code in this unit.
Evidence: the 2026-11-11 research doc "Attachment memory cost: proof and storage options"
(https://claude.ai/artifact/USXsTTKz3VuEdjpGoyZr6k).

## Planned changes

- `docs/spec/2026-11-11-attachment-blob-refs.md` (new)
- this ledger, and the `docs/tasks/` mirror at PR-open

## Test plan

- None: a spec. Its acceptance criteria name the tests the implementation units write.

## Acceptance

- Owner approves the spec in plain words.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
