---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-29
finished: 2026-10-29
---

# runner-blob-reader — bind the run blob store's reader into every Runner run

## Intent

Epic OME-1529 (image and PDF inputs). #1588 (OME-1545) reads a ref-only attachment through a
run-scoped `BlobReader` bound with `bound_blob_reader`; #1603 (OME-1540) builds that reader from
the run env (`blob_reader_from_env`). Nothing bound one around a run, so every ref-only
attachment read as `source_not_found`, and the reader's `BlobDigestMismatch` (store corruption)
escaped the connector's `AttachmentPartError` mapping. This unit binds the reader for the run's
duration in the Runner and maps that corruption to the connector's permanent
`x.blob_digest_mismatch`, digest-only.

Base: `origin/OME-1545-engine-attachment-parts` with `origin/OME-1540-blob-store` merged in.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/runner/blob_reader.py` (new) —
  `bound_run_blob_reader(env)`: binds an adapter over `ScopedBlobReader` that turns
  `BlobDigestMismatch` into the connector's `x.blob_digest_mismatch`; binds nothing when the env
  names no run to scope blobs to.
- `runner/main.py` — `_run_process` enters it alongside `run_scope`.
- `world/attachment_parts.py` — expose the digest-mismatch error builder (one message, DRY).

## Test plan

- `tests/unit/test_runner_blob_reader.py` (new):
  - a ref-only attachment the App stored for this run is served through the bound reader;
  - a corrupt stored copy → permanent `x.blob_digest_mismatch`, message names the digest only;
  - a digest stored for another tenant → `source_not_found`;
  - no run scope in the env → nothing bound, ref-only → `source_not_found` (today's behaviour);
  - `_run_process` binds the reader for the run (scripted run reads a stored blob).

## Acceptance

- Ref-only attachments resolve through the run blob store on the Runner; corruption is a
  permanent `x.blob_digest_mismatch`; out-of-scope digests stay `source_not_found`.
- `run_gates.py screamingface-engine --base origin/main` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `runner/blob_reader.py` (new), `runner/main.py`,
  `world/attachment_parts.py` (`_digest_mismatch` → public `digest_mismatch`), new test
  `tests/unit/test_runner_blob_reader.py` (6 tests).
- **Commits:** see branch `runner-blob-reader` (single `feat(engine)` commit after the
  OME-1540 merge commit).
- **Gates:** `run_gates.py screamingface-engine --base <merge-base with origin/main>` — ALL GATES
  GREEN (append-only, ruff, format, pyright, layering, pytest + coverage). With
  `--base origin/main` the append-only check fails on `test_image_token_forwarding.py` and
  `test_picture_admission.py` showing as deleted: both landed on main after this branch's base
  (#1572, #1584); this branch never touched them. `origin/main` merges in cleanly.
- **Deviations:**
  - "No store configured" is read as "the env names no run to scope blobs to" (no topic, or a
    topic that is not a run id): on the Runner the store always resolves (filesystem default),
    and the existing `_run_process` tests use a non-run-id topic. A half-configured S3 store
    still raises.
  - The binding is built from `blob_scope_from_env` + `blob_store_from_env` rather than
    `blob_reader_from_env`, so only the scope's `ValueError` means "no run".
  - Residual: local mode's in-process runner (`adapters/inprocess.py`) binds no reader, so a
    ref-only attachment is still `source_not_found` there.
