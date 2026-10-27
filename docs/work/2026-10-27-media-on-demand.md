---
ticket: OME-1271
stack: screamingface-engine
status: in_progress
started: 2026-10-27
finished:
---

# media-on-demand — park each Case's pictures and files at finish, so a researcher can open one

## Intent

PR 5 of OME-1271. Since #1558 a Case Result shows each picture or file as a placeholder (type,
size, sha256), so a researcher has no way to see the picture the model saw. The client-facing
engine process can't read the Benchmark files (they ship only in the Runner image), but it
already serves the result store at `GET /artifacts/{id}`, and that store names every item by the
sha256 of its bytes: the same value the placeholder carries. So when a run finishes, the Runner
parks each distinct picture and file in that store; the SDK (next PR) fetches one by its
placeholder's sha256 and checks the bytes. Items live 48 hours (`artifact_ttl_s`), refreshed
each time a run parks the same bytes again. Design agreed with the owner on 2026-10-27.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/media_parking.py` (new): the
  run-scoped parker (read the Case, decode each picture or file, write it once per run) and its
  binding.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/candidate_input.py`: one helper,
  `media_bytes`, so parking and `media_placeholder` decode a part the same way.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/aggregation.py`:
  `finalize_candidate_result` parks each Case's media before the echo.
- `apps/screamingface-engine/src/screamingface_engine/runner/operation_capture.py` and
  `runner/main.py`: bind the parker for each run, with the run's result store.
- Tests: `tests/unit/test_media_parking.py` (new), appended cases in
  `tests/unit/test_benchmark_aggregation.py` and the operation-capture tests.

## Test plan

- A picture Case parks the decoded bytes, named by their sha256, equal to the placeholder's.
- The same picture in two Cases, or for two Candidates of one run, is written once.
- A text Case, a refused Case, and an unbound run park nothing.
- A store that fails to write is logged and the run's result is unaffected.
- Through `finalize_candidate_result`: the parked id equals the echoed placeholder's sha256.
- The run wrapper binds the parker with the run's store for every step.
- The App's reader serves a parked picture's bytes by that sha256.

## Acceptance

- After a picture run, `GET /artifacts/<placeholder sha256>` returns that picture's bytes.
- Text-only runs write nothing extra to the store.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
