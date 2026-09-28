---
id: OME-1230
linear_url: https://linear.app/openmined/issue/OME-1230/add-the-provider-credential-admin-interface-and-reduce-the-profile
status: in_progress   # code stage authorized by the owner on 2026-09-18 after design PR #21 merged
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-09-18
closed:
---

# Add the provider-credential admin interface and reduce the Profile management routes to shells

Stage A3 of `OME-1138`. A2 (`OME-1207`) moved the runtime consumers onto `provider_access`; the
credential management routes still own their write bodies directly, `ProviderCredentialAdmin`
(ops 7–9) is declared but unimplemented, and `ProviderAccess.availability` (op 6) raises
`NotImplementedError`. This unit puts the write bodies behind the declared interface, reduces the
tenant and admin management routes to thin compatibility shells over it, and implements
`availability` in-process — with HTTP bodies, status codes, OpenAPI, authorization, sanitization
and both conflict contracts unchanged. Backing stays the legacy Profile.

D20 vocabulary binds: `Connection` is the final resource noun, `provider access` the boundary,
`legacy Profile` the compatibility surface. `Provider Account` is not introduced.

Ledger: `docs/work/2026-09-18-OME-1230-provider-credential-admin.md`.
Spec: `docs/spec/2026-09-09-OME-1138-converge-connections.md` §3.3 (ops 6–9), §3.4, §5 A3, §8.
Plan: `docs/plan/2026-09-09-OME-1138-converge-connections.md` §2 U3, §3 A3.
Catalog: `solutions/screamingface/product/aigateway/protocol/provider-credential-admin` in the
design repository (v1, draft).

- 2026-09-18: issue filed. Catalog verified against source revision `248b0b6d` (post-A2 state:
  routes → `provider_access` adapter → legacy Profiles; refresh merged). A3 card drafted with
  participant edges on the product, provider-access and credential-store cards; catalog check
  0 errors. **Gate:** the A3 card is not yet accepted/committed and code depends on it → Needs
  Owner. No application code written.
- 2026-09-18 (later): design analysis at the gate. The Protocol summary cannot carry today's
  Profile JSON on its own (spec §3.2 window-only projection applies); key validation and the
  post-commit OAuth cleanup are edge halves that stay in the shells; one prior OME-307 API-key
  race test patches the persistence helper on the route module and will need re-expression at the
  new seam. Four forks (F1–F4) recorded in the ledger and raised on the issue. Still no code.
- 2026-09-18 (evening): owner decided F1–F4 (opaque window-only projection field, removal at E;
  re-express the prior OME-307 API-key race test at the admin seam; dedicated rendering rows for
  the provider-less DELETE 404 bodies; key validation stays in the shell). Card updated; design
  branch to be committed, pushed and opened as a PR. Application code waits for the PR merge and
  explicit authorization.
- 2026-09-18 (evening, later): design repository commit `216acd0` pushed; PR #21 opened for the A3
  card. Waiting for the merge and for explicit authorization of the code stage.
- 2026-09-18 (evening, merge): design PR #21 merged by the owner (merge commit `65ab0b6f`); the A3
  card is on the design repository's `main`. First gate cleared; still waiting for explicit
  authorization before any application code.
- 2026-09-18 (night, code stage): the owner authorized the application-code stage in plain words
  after the PR #21 merge; issue moved to In Progress. A3 implemented per the merged card and F1–F4:
  `core/provider_access/profile_admin.py` (Profile-backed `ProviderCredentialAdmin`), `availability`
  in `profile_backed.py`, refusal rows in `routes/provider_access_http.py`, the tenant and admin
  Profile management routes reduced to shells (`routes/auth.py` 1424 → 1360 lines), four new test
  suites; the one prior-test change is the owner-approved F2 re-expression. Gates: ruff, pyright,
  no-enterprise, full pytest 4654 passed / coverage 92.52 % green; PostgreSQL lane 6 passed; OpenAPI
  byte-identical to the branch base; append-only check RED by design (F2). Committed locally on
  the branch under the owner's commit-only authorization; push and PR await separate authorization.
