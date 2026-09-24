---
id: OME-1266
linear_url: https://linear.app/openmined/issue/OME-1266/correct-the-release-lanes-in-the-working-in-this-repo-routing-table
status: done
type: task
priority: medium
labels: [repo, agentic, autonomous]
created: 2026-09-22
closed: 2026-09-24
---

# Correct the release lanes in the working-in-this-repo routing table

Two of the routing skill's seven release lanes are wrong: `apps/scoreboard` and `packages/url4`
are both described as manual tags outside release-please, and both are in
`release-please-config.json`. The scoreboard error already misled a session — `OME-1181` was told
the deploy was a manual tag the owner had to cut.

Ledger: `docs/work/2026-09-22-OME-1266-routing-table-release-lanes.md`.

- 2026-09-22: filed after the `OME-1265` doc-drift work surfaced the same class of problem one
  layer up. Verified against `release-please-config.json` and the release workflows before
  filing. **Gate:** In Progress.
- 2026-09-22: scope widened during verification. `apps/analytics` (24 tracked files, own test and
  dev-build workflows, CODEOWNERS @sergio-bershadsky @HupBaHa) and `apps/screamingface-studio`
  (97 tracked files, CODEOWNERS @itstauq) are absent from the table entirely and get rows.
  `apps/desktop` is left alone and raised as a finding: its only two tracked files are build
  artifacts under `out/`, left by the July 2026 teardown, and a `release-desktop.yml` still
  exists. Removing those is a code change needing an owner decision, not a doc fix.
