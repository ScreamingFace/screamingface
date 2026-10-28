---
id: OME-1758
linear_url: https://linear.app/openmined/issue/OME-1758/compare-the-configured-endpoint-cache-revision-on-an-sdk-cache-pull
status: in_progress
type: fix
priority: high
labels: [client-sf, agentic, autonomous]
parent: OME-1306
created: 2026-10-28
---

# Compare the configured endpoint cache revision on an SDK cache pull

SDK half of the hosted BYOM Unit 1 branch (OME-1721), in `packages/screamingface`.

- Problem: a cache pull compared revisions built by the bundled plugin loader alone. The
  configured-endpoint adapter registers its revision only when the gateway's composition module
  is imported, so the local set lacked `remote_endpoint_adapter`, and a hosted page keyed under
  another revision of that adapter loaded as rows the local gateway never hits.
- Fix: collecting the local revisions also imports the composition module. It reads no config,
  reads no secret and starts nothing.
- Tests: a new test collects the revisions in a fresh process with only `PATH` and an empty
  `HOME`. The stand-in fixture of `test_cache_local` gains an empty composition module, approved
  by the owner on 2026-10-27.

Rollout: an SDK with this change refuses every pull from a hosted gateway that does not yet
report `remote_endpoint_adapter`. Deploy the hosted gateway with the OME-1721 export fix before an
SDK release carries this change.

Ledger: `docs/work/2026-10-22-hosted-byom-unit1.md`.
