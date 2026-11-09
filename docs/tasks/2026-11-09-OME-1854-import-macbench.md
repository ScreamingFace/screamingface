---
id: OME-1854
linear_url: https://linear.app/openmined/issue/OME-1854/add-macbench-chemistry-and-materials-picture-questions-as-a-benchmark
status: done
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1330
created: 2026-11-09
closed: 2026-11-09
---

# Add MaCBench chemistry and materials picture questions as a Benchmark

MaCBench (arXiv 2411.16955, Alampara et al.) is 1,153 chemistry and materials science
questions in 34 subsets, each about one picture (a hand-drawn molecule, a crystal structure,
an adsorption isotherm, a spectrum, a patent plot, a lab photo). inspect_evals 0.20.0 ships it
as the task `macbench`; the importer replays it and writes `inspect-macbench`.

- 2026-11-09: imported by Task replay at the dataset's pinned revision `ca13e7af`
  (`--shuffle-seed 20260917 --letter-list-key --whole-run-metric mean`): 1,153 Cases, Case
  Digest `d265b015…`, one PNG per Case, largest Case 1,692,138 bytes, licence MIT (the card;
  evaluation-only terms, canary string). 779 multiple choice (19 with several right letters),
  374 numeric (146 with the dataset's own window, 228 on the 1% fallback). Published revision
  `f6cb6e028f58c0f2`, tier medium, policy withhold, no judge.
- Named Deviation: the eval's pinned scorer compares multi-letter answers as text, so
  `[ANSWER]C, A[/ANSWER]` against `A,C` scores 0 (chembench's bug, inspect_evals issue #2586,
  fix PR #2591); `named_deviations/macbench/macbench.py` grades the set of letters, numbers
  stay the eval's own `pattern_mae`; a tripwire test fails when the pin grades the set.
- Byte check: inspect's own `eval()` with `mockllm/model` over all 1,153 Samples matched every
  sent message to exactly one Case (bytes, media type, order) and its target and metadata to
  that Case's Grading Material; one flipped byte left exactly one Sample unmatched.
- Joins the picture notebook (`18_picture_benchmarks`, served on a Mac: no Pillow re-save).
  The paid smoke after merge is the owner's to press.
