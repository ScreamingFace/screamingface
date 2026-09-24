# 04: documentation as part of every PR

Status: layer 2 (the CI check) built, verified against real history, and live. Layers 1 and
3 blocked on child 01. See `spec.md`, `plan.md`, `symbol-page-map.md`,
`packages/screamingface/scripts/check_docs_sync.py`, and
`.github/workflows/docs-sync-check.yml`.

## Scope, from the ticket

Whenever a PR is made, documentation is part of it, automatically generated.

## The mechanism

Three layers, not three alternatives: in-loop drafting while a change is made, a minimal CI
check at PR time, and a follow-up PR for anything that still merges without one. Full detail
in `spec.md`.

The CI check's two hard questions, both answered in the spec: what counts as public surface
(`__all__` in the Client's `__init__.py`, resolved to its backing file by parsing the
import statements directly, not a directory-naming convention), and how a changed symbol
maps to its docs page (`symbol-page-map.md`).

## Contents

- `spec.md`: the mechanism
- `plan.md`: three steps, all done
- `symbol-page-map.md`: 55 of 58 `__all__` names mapped to their docs page, three named as
  gaps rather than silently missing
- `packages/screamingface/scripts/check_docs_sync.py`: the check, live, verified against two
  real historical commits, one that fails and one that passes
- `.github/workflows/docs-sync-check.yml`: its own workflow rather than a job in
  `public-docs-tests.yml`, since that workflow's trigger would never see a Python-only change
