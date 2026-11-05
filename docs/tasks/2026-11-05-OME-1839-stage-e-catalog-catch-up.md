---
id: OME-1839
linear_url: https://linear.app/openmined/issue/OME-1839/retire-the-profile-era-models-from-the-aigateway-catalog-stage-e
status: in_progress
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-11-05
closed:
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

- 2026-11-05: filed at PR-open; the catalog PR opened in `screamingface-design`.
