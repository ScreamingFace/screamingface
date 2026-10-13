# ARC-AGI-2

[ARC-AGI-2: A New Challenge for Frontier AI Reasoning Systems](https://arxiv.org/abs/2505.11831)
(Chollet, Knoop, Kamradt, Landers, Pinkard — 2025). The **public evaluation** set: 120 visual
puzzles. Each task shows 2 to 6 example pairs of coloured grids (rows of the digits 0–9, up to
30×30) and asks for the output grid of one or more new inputs, the **test grids**: 75 tasks have
one, 43 have two, 2 have three, so 167 in all.

This is a **local Task** (OME-1476): an eval we author in inspect's shape and feed to the same
importer that imports inspect_evals. inspect_evals' `arc` is a different benchmark (the AI2
Reasoning Challenge); the Benchmark this produces is ours (`origin="screamingface"`).

## Dataset

GitHub's zip of [arcprize/ARC-AGI-2](https://github.com/arcprize/ARC-AGI-2) at commit
`f3283f72`, fetched with `inspect_ai.util.download`, which refuses it unless its sha256 is
`c3f9f697…d49f`; only `data/evaluation/*.json` is read, and the loader refuses any count but
120 tasks and 167 test grids. Apache-2.0. The semi-private and private sets the ARC Prize scores
on are not public.

## The prompt

One user message per test grid: the ARC Prize harness's own template
(`arcprize/arc-agi-benchmarking@9e2828fb`, `prompts/system_prompt.txt`) with every example pair
and the test input written as JSON. It is restated in `arc_agi_2.py` rather than copied, because
the template file ends with no newline and the repo's whitespace hooks would add one; the test
pins the template's sha256 to the upstream file's and one fixture prompt to the upstream builder's
own output.

## Scoring

| Step | Rule | Where |
|---|---|---|
| Read a reply | a `\boxed{…}` grid, else the last bracketed JSON in the reply | the harness's `parse_and_validate_json`, copied verbatim into `vendor/` |
| Mark one Attempt | 1 if the grid equals the answer cell for cell, else 0; no grid → 0, "no grid found" | `arc_exact_match` |
| Mark one test grid | two Attempts, solved if either is (`epochs=Epochs(2, "max")`) | the Engine's Attempt fold (OME-1458) |
| Headline Score | mean over tasks of grids solved / grids in the task | `arc_per_task_accuracy`, which RESTATES the harness's `scoring.py:122-127` and `:160-234` (not a copy) |

**When our number equals the harness's:** on a run whose Report shows no failed Case and no
"no grid found" Attempt, the arithmetic is the harness's to the last digit
(`test_the_headline_is_the_harness_score_on_the_same_replies`). Otherwise:

- **No grid in a reply:** the harness asks the model again to extract one (OpenAI-style and
  Anthropic models) or re-asks the question; we score the Attempt 0. A Named Deviation.
- **A failed Attempt** (e.g. a reply cut at the token cap) fails the whole Case in the Engine, so
  the grid counts 0 even if the other Attempt was right; the harness credits the other Attempt.
- **A task whose every grid failed** drops out of our mean; the harness counts it 0.

Answers run to 2,760 characters before any reasoning: give the Candidate a high `max_tokens`.

## Baselines

- Human: 0.75, **per task** — on the final ARC-AGI-2 tasks, the share of human attempts that
  solved a task, averaged by task (paper, §5). A task attempt counts only if all its test pairs
  are right, so it is stricter than our per-grid partial credit. The paper also gives 66% per
  test pair (pooled over attempts) and 62% on the pre-curation candidate pairs.
- Frontier: 0.925, GPT-5.6 Sol at maximum reasoning, ARC Prize-verified on the **semi-private**
  set (August 2026). A different 120 tasks, calibrated to the same human difficulty: our
  public-eval runs sit beside it, not on the same scale.

## Identity

The Benchmark revision hashes the Case Digest, the Task reference, the two
Attempts with their `max` reducer, the honoured metric **and the sha256 of every `.py` file in
this package** (`task_source=…`). Editing `arc_agi_2.py` or `vendor/` is a new Benchmark: update
the literal in `tests/unit/inspect/test_published_revisions.py` and say why in the PR.

## Running it locally

```sh
# import (two clean-room replays + the two rows; already done — re-run only to re-seal)
uv run python -m screamingface_engine_inspect.importer \
    screamingface_engine_inspect.local_tasks.arc_agi_2.arc_agi_2:arc_agi_2 --key arc_agi_2 \
    --whole-run-metric honour
# prepare the bundle
uv run python -m screamingface_engine.benchmarks.prepare --root /tmp/assets --bundle arc_agi_2
```

334 Candidate Invocations per Candidate (167 grids × 2 Attempts). See
`docs/adding-an-imported-benchmark.md`, "Importing a local Task".
