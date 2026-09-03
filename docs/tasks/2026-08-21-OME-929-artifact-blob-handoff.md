---
id: OME-929
linear_url: https://linear.app/openmined/issue/OME-929/make-over-cap-result-artifacts-fetchable-on-multi-pod-deployments
status: in_progress
type: bug
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-08-21
closed:
---

# Make over-cap result artifacts fetchable on multi-pod deployments

Any Run whose result exceeds the 1 MiB inline cap is unfetchable on the hosted Engine. The
Runner Job pod and the App pod each mount their own `emptyDir` at `/tmp`, and
`URL4_CLOUD_ARTIFACTS_DIR` is set nowhere in the chart, so both halves fall back to the same
pod-local default — two different disks. The client redeems the claim ticket against the App and
gets 404, after the entire cost of the run is paid (11,902 model calls for a full DRACO 3-pass).
The artifact *is* the Report's payload, so the user gets no Report at all. Known gap flagged on
`OME-892`, not a new regression. Owner confirmed 2026-08-21 that it reproduces in the deployed
pod environment.

Fix (owner decisions, spec §3): spilled artifacts move to **self-hosted S3-compatible object
storage** (Garage, bundled in our charts) for the `k8s`/`jetstream` backends;
`inprocess`/local keeps the filesystem store unchanged. The App **streams artifacts through**
rather than redirecting to a presigned URL, so the SDK's existing size+sha256 verification
survives untouched and this stays a single-landing unit. Client is `httpx` + a hand-rolled
SigV4 signer — bounded to PUT/GET of one object, no multipart, no presigning; we sign and
Garage verifies, so a signer bug fails closed.

Also closes the coverage gap that let it ship: `ARTIFACTS_DIR` is declared in
`job_env.DEPLOY_TIME` ("Helm owns these end-to-end") while Helm sets nothing, and the contract
test asserts only that the App *doesn't* write deploy-time names — never that the chart *does*.
A `DEPLOY_TIME` ↔ rendered-chart test would have gone red the day OME-892 landed.

Spec: `docs/spec/2026-08-21-OME-929-artifact-blob-handoff.md`
Plan: `docs/plan/2026-08-21-OME-929-artifact-blob-handoff.md`
Ledger: `docs/work/2026-08-21-OME-929-artifact-blob-handoff.md`
