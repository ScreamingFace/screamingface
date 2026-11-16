---
id: OME-1863
linear_url: https://linear.app/openmined/issue/OME-1863/add-hle-diamond-as-its-own-benchmark
status: done
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1330
created: 2026-11-10
closed: 2026-11-16
---

# Add HLE-Diamond as its own Benchmark

[HLE-Diamond](https://huggingface.co/datasets/cais/hle-diamond) is the HLE authors' cleaned
successor to Humanity's Last Exam: 1,000 questions, 500 reasoning and 500 knowledge. `hle`
cannot stand in for it: 397 Diamond questions are not in `hle`, and of the 603 shared, 80 have a
corrected answer and 124 a reworded question (counted at both pinned revisions). One PR adds
`hle_diamond`, a local Task around inspect_evals' `hle` over `cais/hle-diamond@04eeb7ef`, judged
exactly as `hle` is. `hle` does not change.

- 2026-11-16: owner decisions in session: the dataset card's "do not publicly re-share" ask is
  accepted as for `hle` (the frozen Cases ride in the benchmark image); the Benchmark publishes
  the overall score and the stated confidence only, no per-half scores.
- 2026-11-16: in build, the proposed `hle_diamond_` Case-id prefix was dropped: the Engine
  numbers Cases 1..N per Benchmark and the Case Digest leaves inspect's Sample id out, so the
  prefix protected nothing. The Task's one line of its own keeps `partition` as Grading
  Material.
- 2026-11-16: the importer refused a local Task whose scorer lives in inspect_evals; one rule
  now lets a local Task name an inspect_evals scorer (an inspect_evals Task keeps the old
  rule). Frontier score set to the top no-tools row of the authors' table, 74.3% (Claude Fable
  5.2); the ticket's 59.9% is GPT-6 Astra's row in that same table.
- 2026-11-16: all 272 Diamond pictures checked: each declares the type its bytes are, so no
  picture-type fix is needed beyond inspect_evals' own.
- 2026-11-16: PR opened as a draft on branch `OME-1863-hle-diamond`, with the Fidelity Record
  (`not-comparable`, the judge differs; everything else measured matches).
- Owner steps left: confirm the test-change approvals manifest, a paid 2-Case smoke run, and
  the dev chart pin bump.
