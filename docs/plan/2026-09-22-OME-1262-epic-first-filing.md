# OME-1262 — Epic-first filing in the SDLC docs

**Goal:** Make a new session file every leaf under an existing epic, and stop instead of filing an orphan when no epic fits.

**Spec:** `docs/spec/2026-07-08-ai-sdlc-adoption-spec.md` — decisions D14–D18 (2026-09-22). Parent epic: `OME-1259`.

**Out of scope for this unit:** reparenting the open orphan tickets (`OME-1261`, owner-approved), and the Linear UI actions (`OME-1260`: saved view, template, milestone retirement). The standalone `epic` label was created by the owner 2026-09-23 and registered in the card.

## Tasks

- [x] Epic `OME-1259` filed, with `OME-1262` (this unit), `OME-1261` (triage), `OME-1260` (owner UI).
- [x] Skill, card, `CLAUDE.md`, `.claude/README.md`, both filing agents, and the superseding spec block.
- [x] Mirrors for the four issues, plus this plan and the work ledger.
- [x] `uv run .claude/scripts/check_loop_parity.py` stays green (no sdlc loop edit).
- [x] Search `.claude/` and `CLAUDE.md` for a remaining "sprints are milestones" rule — none.

## STOP choice used here

The no-epic stop does not file. An already-filed issue with no parent moves to **Triage**. The `blocked` / `needs-owner` labels are not live, and this unit does not add workflow states.

## Open item

Resolved 2026-09-23 (`OME-1259`): Irina Bejan doubles as the product reviewer, so `reviewers.product: irina@openmined.org` and both review paths tag Irina and Kevin. No separate product handle.
