# OME-929 — Implementation plan

Spec: `docs/spec/2026-08-21-OME-929-artifact-blob-handoff.md`
Stack: `screamingface-engine` (single landing — D4 means no SDK change, so no epic split)
Ledger: `docs/work/2026-08-21-OME-929-artifact-blob-handoff.md`

Three SDLC iterations, three commits, one PR. Each iteration is independently green; the bug's
acceptance test lands in iteration 2 and the deployment wiring in iteration 3.

## Layout

`artifacts.py` becomes a package. `__init__.py` re-exports, and **`ArtifactStore` survives as an
alias for `FilesystemArtifactStore`** — there are 24 call sites and 4 test modules referencing
that name, and tests are append-only, so the name must not move.

```
src/screamingface_engine/artifacts/
  __init__.py      re-exports; ArtifactStore = FilesystemArtifactStore
  ports.py         ArtifactWriter, ArtifactReader, ArtifactContent, LocalFile, RemoteStream
  filesystem.py    FilesystemArtifactStore  (today's behaviour, moved verbatim)
  s3.py            S3ArtifactStore
  sigv4.py         the signer — pure functions, no I/O
```

Precondition to verify first: `.claude/scripts/check_layering.py` must permit this placement
(it enforces that concrete adapters stay out of `url4.streaming`). Confirm before writing code.

---

## Iteration 1 — extract the ports (no behaviour change)

**RED**
- `RemoteStream` content renders as a `StreamingResponse` with the right length; `LocalFile`
  renders as a `FileResponse`. Fails: neither type exists.
- `FilesystemArtifactStore` structurally satisfies `ArtifactWriter` and `ArtifactReader`.

**GREEN**
- Add `ports.py`; move the store into `filesystem.py` unchanged; add `content()` returning
  `LocalFile`; keep `path_for` (14 callers) delegating to it.
- `rest/artifacts.py` matches on `ArtifactContent` — `FileResponse` for `LocalFile` (this is
  what keeps `test_a_range_request_does_not_consume_the_artifact` passing unmodified),
  `StreamingResponse` for `RemoteStream`.

**Invariant to hold:** every one of the existing artifact tests passes untouched.

Commit: `refactor(screamingface-engine): split artifact storage into writer and reader ports`

---

## Iteration 2 — the S3 adapter, and the test that proves the bug

**RED**
- **SigV4 signer** against AWS's published `aws-sig-v4-test-suite` vectors: canonical request,
  string-to-sign, signing key derivation, `Authorization` header. Pure functions, table-driven.
- `S3ArtifactStore` round-trip (`write_bytes` → `content`) against a fake S3 built on
  `httpx.MockTransport` — asserting the request it *actually* sends: `PUT /{bucket}/{id}`,
  `x-amz-content-sha256` equal to the artifact id, a valid `Authorization`.
- **The acceptance test for the bug (spec §6.1):** a writer and a reader constructed as two
  independent instances sharing no filesystem round-trip an over-cap result. Parametrised over
  both adapters: it **fails** for `FilesystemArtifactStore` on separate roots with the ticket's
  404, and **passes** for `S3ArtifactStore`. This is the coverage gap that let the bug ship.
- Cap boundary at `cap-1` / `cap` / `cap+1` (spec §6.3): the first two inline, the third spills.
- Error paths: 403 from a bad signature, 404 for a missing object → `None` (not an exception),
  a truncated upload surfaces rather than minting a ticket for absent content.

**GREEN**
- `sigv4.py`, then `s3.py`.

**Ordering invariant to pin with its own test:** the upload completes **before** the terminal
result frame is published. Otherwise a client can redeem a ticket for an object that does not
exist yet — the same 404 with a race instead of a misconfiguration behind it.

Commit: `feat(screamingface-engine): store spilled results in S3-compatible object storage`

---

## Iteration 3 — deployment wiring and loud failure

**RED**
- **The `DEPLOY_TIME` contract test (spec §6.2):** walk `job_env.DEPLOY_TIME` and assert the
  rendered runner-env ConfigMap carries every name, with an explicit allowlist for the
  genuinely optional ones (`TAVILY_API_KEY`). Fails today — this is the test that would have
  caught OME-929 the day OME-892 landed.
- **Startup guard (spec §6.4):** runner backend `k8s`/`jetstream` with absent or unusable S3
  config → the App refuses to start and the Runner fails its first write, each naming the
  missing setting. Never a fetch-time 404.
- Selection is derived (spec §4.3): `inprocess`/`memory` resolve to filesystem, `k8s`/
  `jetstream` to S3, and no configuration can pair `k8s` with filesystem.

**GREEN**
- Garage template + `values.yaml` stanza (default-disabled, mirroring the NATS subchart
  pattern) + PVC (RWO is sufficient — one blob pod).
- Render the S3 settings into `configmap-runner-env.yaml` (Runner) and `configmap.yaml` (App);
  credentials via a Secret with `envFrom`, following the `TAVILY_API_KEY` precedent.
- Wire selection through `adapters/factory.py`; `Settings` gains the S3 fields.

**Also in this iteration** (spec §6.7) — the stale comments, which actively misled the original
investigation:
- `artifacts.py` header — "`delete` (after a successful fetch)" and "sweep at app startup"
  (it is startup **and** periodic)
- `job_env.py:242` — "deleted on fetch, swept by TTL"
- `app.py:104` — "artifacts are deleted on fetch, so the only leak source is …"
- `job_env.py:305` — the inverted "an unwritten READ simply falls back" reasoning (spec §2)

Commit: `feat(screamingface-engine): provision object storage for artifacts and fail loudly on mismatch`

---

## Verification

- `uv run .claude/scripts/run_gates.py screamingface-engine` green after each iteration.
- `helm template` the engine chart with Garage enabled and disabled; assert the rendered
  ConfigMaps agree with `DEPLOY_TIME` (this is what the §6.2 test automates).
- Manual end-to-end against the deployed pods is the owner's check — force a spill with
  `URL4_CLOUD_RESULT_INLINE_CAP_BYTES=1024` and confirm a full-size result round-trips,
  verified against the ticket's `size_bytes` + `sha256`.

## Risks

| Risk | Mitigation |
|---|---|
| Hand-rolled SigV4 is wrong | Signed against AWS's published vectors; fails closed (we sign, Garage verifies). Bound: no multipart, no presigning — else take a real client (spec D5). |
| Converting `artifacts.py` to a package breaks 24 call sites | `ArtifactStore` alias retained; the full existing suite is the regression gate. |
| Garage operational unfamiliarity | Default-disabled in the chart; `inprocess` never touches it, so local development is unaffected. |
| App streams ~3 MiB per redemption | Accepted (D4). Single-consumer, once per run, few runs/hour. Presigned URLs remain the escape hatch behind the port. |
