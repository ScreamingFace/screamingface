---
ticket: OME-1970
stack: screamingface-engine
status: done
started: 2026-11-26
finished: 2026-11-26
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
this one and ruled the published revision HOLDS (26 Nov: no stored runs on this Benchmark; on
27 Nov, after one entry reached the board, re-ruled as a named exception: same pixels, only the
file format changed).

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
  refused; a picture under both limits but over 30,000 patches of 32 px (each side rounded
  up) is refused.
- A header the reader cannot parse is left to the signature check (prior fake-byte tests stay).
- labbench2: a listed Case is re-encoded to lossless WebP with identical pixels and fits; a
  listed Case already under the floor, or with a different dataset id, makes the build refuse;
  an unlisted Case is untouched (same bytes, same path).

## Acceptance

- Every picture in the 12 published picture Benchmarks passes the new check except HLE Case 250
  (fixed by OME-1970 PR 1, which must merge first).
- `labbench2_figqa2_img` reseals on linux/amd64 with only Cases 4 and 82 changed.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `picture_size.py` (a new module: the header-only size
  reader, kept out of `picture_input.py`), the CHANGELOG entry, the OME-1970 task mirror and the
  test-change approval `.claude/test-change-approvals/OME-1970.json`.
- **Commits:** e6ab83422 — feat(screamingface-engine): refuse a picture over the hosts' floor at
  seal time; fit labbench2_figqa2_img's two figures as lossless WebP; then this ledger commit.
- **Gates:** relevant tests only: 291 passed (`test_picture_cases.py`,
  `test_local_task_lab_bench_2.py`, `test_lab_bench_2_rows.py`, `test_benchmark_fingerprints.py`,
  `test_published_revisions.py`, `test_local_task_enigmaeval.py`,
  `test_judge_reads_the_sample_input.py`, `test_inspect_task_replay_benchmarks.py`,
  `test_parked_result_review_fixes.py`, `test_picture_case_limits_fit_the_gateway.py`) + 14 passed
  (MMMU, MathVista, MacBench, ZeroBench picture capture suites); ruff + pyright clean on the
  touched files; append-only check green with the approval. Outside checks: the header reader
  equals Pillow's size on all 5,837 sealed pictures of the 12 published picture Benchmarks
  (674 JPEG, 5,143 PNG, 16 WebP, 4 GIF; 0 mismatches, 0 unreadable). Re-seal on linux/amd64:
  case_digest e0bd1dbc…, case_set_digest 060e620b…; only Cases 4 and 82 differ from the
  2026-11-04 seal.
- **Review fixes (2026-11-27):** the third limit first counted pixels (30,720,000), which sealed
  7985 × 3847 (30,250 patches, refused by GPT); it now counts GPT's patches, each side rounded
  up, pinned by 14950 × 2780 → 40,716, GPT's own number. A patch rescan of the 5,837 sealed
  pictures finds only HLE Case 250 (HLE Diamond Case 35) over, fixed by PR 1, and none the pixel
  rule missed; the next largest is 24,920. The WebP fit now decodes its output and refuses a
  pixel change (a recoloured transparent pixel) or a 16-bit figure; Cases 4 and 82 pass and
  their WebP bytes are unchanged, so the digests hold. `shrunk_pictures.py` imports the 8000 px
  side from `picture_input.py` instead of defining it twice.
- **Deviations:** (1) The old PR 1 (labbench2 revision) is folded in, and its published revision
  holds instead of moving, the third named exception in `adding-an-imported-benchmark.md`
  (owner, 2026-11-27: same pixels, only the file format changed). (2) Lossless WebP instead of the plan's "Pillow
  optimize=True, then downscale": `optimize` saved 0.3%, a 5% downscale made the PNG bigger; WebP
  keeps every pixel and fits. (3) A patch limit (GPT's 30,000 patches of 32 px, each side
  rounded up) joins the planned bytes and side limits, from the 6 Nov HLE run errors. (4) A header the reader
  cannot parse is not refused: the seal never decoded pictures, and the prior tests seal 16-byte
  stand-ins. (5) The HLE picture over 8000 px is fixed in its own PR 1, which must merge first.
