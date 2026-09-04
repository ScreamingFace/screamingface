# OME-1027 — Implementation plan

## Frame

Replace the misleading semver floor, provide an export-certified private-board purge, and turn the
fallback runbook into an exact sequence that verifies both data removal and zero serving endpoints.

## Changes

1. Add task, spec, plan, and work-ledger artifacts.
2. RED: add a new purge test module covering dry-run, confirmation, exact digest, public/unknown
   refusal, baseline refusal, exact targeting, and rollback-on-failure behavior.
3. RED: update the existing verdict test that asserts the now-rejected semver-floor claim. This is
   the one prior-test exception explicitly approved by the owner on 2026-09-04 when approving the
   switch from semver to immutable release identity.
4. GREEN: add `scoreboard.purge_private_benchmark`, sharing the existing export serialization and
   using one Tortoise transaction with a locked benchmark row.
5. Allow the existing full-history score reader to use an explicit transaction connection; no
   model or schema change is involved.
6. Rewrite `DEPLOYMENT.md` with exact Helm/image evidence, export/digest/purge commands, the `SAFE`
   check, pod termination wait, endpoint assertion, rollback, and replica restoration.
7. Run focused tests, the full Scoreboard suite, and `run_gates.py scoreboard` with the documented
   append-only exception.
8. Complete the ledger, commit with `Refs: OME-1027`, push, and open a PR. Leave Linear In Progress
   until production evidence satisfies the operational closure gate.

## Wisdom check

- A generic database shell or pasted SQL would be smaller in lines but not safer: it cannot prove
  which exported bytes correspond to the rows being destroyed.
- A Helm hook cannot guard a rollback to an old manifest.
- A bulk purge increases blast radius without helping the one-board emergency procedure.
- No migration is needed because the database schema is unchanged.
