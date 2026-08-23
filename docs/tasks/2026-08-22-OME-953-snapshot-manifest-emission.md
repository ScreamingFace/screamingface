---
id: OME-953
linear_url: # pending — owner creates the sub-issue in Linear under the OME-950 epic
status: todo
type: improvement
priority: 3
labels: [repo, autonomous, agentic]
created: 2026-08-22
closed:
---

# snapshot-cache emits a revision-guard manifest

PROVISIONAL id — see the epic mirror (`docs/tasks/2026-08-22-OME-950-admin-cache-snapshot-upload.md`).

Repo-script half of OME-950, per `docs/spec/2026-08-22-OME-950-admin-cache-snapshot-upload.md`:

- `local_k8s_deployment.sh snapshot-cache` additionally writes `<name>.manifest.json` beside
  the `.sql.gz`: schema tag, generated_at, row_count, sha256 of the archive, and the deployed
  gateway's revision constants (`PARAMETER_CONTRACT_REVISION`, `GLOBAL_CACHE_ADAPTER_REVISION`).
- The constants are read from the aigateway image running in the cluster (one-shot Job, the
  same mechanism `restore-cache` uses for `generate_schemas`) — never from the host checkout.
- Runbook note in the script header: the manifest travels with the snapshot; the admin upload
  (OME-951) verifies it and refuses mismatches.
