# 03: SDLC flow update

Status: not started. No spec, no plan.

This child carries the epic's stated Done when, so the epic closes on this one.

## Scope, from the ticket

- Review and update `.claude/`.
- Folder-scoped routing: working in this folder means using this skill.
- Route documentation and copy work to the new skills from children 01 and 02.
- Retire or refresh skills that are outdated or confusing.

## Also folded in here

Installing child 01's skill in this repository. That was deliberately kept out of child 01
so the skill itself never reaches into a product repository, which is what keeps it
agnostic.

## Depends on

Children 01 and 02, because the routing has to point at skills that exist.

## Expected contents

- `spec.md`
- `plan.md`
- the `.claude/` changes, or a pointer to the PR
