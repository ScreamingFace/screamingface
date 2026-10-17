# OME-898: align SDLC with product and documentation flows

The epic.

| Deliverable | Lands in | Where it is |
|---|---|---|
| a product-agnostic documentation-writing and review skill (writing-docs) | its own repository, not a product repo | branch `callis/ome-898-01-writing-docs` |
| a single source of truth for product and brand context (product-context) | this monorepo | branch `callis/ome-898-02-product-context` |
| the `.claude/` flow, with folder-scoped routing to the new skills | this monorepo | merged |
| documentation generated as part of every PR | this monorepo, and the docs site | merged |
| the release-time manual docs review by product | process document | drafted |

The epic's own stated Done when is "SDLC flow updates". The epic cannot close before that
lands.

## Conventions

- No em-dashes or en-dashes in anything written in this tree.
- Nothing in the writing-docs skill's deliverable names a product, an organisation, or a
  repository. Everything project-specific reaches it through a context contract at runtime.
- Specs and plans stay `status: draft` until the matching work item is filed.
- The writing-docs and product-context skills are independent of each other and of any
  existing skill. Where a rule is duplicated across them, that is accepted rather than
  factored out.
