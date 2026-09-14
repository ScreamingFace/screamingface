# 02: product and brand context skill

Status: spec drafted, see `spec.md`. Evidence in `findings.md`. No plan yet.

Named `product-context` to avoid colliding with the marketplace skill of a similar name.

## Scope, from the ticket

- Review the `screamingface-context` skill in the openmined marketplace and re-use that
  context.
- Add anything missing from the brand-positioning and product-positioning documents.
- Land a single source of truth that informs engineering tickets, copy, and documentation.
- Remove or update outdated skills that confuse. `docs/positioning.md` is explicitly not to
  remain a source of truth.
- Today engineers rely only on what the repository's own skills carry, not on the context
  skill. Closing that gap is the point.

## What it feeds

This is what fills the context contract that child 01's skill declares: product facts,
terminology casing, positioning language, the reader, and the operational metrics.

## Not blocked

An earlier draft of this file recorded the two positioning Google Docs as a blocker needing
someone's access. They are not. The upstream context skill already mirrors them into the
marketplace repository, alongside the strategy doc, the canonical terminology, the four
personas, and the launch deck, and all of it is readable with `gh`.

What that means for this child: the content exists, so the work is reconciling it against
what the repository currently carries, deciding what becomes canonical, and retiring the
rest. There is nothing to wait for.

## Expected contents

- `spec.md`
- `plan.md`
- the deliverable, or a pointer to where it landed
