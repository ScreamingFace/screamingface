---
id: OME-1209
linear_url: https://linear.app/openmined/issue/OME-1209/aigateway-retire-or-rename-legacy-profiles-surface
status: done
type: task
priority: medium
labels: [aigateway]
parent: OME-1138
blocked_by: [OME-1207, OME-1208, OME-1210, OME-1333, OME-1498]
related: [OME-1398, OME-1618]
created: 2026-09-15
closed: 2026-10-21
---

# AIGateway: retire or rename legacy Profiles surface

Stage E of `OME-1138`. Once consumers and backing have moved, the legacy Profile surface must not
stay as a second credential model in APIs, docs, generated types and UI. Scope: compatibility shims
and Profile route names; Profile/ProfileIndex schemas, errors and bootstrap hooks; `X-Profile`
propagation and selector vocabulary; Hosted listing labels; generated API/client references and UI
copy; migration-only storage cleanup once rollback safety conditions are met.

Spec: `docs/spec/2026-10-14-OME-1209-retire-legacy-profiles.md`.
Plan: `docs/plan/2026-10-14-OME-1209-retire-legacy-profiles.md`.

Each landing merged under its own leaf issue under `OME-1138`:

| Landing | Leaf | PR | Squash |
|---|---|---|---|
| E1 successor re-auth pointers | `OME-1618` | #1432 | `59545b20b` |
| E1b native repair of a migrated pair | `OME-1640` | #1449 | `00c1bef11` |
| E2a neutral credential vocabulary | `OME-1647` | #1458 | `4803a77c9` |
| E2b dead chat shims and saved defaults | `OME-1645` | #1456 | `1f873d95e` |
| E3 Profile routes retired with a 410 | `OME-1651` | #1464 | `08f534317` |
| E3b dead Profile-era core | `OME-1682` | #1480 | `aac2a1ab2` |
| E4a Connection-only readers | `OME-1685` | #1491 | `b66f94f08` |
| E4b no Profile document writer | `OME-1695` | #1516 | `f7e54869b` |
| E4c neutral plugin hook names | `OME-1703` | #1523 | `eb31158de` |

- 2026-10-21: closed Done in Linear with the Stage E close comment. Storage cleanup left this issue
  by owner decision (spec §7 Q4) and became E5, with its own leaves: `OME-1715` (E5a, PR #1541),
  `OME-1750` (E5b, PR #1573) and `OME-1759` (E5c, PR #1596).
