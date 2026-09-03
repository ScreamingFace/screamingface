---
ticket: OME-929
stack: screamingface-engine
status: in_progress
started: 2026-08-21
finished:
---

# OME-929 — Over-cap result artifacts must survive the Runner Job

## Intent

Every full-scale benchmark run on the hosted Engine currently produces **no Report at all**. A
result over the 1 MiB inline cap spills to a content-addressed artifact, but the Runner Job pod
and the App pod each mount their own `emptyDir` at `/tmp` and `URL4_CLOUD_ARTIFACTS_DIR` is set
nowhere in the chart — so both fall back to the same pod-local default, which is two different
disks. The client redeems the claim ticket against the App and gets 404, after all 11,902 model
calls of a DRACO 3-pass run have been paid for. The artifact *is* the Report's payload
(`_decoded_result_body` raises on a `None` body), so losing it is total, not partial.

This unit moves spilled artifacts into self-hosted S3-compatible object storage (Garage) for the
`k8s`/`jetstream` backends, keeps the filesystem store for `inprocess`/local, and closes the
coverage gap that let the bug ship.

Spec: `docs/spec/2026-08-21-OME-929-artifact-blob-handoff.md` (owner decisions D1–D5)
Plan: `docs/plan/2026-08-21-OME-929-artifact-blob-handoff.md` (three iterations)

## Planned changes

Iteration 1 — ports (no behaviour change):
- `src/screamingface_engine/artifacts/{__init__,ports,filesystem}.py` — split the single
  `ArtifactStore` into `ArtifactWriter`/`ArtifactReader`; `ArtifactStore` retained as an alias
  for `FilesystemArtifactStore` (24 call sites, 4 test modules, append-only tests)
- `src/screamingface_engine/rest/artifacts.py` — render `ArtifactContent` (`FileResponse` for
  `LocalFile`, `StreamingResponse` for `RemoteStream`)

Iteration 2 — the adapter and the bug's acceptance test:
- `src/screamingface_engine/artifacts/sigv4.py` — pure SigV4 signer (no I/O)
- `src/screamingface_engine/artifacts/s3.py` — `S3ArtifactStore` over `httpx`
- tests: SigV4 vectors, fake-S3 round-trip, **separate-roots acceptance test**, cap boundary,
  upload-before-terminal-frame ordering

Iteration 3 — wiring and loud failure:
- `deploy/helm/` — Garage template + values + PVC; S3 settings into `configmap-runner-env.yaml`
  and `configmap.yaml`; credentials Secret via `envFrom` (TAVILY precedent)
- `src/screamingface_engine/{config,job_env}.py`, `adapters/factory.py` — derived selection
  (§4.3) + startup guard (§4.4)
- tests: `DEPLOY_TIME` ↔ rendered-chart contract test; startup-guard tests
- comment corrections: `artifacts.py` header, `job_env.py:242`, `job_env.py:305`, `app.py:104`

## Test plan

Risk-ranked (highest first), mirroring the ticket's R1–R5:

- **R1 the bug.** Writer and reader on separate storage — over-cap result round-trips.
  Parametrised over both adapters: fails for filesystem-on-separate-roots with the 404, passes
  for S3. 100% reproducible.
- **R2 silent regression.** Every existing artifact test uses one store instance in one process,
  so none of them can catch a writer/reader split. The R1 test is the structural fix. Plus the
  `DEPLOY_TIME` ↔ chart contract test, which would have gone red the day OME-892 landed.
- **R3 cap boundary.** `cap-1`, `cap`, `cap+1` — first two inline, third spills.
- **R4 ordering.** Upload completes before the terminal frame is published; otherwise the client
  can redeem a ticket for an object that does not exist yet.
- **R5 diagnosability.** A storage mismatch fails at startup/first write with the missing
  setting named — never a fetch-time 404 minutes after the spend.
- SigV4 correctness against AWS's published test vectors (table-driven, pure).
- Error paths: bad signature (403), missing object (`None`, not an exception), truncated upload
  surfaces rather than minting a ticket for absent content.

Explicitly **not** covered: real Garage behaviour under load, and multi-replica App (out of
scope — the App is pinned to one replica for the in-process subscriber gate).

## Acceptance

