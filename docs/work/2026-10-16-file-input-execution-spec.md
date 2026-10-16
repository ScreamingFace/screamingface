---
ticket: OME-1535
stack: repo
status: in_progress
started: 2026-10-16
finished:
---

# file-input-execution-spec — the file-input execution spec for the engine and gateway

## Intent

Write the execution spec that the engine and gateway leaves of epic `OME-1529` build against:
per-layer findings re-verified on current `main`, the execution contract, the boundary with
`OME-1330` / `OME-1271`, the url4 contract (`OME-1534` C1–C9 as signed off) and the open items
with the 2026-10-16 live evidence. Docs only.

## Planned changes

- `docs/spec/2026-10-16-OME-1535-file-input-execution.md` (new)
- `docs/diagrams/file-input-path.svg` + `.png` (new)
- `docs/tasks/2026-10-16-OME-1535-file-input-execution-spec.md` (mirror)

## Test plan

- Every file:line cited re-checked against `origin/main` at `637594595` (40 citations, 37 unique; 0 wrong).
- url4 parse behaviour reproduced with `url4.core.grammar.parse`.
- Diagram rendered with `rsvg-convert` and inspected.

## Acceptance

- The spec is merged, and Kevin (url4) and Dmitry (gateway) have reviewed it.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see the branch (`docs(spec): draft the file-input execution spec`).
- **Gates:** docs only; no app gates apply.
- **Deviations:** rebased on `637594595` and updated for OME-1541 (#1431), the Ollama file-part
  refusal (OME-1641, #1447), the 2026-10-16 live provider results, the Gemini CLI deprecation (I-26) and
  the stale Codex catalog (OME-1634). Items marked UNVERIFIED in the spec were not re-run.
