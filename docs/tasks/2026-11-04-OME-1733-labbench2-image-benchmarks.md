---
id: OME-1733
linear_url: https://linear.app/openmined/issue/OME-1733/add-labbench2-figqa2-and-tableqa2-image-mode-as-benchmarks
status: done
type: feature
priority: low
labels: [screamingface-engine, human, design-session]
parent: OME-1330
created: 2026-10-26
closed: 2026-11-04
---

# Add LABBench2 FigQA2 and TableQA2 image mode as Benchmarks

LABBench2 (arXiv 2604.09554) is the successor to LAB-Bench. Its two picture subsets, FigQA2
image (101 questions) and TableQA2 image (100), are one figure or table plus a question, graded
by an LLM judge against the authors' ideal answer. inspect_evals lists LABBench2 only as an
external eval, so it lands as a local Task.

- 2026-10-28: owner decisions: image variants only; CC BY-SA 4.0 accepted on LAB-Bench v1's
  terms, figures' terms unknown; HF gate accepted on the CI token's account; dataset pinned at
  `3678e7e`; "unsure" scores 0, the authors' rule.
- 2026-11-04: un-blocked (pictures in Cases landed with HLE, MMMU, MathVista). Judge:
  `openrouter/anthropic/claude-sonnet-4.5`, the authors' and the inspect port's default.
- 2026-11-04, PR 1 of 2: the local Task `local_tasks/lab_bench_2/`, following the authors'
  harness at `0cabab27`: their file-mode prompt and exact-match judge prompt vendored byte for
  byte, the inspect port's verdict reader vendored, the figures fetched from the authors'
  public bucket into the replay cache with an md5 check. A real build gave 101 and 100 Cases,
  every picture sealed, largest Case 5.53 MB.
- 2026-11-04, PR 2 of 2: `labbench2_figqa2_img` (101 Cases, revision `b00a1a0f8bbdb9c4`, tier
  hard) and `labbench2_tableqa2_img` (100 Cases, revision `e3365eafa0730f60`, tier easy)
  imported at `3678e7e`, licence CC BY-SA 4.0, policy `withhold`, judged by Claude Sonnet 4.5 at
  temperature 0. Frontier scores read from the paper's Figure 3: 0.614 and 0.94 (GPT 5.2 Pro, no
  tools), so TableQA2 image is near saturation. Both join the picture notebook. This closes the
  ticket; the paid smoke is the owner's to press.
