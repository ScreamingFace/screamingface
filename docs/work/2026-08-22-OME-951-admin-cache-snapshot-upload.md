---
ticket: OME-951
stack: repo
status: done
started: 2026-08-22
finished: 2026-08-22
---

# OME-951 — Admin cache-snapshot upload (spec + scaffolding unit)

## Intent

Specify the admin feature that feeds a `snapshot-cache` pg_dump of `request_cache_entries`
into a deployed aigateway (merge semantics, guarded replace, revision guard) and file the
epic's documentation scaffolding. No implementation in this unit — spec, mirrors, diagram.

## Planned changes

- `docs/spec/2026-08-22-OME-951-admin-cache-snapshot-upload.md` (new)
- `docs/tasks/2026-08-22-OME-951-admin-cache-snapshot-upload.md` (new, epic mirror)
- `docs/tasks/2026-08-22-OME-952-aigateway-cache-snapshot-upload.md` (new)
- `docs/tasks/2026-08-22-OME-953-aigateway-ui-cache-upload-console.md` (new)
- `docs/tasks/2026-08-22-OME-954-snapshot-manifest-emission.md` (new)
- `docs/diagrams/ome-950-cache-snapshot-upload.svg` + `.png` (new)

## Test plan

- None — documentation unit. Code gates do not apply; CI runs docs-agnostic.

## Acceptance

- Spec covers outcome, contract, algorithm, invariants, scope split, non-goals, limitations,
  and testable acceptance criteria (12 items).
- Epic + 3 sub-issue mirrors follow the task-board frontmatter rules (landing label, one
  who-acts, one actor). Linear issues are pending owner creation (MCP not active).
- Diagram committed as SVG + PNG per docs/README.md.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned
- **Commits:** 9f191515 — docs(spec): OME-951 admin cache-snapshot upload — spec, mirrors, ledger, diagram
- **Gates:** n/a (docs-only)
- **Deviations:** filed as OME-951..954 in Linear (one off the drafted OME-950..953; ids and file names updated)
