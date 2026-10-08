---
ticket: OME-1484
stack: repo
status: done
started: 2026-10-05
finished: 2026-10-05
---

# observability-mirror-sweep — close the stale observability docs/tasks mirrors

## Intent

Linear shows these issues as Done: OME-942, OME-1130, OME-1131, OME-1132, OME-1184, OME-1134,
OME-1453 and OME-1452 (merged as #1213 on 2026-10-05). Their `docs/tasks/` mirrors still said
`in_review`. Flip each to `done`, with `closed:` set to Linear's `completedAt` date. Move the
OME-935 epic mirror from `backlog` to `in_progress`, which matches Linear.

## Planned changes

- 9 mirror frontmatter edits under `docs/tasks/`, and this ledger plus the OME-1484 mirror.

## Test plan

- `python3 .claude/scripts/check_mirror_status.py` green.

## Acceptance

- Each mirror listed above matches its Linear state. No ledger changed (all were already `done`).

## Outcome

- **Actual files:** as planned.
- **Gates:** `check_mirror_status.py` green.
- **Deviations:** the OME-1069 mirror ("runner traceability") is NOT touched. Linear OME-1069 is
  an unrelated canceled issue (AI Gateway discovery timeout), so the mirror probably carries
  the wrong id. Left for owner triage.
