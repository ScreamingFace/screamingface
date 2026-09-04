---
ticket: OME-822
stack: scoreboard
status: done
started: 2026-09-03
finished: 2026-09-04
---

# OME-822 — Require run cost on direct submissions

## Intent

Reject new direct leaderboard submissions that omit or null the run total now that the producer
chain is shipped, without changing the nullable historical/imported data contract.

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/schemas.py` — required non-null request field.
- Scoreboard unit fixtures — explicit costs plus omission/null/OpenAPI route assertions.
- `apps/scoreboard/DEPLOYMENT.md` — valid direct-submission smoke payload.
- `public-docs/src/pages/sf-client/guides/LeaderboardsPage.vue` — document the published cost and
  null/zero boundary.
- task, spec, plan, and this work ledger.

## Test plan

- Reject missing and null at schema and real HTTP boundaries.
- Keep zero and the complete OME-770 normalization matrix green.
- Keep imported/legacy null reads green.
- Assert the OpenAPI request schema declares the field required.
- Run the full Scoreboard and affected public-docs gates.

## Acceptance

- Direct omission/null returns a field-local `422`.
- Every accepted direct submission stores a non-null normalized cost.
- No database/read migration; old/imported null rows remain readable.
- Docs and smoke commands match the request contract.
- CI-equivalent gates are green and the PR is linked from Linear.

## Outcome

- **Actual files:** as planned. Tightened only the direct request DTO and validator typing; added
  missing/null/OpenAPI assertions; supplied explicit costs in every direct-submission fixture;
  retained controlled legacy-null read tests; corrected the deployment smoke payload and public
  Client guide; added the task/spec/plan/ledger set.
- **Commits:** one conventional feature commit on `OME-822-require-run-cost` (squash target; final
  merge sha will be recorded in Linear).
- **Gates:** Scoreboard `run_gates.py ... --base origin/main --skip-append-only` ALL GREEN (ruff,
  format, pyright, pytest coverage ≥80, three explicit portal suites). Direct full run: 602 passed,
  3 skipped, 3 deselected. Public docs: clean `npm ci`, bare oxlint, bare eslint, Vue typecheck, and
  production Vite build all green.
- **Deviations:** the spec/plan were recorded retroactively because the implementation commit had
  already been prepared in the prior session. Existing test changes use the owner's explicit
  Confidence-Gate exception; the database/read contract remains nullable and no migration exists.
  The public-docs build succeeded locally, though Node 24.10 emitted an engine warning against the
  repository's newer ≥24.12 floor; CI pins the repository version. The SFDS copy check kept the
  guide change factual and evidence-led, with no visual-system changes. PR #840's independently
  added direct-submission fixtures were also made cost-ready there, so the two PRs can merge in
  either order without breaking `main`.
