---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-29
finished: 2026-10-29   # round 1; round 2 (local mode) 2026-10-30
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
- Round 2 (2026-10-30) — local in-process mode binds the same reader:
  - `adapters/inprocess.py` — `InProcessJobRunner(run_binding=...)`: an injected
    `env -> context manager`, built eagerly in `schedule` from THIS run's env (topic + verified
    identity) and entered inside the run's own task, around `lifecycle.run`. Injected, so the
    adapter stays engine-free (layering).
  - `runner/blob_reader.py` — `bound_run_blob_reader` resolves eagerly (returns the binding
    rather than a generator context), so a half-configured S3 store refuses at `schedule`, the
    same moment `build_executor`'s own artifact wiring refuses it.
  - `local.py` — `create_local_app` passes `bound_run_blob_reader` as the runner's binding.

## Test plan

- `tests/unit/test_runner_blob_reader.py` (new):
  - a ref-only attachment the App stored for this run is served through the bound reader;
  - a corrupt stored copy → permanent `x.blob_digest_mismatch`, message names the digest only;
  - a digest stored for another tenant → `source_not_found`;
  - no run scope in the env → nothing bound, ref-only → `source_not_found` (today's behaviour);
  - `_run_process` binds the reader for the run (scripted run reads a stored blob).
- `tests/unit/test_local_blob_reader.py` (new, round 2):
  - an in-process run reads a ref-only file the App stored for its topic + caller;
  - another tenant's stored digest stays `source_not_found` in an in-process run;
  - the binding is the run task's only — the scheduling caller's context binds nothing;
  - a half-configured S3 store refuses at `schedule` and admits no run;
  - `create_local_app` wires the binding into its in-process runner.

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
  - Round 1 residual (local mode's in-process runner bound no reader) — closed in round 2.
- **Round 2 (2026-10-30) — local in-process mode:**
  - **Actual files:** `adapters/inprocess.py` (`run_binding` param + `RunBinding` alias +
    `_run_within`), `runner/blob_reader.py` (`bound_run_blob_reader` resolves eagerly, returns
    the binding), `local.py` (`_run_blob_binding`, passed as the runner's `run_binding`), new
    test `tests/unit/test_local_blob_reader.py` (5 tests). No prior test changed.
  - **Gates:** `run_gates.py screamingface-engine --base cfb178b30` (merge-base with
    `origin/main`) — ALL GATES GREEN.
  - **Deviations:**
    - The tenant and run id come from the in-process run's own env (`_env`: `TOPIC` + the
      request's verified identity) — the same keys a Runner process reads, so no new plumbing.
    - The store is resolved from the run env (`URL4_CLOUD_ARTIFACT*`), not by sharing
      `app.state.blob_store`: one code path with the Runner; local `run_env` and `Settings`
      read the same variables, as the result spill path already assumes. An explicit
      `create_local_app(settings=...)` whose `artifacts_dir` differs from the env would split
      them — same pre-existing caveat as the spill store.
    - `bound_run_blob_reader` is now eager (resolve at call, bind at enter) so a half-configured
      S3 store refuses at `schedule` rather than killing a task before `lifecycle.run` can
      publish a terminal frame. Runner behaviour unchanged (call and enter are one `with`).
    - `run_binding` is injected (not imported) so `adapters/inprocess.py` stays an engine-free
      shared leaf; the import crossing sits in `local.py` beside `build_executor`'s.

### Owner decisions (2026-10-30)

- Local mode builds its blob store from the run env, the same way the Runner does. It does not use
  `app.state.blob_store`. Known caveat, shared with the result spill store: `create_local_app(settings=...)`
  with an `artifacts_dir` different from the env points the two at different directories.
- Known gap, deferred: the C8 local node route (`_install_local_node`, the shared-world eval path) does not
  go through `InProcessJobRunner`, so it binds no blob reader and attachments fail there. Fix it when an
  eval needs attachments on that path; name the gap in the PR body.
