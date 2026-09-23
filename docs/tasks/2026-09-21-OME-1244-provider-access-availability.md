---
id: OME-1244
linear_url: https://linear.app/openmined/issue/OME-1244/publish-the-backing-neutral-availability-listing
status: in_progress   # code stage authorized 2026-09-21 after design PR #22 merged
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-09-21
closed:
---

# Publish the backing-neutral availability listing

Stage A4 of `OME-1138`, gateway half (plan unit U4). A3 (`OME-1230`, PR #992) put the Profile
management bodies behind `ProviderCredentialAdmin` and implemented `ProviderAccess.availability`
in-process. This unit publishes the caller-scoped read-only successor `GET /v1/provider-access`
(D17): rows of `provider` and `status` only, `Cache-Control: private, no-store`, inbound
`X-Profile` non-selecting, no names, ids, labels, defaults, auth method, account label, locators,
reauth URL, credential names or secrets. The Hosted Engine switch is the sibling unit `OME-1245`.

D20 vocabulary binds: `Connection` is the final resource noun, `provider access` the boundary,
`legacy Profile` the compatibility surface. `Provider Account` is not introduced.

Ledger: `docs/work/2026-09-21-OME-1244-provider-access-availability.md`.
Spec: `docs/spec/2026-09-09-OME-1138-converge-connections.md` §3.2, §3.5, §5 A4, §8 (D15, D17), §11.
Plan: `docs/plan/2026-09-09-OME-1138-converge-connections.md` §2 U4, §3 A4.

- 2026-09-21: issue filed as plan unit U4 after PR #992 (A3) merged as `a78d58da`. Metamodel
  gate checked at design `main` `65ab0b6f`: the provider-access component card still calls
  `availability` declared-only and states no `/v1/provider-access` router exists; the protocol
  card lists no such operation → the design PR comes first. **Gate:** Needs Owner (metamodel
  acceptance and scope approval). No application code written.
- 2026-09-21: design update authored (new `protocol/provider-access-availability` card, the
  provider-access component and provider-credential-admin cards refreshed to `a78d58da`, Engine
  `uses` edge, credential-store and product edges); catalog check 0 errors / 3 baseline warnings.
  Awaiting authorization to commit, push and open the design PR. **Gate:** Needs Owner.
- 2026-09-21: owner approved the issue as filed (gate 2) and authorized a commit-only landing
  of the design update: design commit `defd3f7b` on branch `OME-1244-provider-access-availability`.
  Push, PR and merge of the design branch remain owner steps; code waits for them. **Gate:** Todo.
- 2026-09-21: design PR #22 merged as `a2468eee` (gate 1 cleared). The owner authorized the
  application-code stage in plain words: route only, no Engine switch, nothing from Stages B–E.
  Linear → In Progress. Branch fast-forwarded to `origin/main` `39cea39f`; RED tests first.
- 2026-09-21: RED → GREEN complete. Route module `routes/provider_access_availability.py` +
  registration in `main.py`; 13 new tests. Gates all green vs `39cea39f` (4667 passed / 79 skipped /
  92.53%); OpenAPI diff = the new operation and its two schemas only; PostgreSQL lane 6 passed
  (full `needs_postgres` set green once PostgreSQL 16 client tools are on PATH); Python 3.12 leg
  25 passed. Ledger Outcome filled. **Gate:** Needs Owner — authorization to stage the exact paths,
  commit, push and open the PR.
