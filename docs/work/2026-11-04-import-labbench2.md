---
ticket: OME-1733
stack: screamingface-engine
status: done
started: 2026-11-04
finished: 2026-11-04
---

# import-labbench2 — import LABBench2 FigQA2 and TableQA2 image as two Benchmarks (PR 2 of 2)

## Intent

Run the importer over PR 1's local Task (`local_tasks/lab_bench_2/`) and review its two rows,
so `labbench2_figqa2_img` (101 Cases) and `labbench2_tableqa2_img` (100) are served, judged by
Claude Sonnet 4.5, and listed in the picture notebook.

## Planned changes

- `prepare.py`, `benchmarks.py`: the importer's two TaskReplayCasesSpec and BenchmarkSpec rows,
  every TODO resolved (prose, tier, failure policy, provenance, judge, published revision).
- The five row tables in `apps/screamingface-engine/tests/unit/inspect/`, and a new
  `test_lab_bench_2_rows.py`.
- `.claude/test-change-approvals/OME-1733.json` for the edited prior tests.
- `packages/screamingface/scripts/build_notebooks.py`, the regenerated
  `examples/18_picture_benchmarks.ipynb`, its test, and the README's notebook line.

## Test plan

- New: the row pins the judge the scorer calls, and that judge is a gateway route; the Cases
  row reads the Task's pinned dataset behind the HF token, CC BY-SA, question kept for the
  judge; both rows are local Tasks counting an ungraded Case as 0.
- Prior tables gain the two rows; nothing else in them changes.

## Acceptance

- Importer exits 0 for both Tasks; both rows assemble and pass every registration check.
- The relevant test files green with the inspect extra and extra-less.

## Outcome

- **Actual files:** as planned.
- **Commits:** see the PR; one commit on `OME-1733-pr2-import-labbench2`.
- **Gates:** importer run 2026-11-04: `labbench2_figqa2_img` 101 Cases, Case Digest
  `14980c37ac16…`; `labbench2_tableqa2_img` 100 Cases, Case Digest `fee5764a5560…`; source pin
  `EdisonScientific/labbench2@3678e7e3`, licence cc-by-sa-4.0 read from the card. Fingerprints
  `b00a1a0f8bbdb9c4` and `e3365eafa0730f60`, set as the published revisions. Tests: the new
  rows file (6), the PR 1 Task file (32) and the five row tables, 809 passed with the inspect
  extra; every Engine test file that walks the row table (75 files) passed extra-less, as in CI
  (189 passed, 63 skipped); extra-less pyright clean on the touched files. Four catalogue
  tests in `test_benchmark_display_metadata.py` and `test_benchmark_protocol.py` fail with the
  inspect extra installed on PR 1's branch too, without these rows, and pass extra-less.
  Picture notebook: regenerated, `check_notebooks.py` exit 0, its test 4 passed.
- **Deviations:**
  - Row keys are `labbench2_*`, not `lab_bench_2_*`: the LAB-Bench v1 tests select their eight
    rows by the `lab_bench_` prefix, and the dataset spells its name `labbench2`.
  - **TableQA2 image is near saturation:** the paper's Figure 3 puts every model at 0.91-0.95
    without tools, so its tier is "easy". The ticket assumed both image subsets unsaturated
    from inspect_evals' FigQA2-only report. Flagged to the owner; the row ships as decided.
  - The frontier scores are read from Figure 3's pixels (the paper prints no table): FigQA2
    image 0.614 and TableQA2 image 0.94, GPT 5.2 Pro, no tools. The same reading gives GPT 5.2
    0.565 on FigQA2 image, where inspect_evals' register quotes the paper at 0.564.
- **Owner verify:** the paid smoke on both Benchmarks after merge
  (`screamingface-paid-benchmark-smoke.yml`, benchmarks `labbench2_figqa2_img,labbench2_tableqa2_img`);
  the notebook's two LABBench2 cells on the local stack with `HF_TOKEN`, then on dev once its
  chart pin moves past the merge.
