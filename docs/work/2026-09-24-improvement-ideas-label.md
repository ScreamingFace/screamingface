---
ticket: OME-1334
stack: repo
status: done
started: 2026-09-24
finished: 2026-09-24
---

# improvement-ideas label — a no-epic, no-relation parking marker

## Intent

Add an `improvement-ideas` team label that functions like `blocked` (a standalone marker in the
card's `stop:` bucket) but with a lighter filing contract: it may be applied with NO epic parent
and NO blocker relation, and the component/landing label is optional. It captures enhancement/
parking-lot ideas. Parked like a `bug` — Triage, unassigned.

## Planned changes

- Linear: create the `improvement-ideas` team label (done — `fb1131ea-…`).
- `.claude/task-board.local.md` — register the label in the `stop:` bucket + document its rule.
- `CLAUDE.md` rule 1 — name `improvement-ideas` as a second epic-first exception alongside `bug`.
- `.claude/skills/task-management/SKILL.md` — document the label's filing contract next to `blocked`
  and `bug`.

## Acceptance

- Label exists in Linear (Engineering) and is registered in the card.
- All three docs describe: no-epic OK, no relation required, component optional, parked in Triage
  unassigned.

## Outcome

- **Filed:** OME-1334 (under epic OME-1259).
- **Label:** `improvement-ideas` created in Linear (Engineering) — `fb1131ea-6e7e-4037-90b5-24ec48a10017`.
- **Files:** `CLAUDE.md`, `.claude/task-board.local.md`, `.claude/skills/task-management/SKILL.md`.
  Docs + label only; no code behavior change.
- **Gates:** SHARED-LOOP untouched; `check_loop_parity.py` green.
- **Deviations:** `stop:` turned out not to be a real Linear single-select group (`blocked` has no
  parent) — it is a card-doc bucket of standalone markers, so `improvement-ideas` is likewise a
  standalone additive label. Documented as such.
