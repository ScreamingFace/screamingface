# 03: SDLC flow update

Status: not started. No spec, no plan.

This child carries the epic's stated Done when, so the epic closes on this one.

## Scope, from the ticket

- Review and update `.claude/`.
- Folder-scoped routing: working in this folder means using this skill.
- Route documentation and copy work to the writing-docs and product-context skills.
- Retire or refresh skills that are outdated or confusing.

## Also folded in here

Installing the writing-docs skill in this repository. That was deliberately kept out of the
skill itself so it never reaches into a product repository, which is what keeps it agnostic.

## Depends on

The writing-docs and product-context skills, because the routing has to point at skills
that exist.

## Expected contents

- `spec.md`
- `plan.md`
- the `.claude/` changes, or a pointer to the PR
