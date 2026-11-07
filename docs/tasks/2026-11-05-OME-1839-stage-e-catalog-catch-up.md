---
id: OME-1839
linear_url: https://linear.app/openmined/issue/OME-1839/retire-the-profile-era-models-from-the-aigateway-catalog-stage-e
status: done
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-11-05
closed: 2026-11-07
---

# Retire the Profile-era models from the AIGateway catalog (Stage E catalog catch-up)

The AIGateway catalog in `screamingface-design` moves from gateway source `d35a46537` to
`24d979a5e`, after Stage E removed the Profile. The fifteen generated datamodels whose models left
the source, and the authored `profile-defaults`, become `deprecated`. The two live models that
narrowed move to successors with a `supersedes` edge (`oauth-connection-listing`,
`chat-usage-accounting`), the other generated cards advance once, the eight models added since
get `draft` cards, and both OpenAPI snapshots are re-extracted. Authored cards that described
Stage E-deleted code, renamed hooks or retired routes as live are corrected, each advancing once.
Spec `docs/spec/2026-11-05-stage-e-catalog-catch-up.md`, plan
`docs/plan/2026-11-05-stage-e-catalog-catch-up.md`, ledger
`docs/work/2026-11-05-stage-e-catalog-catch-up.md`.

- 2026-11-05: filed at PR-open; the catalog PR opened in `screamingface-design`. In Review.
- 2026-11-06: review findings addressed in the spec, plan and ledger.
- 2026-11-06: squash-merged to `main` as `188246268ebf4b833e29bd78b38c3f2ef3a836af` (PR #1691);
  the catalog PR merged in `screamingface-design` as `01368cdab85cb925be3d0ccd0efa0472246d0be8`
  (PR #34).
- 2026-11-07: closed Done in Linear with the close comment. The shared checkout's local projection
  tools now carry the reviewed patch, SHA-256
  `98f0c5e5817954b7de3fc41cdfb2f12ceaada2007222e8ac465a5553824f11d8`.
