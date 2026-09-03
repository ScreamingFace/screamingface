# OME-929 — Over-cap result artifacts must survive the Runner Job

Status: DECIDED 2026-08-21 (owner decisions recorded in §3). Supersedes the transport
recommendation in the Linear issue, which proposed HTTP upload to the App.

## 1. Problem

A Run whose serialized result exceeds the inline cap (1 MiB) spills to a content-addressed
artifact; the terminal frame carries only a claim ticket. On the hosted Engine the Runner is a
Kubernetes **Job** pod and the App is a **Deployment** pod. Each mounts its own `emptyDir` at
`/tmp` (`adapters/k8s.py:342,367`), and `URL4_CLOUD_ARTIFACTS_DIR` is set by **nothing** in the
chart — so both halves fall back to the same *pod-local* default path, which is two different
disks. The Runner writes ~3 MiB into a disk that dies with the Job; the client redeems the
ticket against the App and gets 404.

The artifact is not an accessory to the Report — it **is** the Report's payload.
`_decoded_result_body` (`packages/screamingface/.../_evaluation/results.py:44`) raises
`ExecutionError` on a `None` body, so a lost artifact yields **no Report at all**. Every
full-scale benchmark run on the hosted Engine therefore produces nothing the user can see,
after the entire cost of the run is paid (a full DRACO 3-pass run is 11,902 model calls).

Confirmed by the owner 2026-08-21: the failure occurs in the deployed pod environment. The
Linear issue's "confirm hosted vs local" precondition is satisfied; local (`inprocess`) shares
the directory by construction and is genuinely unaffected.

## 2. Why it shipped — the coverage gap

`ARTIFACTS_DIR` is a member of `job_env.DEPLOY_TIME`, whose docstring states "Helm owns these
end-to-end." Helm owns nothing of the sort. `tests/unit/test_job_env_contract.py` asserts only
the **negative** direction — that the App must not write a deploy-time name (lines 159-166) —
and never that the chart *does* write them. `job_env.py:305` records the reasoning that
permitted this: *"the direction that breaks silently is an unread WRITE, not an unwritten READ
(which simply falls back)."*

That reasoning is inverted for this variable. The fallback is a pod-local temp directory: it is
not a benign default but the exact misconfiguration that loses the result. A test walking
`DEPLOY_TIME` against the rendered chart would have failed the day OME-892 landed. Closing this
gap is in scope and is transport-independent.

## 3. Decisions (owner, 2026-08-21)

| # | Decision | Rationale |
|---|---|---|
| D1 | **Object storage**, not a shared RWX volume and not HTTP-upload-to-App | Hosted is AKS; the repo has no RWX StorageClass and no inter-pod shared-volume precedent, so a shared volume needs a platform action outside this repo. Object storage also keeps run completion independent of App liveness. |
| D2 | **Self-hosted S3 in our own charts** — Garage | Removes object storage's two stated costs (cloud credentials, cloud coupling). Garage is a single static binary, no external dependencies, sized for exactly this workload. |
| D3 | **Local/`inprocess` keeps the filesystem store** | One process, one disk: the existing behaviour is correct there and stays byte-identical. |
| D4 | **The App streams artifacts through**; no presigned-URL redirect | Keeps `GET /artifacts/{id}` unchanged, so the SDK's existing size + sha256 verification and retry survive untouched and the blob store stays cluster-internal. Also keeps this a single-landing unit (no SDK change, no epic split). |
| D5 | **`httpx` + hand-rolled SigV4**; no new dependency | Bounded to PUT and GET of one object — no multipart, and D4 means no presigning. We sign, Garage verifies, so a signer bug fails **closed** (our request is rejected; nothing forged is accepted). The payload sha256 is already computed — it *is* the artifact id. Testable against AWS's published SigV4 vectors. **Bound: if the signer ever needs multipart or presigning, revisit and take a real S3 client.** |
| D6 | **The deployment configures itself — no bootstrap Job, no operator commands** (owner, 2026-08-21) | See §4.5. |

### 4.5 Self-configuration (D6)

Garage ≥ 2.3.0 provides three `garage server` flags that remove the bootstrap entirely:
`--single-node` (creates its own layout), `--default-access-key` (adopts
`GARAGE_DEFAULT_ACCESS_KEY`/`_SECRET_KEY`), `--default-bucket` (creates `GARAGE_DEFAULT_BUCKET`).
The chart generates a stable key pair when none is supplied — reused across upgrades via `lookup`,
the pattern already used for the JWT secret — and Garage **adopts** it.

