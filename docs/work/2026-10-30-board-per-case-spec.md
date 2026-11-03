---
ticket: OME-1790
stack: repo
status: done
started: 2026-10-30
finished: 2026-10-30
---

# board-per-case-spec — Spec for O(selected) imported-board storage

## Intent

Write the design spec for OME-1790: imported Inspect boards are one `cases.json`, and every
consumer parses all of it, so a 2-Case run of a 330 MB board pays for the whole board. The spec
maps every consumer, compares storage options, and recommends one with acceptance criteria and
a test plan. No code in this unit.

## Planned changes

- `docs/spec/2026-10-30-OME-1790-board-per-case-storage.md` (new)
- this ledger

## Test plan

- Docs only: `uv run .claude/scripts/run_gates.py repo --base origin/main`.
- Every cited file:line re-read on `origin/main` (f76cacf85) before it went into the spec.

## Acceptance

- Spec covers the consumers with file:line, build/packaging/runtime load path, options A/B (+C)
  on memory, build time, image size, golden replay, migration, OME-1675/OME-1789 interaction
  and complexity, a recommendation, owner questions, acceptance criteria and a test plan.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see branch `board-per-case-spec` (spec commit).
- **Gates:** `run_gates.py repo --base origin/main` — ALL GATES GREEN.
- **Deviations:** added an Option C (stream the prefix of the unchanged `cases.json`), because
  selection is always a prefix today (`protocol.py:274`); also found two consumers the ticket
  does not list (`_case_by_input`, the completion-marker checks).
