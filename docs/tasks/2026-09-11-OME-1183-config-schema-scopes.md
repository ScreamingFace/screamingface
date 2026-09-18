---
id: OME-1183
linear_url: https://linear.app/openmined/issue/OME-1183
status: In Progress
priority: High
labels: [screamingface-engine, agentic, design-session]
created: 2026-09-11
closed:
---

# OME-1183 — expose the node's layered configuration catalog as scoped JSON Schema via .well-known

Mirror of the Linear epic. **Linear is the status authority**; this file records what the
repo holds against it.

## Design

Locked 2026-09-11 in `docs/spec/2026-09-11-OME-1183-config-schema-scopes.md` (branch
`OME-1183-config-schema-scopes`, not yet pushed). Physical model, scope ladder,
`.well-known` layout, dynamic enums, and the catalog set are specified there.

## Implementation

Branch `OME-1183-url4-discovery-implementation`, ledger
`docs/work/2026-09-16-OME-1183-url4-discovery-implementation.md`.

Decisions taken during implementation and not in the parent spec are in
`docs/spec/2026-09-16-OME-1183-config-carriers-and-enforcement.md`.

| epic item | state |
|---|---|
| the three `.well-known` documents | served by `url4 serve` |
| node compilation / mount resolver | built (discovery only) |
| `x-scope` enforcement at rest | `walk_config` |
| `x-scope` enforcement in flight | `enforce` + `request.py` |
| `url4.json` migration off TOML | landed, 4 packages, `url4.toml` deleted |
| catalog linter + CI gate | `catalogs.yml` |
| **D1** carrier for user-scope values | **DECIDED 2026-09-16 — both valid** |
| **D2** suffix name | **DECIDED — `url4-` everywhere** |
| mount forwarding | NOT built — belongs to OME-1187 |
| `/v1/models` retirement | not started; needs the client repo |

## Decomposition — NOT done

The parent spec names four sub-issues after approval: `url4-sdk`,
`screamingface-engine`, `aigateway`, `py-screamingface`. The implementation above spans
the first three and was not split. Per CLAUDE.md rule 8 (cross-cutting → epic + one
sub-issue per landing) it should have been; the landing label group is single-select, so
this work cannot carry one correct leaf as it stands.

**Owner action:** decide whether to file those sub-issues retroactively and split the
branch, or land it as one unit against the epic.
