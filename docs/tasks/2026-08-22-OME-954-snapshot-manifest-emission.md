---
id: OME-954
linear_url: https://linear.app/openmined/issue/OME-954/snapshot-cache-emits-a-revision-guard-manifest
status: todo
type: improvement
priority: 3
labels: [repo, autonomous, agentic]
created: 2026-08-22
closed:
---

# snapshot-cache emits a revision-guard manifest

Repo-script half of OME-951, per `docs/spec/2026-08-22-OME-951-admin-cache-snapshot-upload.md`:

- `local_k8s_deployment.sh snapshot-cache` additionally writes `<name>.manifest.json` beside
  the `.sql.gz`: schema tag, generated_at, row_count, sha256 of the archive, and the deployed
  gateway's revision constants (`PARAMETER_CONTRACT_REVISION`, `GLOBAL_CACHE_ADAPTER_REVISION`).
- The constants are read from the aigateway image running in the cluster (one-shot Job, the
  same mechanism `restore-cache` uses for `generate_schemas`) — never from the host checkout.
- Runbook note in the script header: the manifest travels with the snapshot; the admin upload
  (OME-952) verifies it and refuses mismatches.
