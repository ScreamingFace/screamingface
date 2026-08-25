---
ticket: OME-986
stack: scoreboard
status: planned
started: 2026-08-25
finished:
---

# OME-986 — Retire the legacy news demo benchmarks

## Intent

`hle`, `livetruth` and `livetruth-latest` are leftovers from the previous SF project, still
advertised on the catalogue of the board being handed to internal testers this week. Irina asked
for their removal in `#scream-dev` on 2026-08-25.

Removing them from the chart's seed list is necessary but not sufficient: seeding only registers
and updates, so the rows persist and keep being served. A deletion path has to exist first, and
this unit builds it as an operator module rather than a migration or hand-written SQL.

## Status

**Prepared, not started.** Owner asked for the groundwork only — ticket, spec, plan, ledger — with
no implementation yet. Nothing under `apps/` or `charts/` has been touched.

## Facts established before design

Full table in the spec (§2). The two that shape the unit:

- **F1/F2** — seeding never deletes, so the config change alone changes nothing a reader sees.
- **F3/F4** — all three are empty today (0 entries, 0 baselines) and both foreign keys are
  `RESTRICT`, so nothing blocks deletion right now. That stops being true the moment a tester
  submits against one, which is why this is cheaper now than later.

## Owner decisions (2026-08-25)

- Operator module plus the config removal, rather than a migration or raw SQL.
- Scope is exactly the three revision-less ids; the five Engine-published benchmarks are a
  different conversation.

## Planned changes

Per `docs/plan/2026-08-25-OME-986-retire-news-benchmarks.md`: refusal path → unknown-id guard →
deletion → CLI wrapper → chart seed list → close-out. The refusal path is built and tested before
the deletion path, because destroying submissions is this module's only real risk.

## Test plan

Per the plan, RED-first. Contracts pinned: a referenced benchmark is refused **and survives**; an
unknown id is refused rather than reported as success; an unreferenced benchmark is deleted and
stops being advertised.

## Acceptance

See spec §6.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">
