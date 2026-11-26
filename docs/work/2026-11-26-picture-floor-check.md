---
ticket: OME-1970
stack: screamingface-engine
status: in_progress
started: 2026-11-26
finished:
---

# picture-floor-check — refuse a picture over the hosts' floor at seal time; fit labbench2_figqa2_img's two

## Intent

OpenRouter can serve any Claude call from Amazon Bedrock, which refuses a picture over 5 MiB of
base64 (measured live 24 and 26 Nov, OME-1971). Claude also refuses a picture side over 8000 px,
and GPT-6 Astra Pro / GPT-6.1 Terra Pro refuse a picture over 30,000 patches of 32 px. Today the
importer checks only the whole Case (8,000,000 bytes), so a sealed Case can pass or fail
depending on the host OpenRouter picks. This unit adds the per-picture floor to the seal
(OME-1970 Plan PR 2, decision 7), and in the same PR fits the only two published Cases over it,
`labbench2_figqa2_img` Cases 4 and 82, by re-encoding their PNGs as lossless WebP (same
pixels), so the image build keeps sealing that Benchmark. The owner folded the old PR 1 into
this one and ruled the published revision HOLDS (26 Nov: no stored runs on this Benchmark).

## Planned changes

- `src/screamingface_engine_inspect/picture_input.py`: `MAX_PICTURE_BASE64_BYTES`,
  `MAX_PICTURE_SIDE_PX`, a header-only size reader, the refusals; reverse the "no limit per
  picture" note.
- `src/screamingface_engine_inspect/local_tasks/lab_bench_2/lab_bench_2.py`: the two Cases
  named by Case number and dataset id; `_fitted_picture` → lossless WebP `data:` URI.
- `src/screamingface_engine_inspect/prepare.py`: the row's digests (linux/amd64 re-seal) and
  the deviation note; `tests/unit/inspect/test_benchmark_fingerprints.py` literal.
- Tests: `test_picture_cases.py` (new floor tests; two prior tests edited, manifest),
  `test_local_task_lab_bench_2.py` (new fit tests).
- LAB-Bench 2 README, Fidelity Record, CHANGELOG.

## Test plan

- A picture at 5,242,880 base64 bytes is sealed; one base64 quantum over is refused, naming
  the picture and both sizes.
- A picture whose header says 8000 px is sealed; 8001 px (each of PNG, JPEG, GIF, WebP) is
  refused; a picture under both limits but over 30,720,000 pixels is refused.
- A header the reader cannot parse is left to the signature check (prior fake-byte tests stay).
- labbench2: a listed Case is re-encoded to lossless WebP with identical pixels and fits; a
  listed Case already under the floor, or with a different dataset id, makes the build refuse;
  an unlisted Case is untouched (same bytes, same path).

## Acceptance

- Every picture in the 12 published picture Benchmarks passes the new check except HLE Case 250
  (fixed by OME-1970 PR 1, which must merge first).
- `labbench2_figqa2_img` reseals on linux/amd64 with only Cases 4 and 82 changed.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