WHY adopt rather than mint: a `post-install` hook running `garage key create` makes Garage produce
the credential, which the chart must then discover and write back into a Secret. That needs
`create secrets` RBAC and makes the chart two-phase, so `helm template` no longer describes the
result. Adopting a chart-stated key keeps the data flowing one way and the chart declarative.

WHY not script the layout: Garage's own operations guide warns that repeating
`layout apply --version N` can leave a cluster **inconsistent**, and that the version must be
exactly one past the current one — which is what a hook re-running on every `helm upgrade` gets
wrong. `--single-node` removes the operation instead of automating it.

INVARIANT: one Secret, three consumers — the App (Deployment `envFrom`), every Runner Job
(`envFrom.secretRef`), and Garage itself (`env` → `GARAGE_DEFAULT_*`). The store therefore cannot
hold a key the engine does not present.

INVARIANT: the pair is NOT rotated by an upgrade. Garage adopts a default key only on first boot,
so minting a new pair later would leave the engine signing with credentials the store has never
seen — a 403 on every artifact, which reads as a code bug rather than a config change.

## 4. Design

### 4.1 Ports (core; core never imports an adapter)

The single `ArtifactStore` class exists only because writer and reader shared a filesystem.
Split it along the boundary that is now real:

- `ArtifactWriter` — Runner side: `write_bytes(encoded: bytes) -> ResultArtifact`
- `ArtifactReader` — App side: `content(artifact_id) -> ArtifactContent | None`,
  `delete(artifact_id)`, `sweep(ttl_seconds, *, now=None) -> int`

`ArtifactContent` is a value object, not an HTTP concept, and is deliberately a union because
the two storage kinds genuinely differ in what they can offer:

```python
@dataclass(frozen=True)
class LocalFile:      path: Path                                    # supports HTTP Range
@dataclass(frozen=True)
class RemoteStream:   stream: AsyncIterator[bytes]; size_bytes: int  # does not
ArtifactContent = LocalFile | RemoteStream
```

Flattening these into one shape would either lose Range on the local path or fake it on the
remote one. `rest/artifacts.py` renders `LocalFile` with `FileResponse` (as today, preserving
`test_a_range_request_does_not_consume_the_artifact`) and `RemoteStream` with
`StreamingResponse`.

### 4.2 Adapters

- `FilesystemArtifactStore` — today's `ArtifactStore` behaviour verbatim, implementing both
  ports. The default for `inprocess`/`memory` (D3).
- `S3ArtifactStore` — `httpx` + SigV4 (D5), implementing both ports against one bucket.
  Selected for `k8s`/`jetstream`.

### 4.3 Selection — derived, not independently configurable

Backend selection **derives** from the runner backend rather than taking its own env var. An
independent setting would admit exactly one new misconfiguration: `runner=k8s` with a
filesystem store, which is today's bug wearing a config flag. Deriving makes that state
unrepresentable.

### 4.4 Fail loudly, at startup

INVARIANT: a writer/reader storage mismatch must surface **before** any run, never at fetch
time minutes after the spend. When the runner backend is `k8s`/`jetstream` and the S3
configuration is absent or unusable, the App refuses to start and the Runner fails its first
write — with a message naming the missing setting.

## 5. Out of scope

- Multi-replica App support (D4 keeps the App on the read path; it is already pinned to one
  replica for the in-process subscriber gate).
- Presigned URLs, multipart upload, object-storage replication/versioning tiers. The object is
  single-consumer, fetched once, dead within 48 h — "survives until the client fetches it" is
  the entire durability requirement.
- Migrating existing on-disk artifacts. They are ≤48 h hand-offs; the TTL sweeper drains them.
- The `draco-3pass` board and DRACO cache-seed work.

## 6. Acceptance

1. A test with writer and reader on **separate storage roots** round-trips an over-cap result.
   It must fail before the fix with the ticket's 404 and pass after.
2. A test asserts every `job_env.DEPLOY_TIME` name is rendered by the chart (or is explicitly
   declared optional), closing the §2 gap.
3. Cap-boundary tests at `cap-1`, `cap`, `cap+1` bytes pin inline-vs-spill.
4. A storage mismatch fails at startup or first write, not at fetch.
5. `inprocess`/local behaviour is byte-identical to today.
6. Existing artifact tests unchanged and green (tests are append-only).
7. The stale "deleted on fetch" comments corrected (`artifacts.py` header, `job_env.py:242`,
   `app.py:104`), and the inverted `job_env.py:305` reasoning corrected.
8. `uv run .claude/scripts/run_gates.py screamingface-engine` green.
