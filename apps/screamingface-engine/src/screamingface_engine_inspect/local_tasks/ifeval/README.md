# IFEval

[Instruction-Following Evaluation for Large Language Models](https://arxiv.org/abs/2311.07911)
(Zhou et al., 2023). 541 prompts, each carrying one to several instructions a program can check
("no commas", "at least 300 words", "wrap the answer in quotes"), graded by deterministic code with
no judge.

This is a **local Task** (OME-1527): the hand-built `benchmarks/ifeval/` folder rewritten in
inspect's shape (dataset loader, scorer, whole-run metric, one `@task`) and fed to the same
importer that imports inspect_evals. It keeps its id, `ifeval`, and is ours
(`origin="screamingface"`). inspect_evals has an `ifeval` too; it is not used, because its metric
is not the published headline, its integer argument keys come back as `"0"` through JSON, it serves
official key 2785 unpatched, and it grades keys 1122 and 1129 against a random letter.

## Dataset

`google/IFEval` at `966cd895` (Apache-2.0), all 541 rows in dataset order. Each row is checked
against the official file vendored with the checker (`vendor/data/input_data.jsonl`): the
instruction ids and arguments must match, and the official prompt wins where the two differ.
That happens on exactly one row, official key 2785, whose Hub prompt asks for "at least one
placeholder" while its own arguments require 3; any other difference refuses the build.

**Case ids are positions 1..541**, no longer the official keys (owner decision, OME-1527). Case
`N` is row `N` of the pinned split, which is also row `N` of the official file; for example
official key 1000 is Case 1, 1069 is Case 10, 2785 is Case 340.

## The prompt

The Candidate is sent the prompt untouched, as one user message: the bytes equal the hand-built
Benchmark's for all 541 Cases (compared at import, and pinned by `test_local_task_ifeval.py`).
The instructions and their arguments ride the Sample metadata (private Grading Material),
arguments as a list parallel to the ids, with the Hub's padding `None`s dropped.

## Scoring

`instruction_following` runs the vendored checker (`grading.py`, moved unchanged from the folder)
over the reply, strictly and loosely (the loose pass also tries the reply with markdown asterisks
and its first or last line removed, as the paper does). Each Case gets one dict Score, the paper's
four numbers in its published order, the first being the Case score:

| Named Score | per Case | over the run |
|---|---|---|
| `prompt_level_strict_accuracy` | 1 if every instruction is met strictly | share of such Cases (**the headline**) |
| `inst_level_strict_accuracy` | share of the Case's instructions met strictly | **pooled** over the run's instructions |
| `prompt_level_loose_accuracy` | 1 if every instruction is met loosely | share of such Cases |
| `inst_level_loose_accuracy` | share met loosely | **pooled** over the run's instructions |

The row's whole-run metric `ifeval_accuracy` computes the run column. Instruction-level accuracy
is pooled, never a mean of Case fractions: Case A meeting 1 of 1 instruction and Case B 0 of 3 is
1 of 4 = 0.25, where the Case mean would say 0.5. The metric's numbers fill the Named Score
columns and are also published as run metrics under the hand-built keys
(`inst_level_strict_accuracy`, `prompt_level_loose_accuracy`, `inst_level_loose_accuracy`,
`pass_rate`), so a Report reads the same numbers as before. All are rounded to 4 places.

**One deliberate difference from the official checker** (owner decision 2026-08-10, kept from the
hand-built Benchmark): the two rows whose `letter_frequency` letter is not a-z (official keys 1122
`#` and 1129 `!`) are graded against that literal character, where the official checker replaces
it with a random letter. `test_local_task_ifeval_parity.py` proves the checker equals the official
fork on the other 539 rows.

## Draft Feedback

IFEval is the one Benchmark that offers Draft Feedback (owner decision, `OWNER_ALLOWED_DRAFT_FEEDBACK`):
the Corrective Loop checks each draft mid-run, free, with this same scorer. The scorer writes what
the hand-built route sent under `Score.metadata["draft_feedback"]`: `satisfaction`, the unrounded
share of instructions met strictly, and `feedback`, "The answer failed these requirements: "
followed by the checker's own description of each failed instruction, joined by " | " (empty when
the draft passes). In a Corrective Loop those words go into the next round's prompt, so they are
byte for byte the hand-built route's (pinned by `test_local_task_ifeval.py`). Nothing in them is
hidden: every instruction is stated in the prompt.

## The Report

Thinner than the hand-built Benchmark's, as for the other moved Benchmarks: one Check per Case,
whose evidence carries each instruction's id, description, strict and loose verdict, and the
Draft Feedback; no Check per instruction. A Case the checker could not grade fails as
`scorer_error` (the hand-built Benchmark said `ifeval_checker_failed`).

## Identity

The fingerprint hashes the Case Digest (which seals every prompt and every instruction set), the
Task reference, the Hub pin, the nltk corpus the checker reads (punkt and punkt_tab, sealed at
import and downloaded at every image build, since the grading job has no network), the Named
Scores, the whole-run metric and its headline key, the Draft Feedback flag, and the sha256 of
every `.py` file in this package, the vendored checker included (`task_source=…`). ifeval keeps the hand-built Benchmark's id (OME-1527). Editing any of them moves only the fingerprint: `tests/unit/inspect/test_benchmark_fingerprints.py`
goes red and the Benchmark keeps publishing its hand-set `published_revision` (OME-1610).
Whether that id moves too is the owner's call, under [Changing a Benchmark's published revision](../../../../docs/adding-an-imported-benchmark.md#changing-a-benchmarks-published-revision). Citations live in this README rather than in
the `.py` headers for that reason.

## Running it locally

```sh
# import (two clean-room replays + the two rows; already done — re-run only to re-seal)
HF_HUB_DISABLE_XET=1 uv run --extra benchmarks python -m screamingface_engine_inspect.importer \
    screamingface_engine_inspect.local_tasks.ifeval.ifeval:ifeval --key ifeval \
    --no-answer-key --keep-sample-metadata \
    --whole-run-metric honour --whole-run-headline prompt_level_strict_accuracy \
    --nltk-resource punkt --nltk-resource punkt_tab
# prepare the bundle
uv run --extra benchmarks python -m screamingface_engine.benchmarks.prepare \
    --root /tmp/assets --bundle ifeval
```