Spec §6, items 1-8. Headline: a >1 MiB result round-trips end to end on the deployed pods, and
a writer/reader storage mismatch can no longer reach fetch time.

## Outcome

- **Actual files** (as planned, plus the four marked ✚):
  - `artifacts/{__init__,ports,filesystem,s3,sigv4}.py` — ports + both adapters + the signer
  - ✚ `artifacts/wiring.py` — the shared `S3Config` builder. Not planned: the validation is
    needed by BOTH halves, and `adapters/factory.py` (where the plan put selection) is
    control-plane, so the Runner cannot import it. It belongs in the shared leaf.
  - `rest/artifacts.py` — renders `LocalFile` (FileResponse, keeps Range) or `RemoteStream`
    (StreamingResponse + explicit Content-Length); `response_model=None` + `response_class`
    so FastAPI stops inferring a Pydantic field from a union of Starlette responses
  - `runner/executor.py` — `artifact_store` retyped to the `ArtifactWriter` PORT (pyright found
    the leftover coupling to the concrete filesystem class)
  - `runner/main.py` — `result_delivery_from_env` selects the store; refuses a half-configured one
  - `app.py` — `_build_artifact_reader` + the startup refusal; stale sweeper comment corrected
  - `config.py` — `ArtifactStoreBackend`, six `artifact_*` settings, `artifact_s3_secret_name`,
    ✚ a validator normalising a blank `artifacts_dir` (see deviation 4)
  - `job_env.py` — six new DEPLOY_TIME names; the inverted "unwritten READ simply falls back"
    reasoning corrected; ARTIFACTS_DIR redocumented as local-only
  - `adapters/factory.py` — Jobs now receive both Secrets (Tavily and artifact storage)
  - `deploy/helm/` — `artifactStorage` + `garage` values stanzas, both ConfigMaps,
    `secret-artifact-storage.yaml`, `garage.yaml` (StatefulSet + Service + ConfigMap),
    two `_helpers.tpl` helpers, Deployment `envFrom`, ✚ `values.schema.json`
    (`additionalProperties: false` rejected the new stanzas), ✚ `README.md` operator section
  - tests: `test_artifact_ports.py` (9), `test_sigv4.py` (9), `test_s3_artifact_store.py` (11),
    `test_artifact_spill_is_store_agnostic.py` (5), `test_artifact_storage_selection.py` (16),
    `test_deploy_time_chart_contract.py` (14)
- **Commits:**
  - f9c3f795 refactor(screamingface-engine): split artifact storage into writer and reader ports
  - 1d8f4ef1 feat(screamingface-engine): store spilled results in S3-compatible object storage
  - (this) feat(screamingface-engine): provision object storage and fail loudly on mismatch
- **Gates:** ALL GREEN — 1989 passed, 5 skipped, coverage 93.40% (floor 80); ruff check + format,
  pyright, layering. `helm template` renders in filesystem and s3+garage modes; `helm lint` clean.
  Final run used the documented `--skip-append-only` (deviation 3).
- **Deviations:**
  1. **`artifacts.py` header corrected in iteration 1, not 3.** The plan scheduled all comment
     fixes for iteration 3, but iteration 1 rewrites that header while moving the module —
     committing a known-false statement in order to fix it two commits later is worse.
  2. **`write_text` added to the `ArtifactWriter` port.** A PRIOR test (`test_runner.py:469`)
     calls it on the value `result_delivery_from_env` returns. Retyping that return to the port
     made pyright fail. Fixed in the PORT rather than the test, so no prior test was touched.
  3. **One prior test modified, with owner approval** (2026-08-21):
     `test_catalog_wiring.py::test_no_setting_holds_an_aigateway_credential` pins the set of
     secret-shaped `Settings` fields as a deliberate tripwire. Three names were added
     (`artifact_s3_access_key`, `artifact_s3_secret_key`, `artifact_s3_secret_name`) with the
     provenance and blast radius of each recorded inline. The App must hold the S3 secret to
     sign its own GETs when streaming artifacts back, so a name-only reference cannot work the
     way it does for Tavily. No assertion was weakened; the tripwire still fires on the next
     addition.
  4. **Extra hardening not in the plan:** a blank `URL4_CLOUD_ARTIFACTS_DIR` used to become
     `Path("")` — the working directory — silently relocating the store. Now normalised to the
     default in `Settings`, and the chart omits the key rather than rendering an empty value.
  5. **A second unrendered `DEPLOY_TIME` member surfaced:** the new chart contract test caught
     `URL4_RUNNER_CONFIG`, which is also declared Helm-owned and set by nobody. Its fallback is
     a path the image guarantees, so it is genuinely safe — allowlisted with that reason rather
     than papered over.
  6. **AWS SigV4 vectors:** the constants recalled from memory were wrong (one was from a
     different AWS example). The implementation independently produced the correct signature, and
     the TEST DATA was corrected against AWS's published `aws-sig-v4-test-suite` `get-vanilla`
     files, whose provenance is now recorded in the test.

