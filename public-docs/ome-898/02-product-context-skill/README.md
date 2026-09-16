# 02: product and brand context skill

Status: spec, plan, and a first draft of the skill exist. See `spec.md`, `plan.md`,
`findings.md`, and `product-context/SKILL.md`.

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

The two positioning Google Docs are not a blocker. The upstream context skill already
mirrors them into the marketplace repository, alongside the strategy doc, the canonical
terminology, the four personas, and the launch deck, and all of it is readable with `gh`.

The work is reconciling that content against what the repository currently carries, deciding
what becomes canonical, and retiring the rest.

## Contents

- `findings.md`: what `docs/positioning.md` and the marketplace canon disagree on
- `spec.md`
- `plan.md`
- `product-context/SKILL.md`: the deliverable
