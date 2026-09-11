# OME-898: align SDLC with product and documentation flows

The epic. This branch carries the epic-level map and the three children that have not
started. Children 01 and 02 live on their own branches off this one, so each can be reviewed
and landed without dragging the others along.

| Child | Deliverable | Lands in | Where it is |
|---|---|---|---|
| 01 writing-docs | a product-agnostic documentation-writing and review skill | its own repository, not a product repo | branch `callis/ome-898-01-writing-docs` |
| 02 product-context | a single source of truth for product and brand context | this monorepo | branch `callis/ome-898-02-product-context` |
| [03 sdlc-flow-update](03-sdlc-flow-update/) | the `.claude/` flow, with folder-scoped routing to the new skills | this monorepo | not started |
| [04 docs-in-every-pr](04-docs-in-every-pr/) | documentation generated as part of every PR | this monorepo, and the docs site | not started |
| [05 release-docs-review](05-release-docs-review/) | the release-time manual docs review by product | process document | not started |

The epic's own stated Done when is "SDLC flow updates", which is child 03. The epic cannot
close before that lands.

**Nothing in 03 through 05 should start before the drafts in 01 and 02 are reviewed.** They
are consequences of that review, not queued work.

## Numbering

The numbers fix the order the children were derived in, which is the order of the scope
bullets on the ticket. A number is not a priority and not a dependency, though 01 and 02 both
feed 03.

## Conventions

- No em-dashes or en-dashes in anything written in this tree.
- Nothing in child 01's deliverable names a product, an organisation, or a repository.
  Everything project-specific reaches it through a context contract at runtime.
- Specs and plans stay `status: draft` until the matching work item is filed.
- Child 01 and child 02 are independent of each other and of any existing skill. Where a rule
  is duplicated across them, that is accepted rather than factored out.
