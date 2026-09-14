# 04: documentation as part of every PR

Status: not started. No spec, no plan.

## Scope, from the ticket

Whenever a PR is made, documentation is part of it, automatically generated.

## The decision this needs first

The line admits at least three incompatible readings, and they cost very different amounts:

| Mechanism | What it does | Cost |
|---|---|---|
| CI gate | fails a PR that changes public behaviour with no docs change | needs a definition of "public behaviour" that a script can evaluate |
| in-loop step | the SDLC loop drafts docs while the change is being made | no CI work, but nothing enforces it |
| follow-up bot | opens a separate docs PR after the code PR merges | docs always lag by one merge |

## The complication

The documentation site is not in this monorepo. A gate here cannot require a change that has
to land in another repository, so whichever mechanism wins has to answer the cross-repo
question explicitly.

## Expected contents

- `spec.md`, which is mostly the mechanism decision
- `plan.md`
- the implementation, or a pointer to the PRs