## Iteration 4 — the deployment configures itself (owner requirement, 2026-08-21)

Owner: bundled Garage, **no manual commands — everything configured automatically.** This
retired known-limitation 2 below rather than documenting it.

Verified against Garage's docs before designing (the SigV4 episode earlier in this unit is why):

- `garage server` gained `--single-node`, `--default-access-key` and `--default-bucket` in
  **v2.3.0**. Confirmed the `dxflrs/garage:v2.3.0` tag exists in the registry (v2.3.1 / v2.4.0 do
  not), so the image floor is real and pinned.
- **My `key import` assumption was WRONG** — the CLI has no documented way to supply your own key
  id and secret. The v2.3.0 env-var path replaced that idea entirely.
- Garage's layout guide states that repeating `layout apply --version N` can leave a cluster
  **inconsistent**, and the version must be exactly one past the current. That is worse than the
  "just fails" risk originally recorded, and it is decisive against a hook that re-runs on every
  upgrade. `--single-node` removes the operation instead.

Implementation:
- `secret-artifact-storage.yaml` now holds BOTH halves of the pair and GENERATES them when unset,
  in Garage's own formats (`GK` + 24 hex; 64 hex), reusing the existing `lookup` pattern so an
  upgrade never rotates them.
- The access key moved out of both ConfigMaps into that Secret — it must be stable, and `lookup`
  only works against an object the chart owns.
- `garage.yaml` gains the three flags and maps the Secret to `GARAGE_DEFAULT_*`.
- `values.schema.json`: the `accessKey`-required rule was REMOVED; requiring it would forbid the
  fully-automatic path.
- Tests: the three flags are present, `GARAGE_DEFAULT_*` reads the same Secret keys the engine
  reads, and the pinned image is ≥ v2.3.0.

Verified: `helm template` with `backend=s3 garage.enabled=true` and **no credentials supplied**
renders 12 documents; the generated pair reaches all three consumers from one Secret.

✚ Also documented a limitation found while explaining the design, not while writing it: the
adapter uses **path-style** addressing, which excludes real AWS S3 (virtual-hosted-style) and
Azure Blob (not S3-compatible at all). Recorded in `s3.py` and the chart README.

## Known limitations (carried, not fixed)

1. **Object expiry depends on a bucket lifecycle rule.** `S3ArtifactStore.sweep` is a deliberate
   no-op: listing objects needs query-string signing, which would push the signer past the
   PUT/GET bound spec D5 sets on it. A bucket configured without a lifecycle rule never expires
   artifacts, and nothing in the App will notice. Documented in the chart README and in the code.
   **This is now the only operational gap in the bundled path** — worth its own ticket.
2. **Path-style addressing only** — fine for Garage/MinIO/SeaweedFS/Ceph/R2, likely broken against
   real AWS S3, impossible for Azure Blob. Choosing the style per endpoint is the fix if needed.
3. **Not exercised against a live cluster.** The engine side is fully covered by tests and the
   chart is verified to render, but the Garage manifests and the end-to-end round trip on real
   pods still need the owner's live-run check (cheap repro: force a spill with
   `URL4_CLOUD_RESULT_INLINE_CAP_BYTES=1024`). Two things to watch first: whether
   `--default-access-key` + `--default-bucket` also GRANT the key access to the bucket (the docs
   do not say so explicitly; if not, the first PUT 403s), and whether Garage accepts a
   caller-supplied key in these formats.
