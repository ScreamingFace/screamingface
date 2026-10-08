# MuSiQue-Ans

[MuSiQue: Multihop Questions via Single-hop Question Composition](https://aclanthology.org/2022.tacl-1.31/)
(Trivedi, Balasubramanian, Khot, Sabharwal — TACL 2022). 2,417 answerable multi-hop questions
from the **dev** split (the test split's answers are withheld). Each question chains 2 to 4
facts, each fact sits in a different paragraph, and the model is given 17 to 20 numbered
paragraphs, most of them decoys chosen to look relevant.

This is a **local Task** (OME-1513): an eval we author in inspect's shape — dataset loader,
scorer, one `@task` — and feed to the same importer that imports inspect_evals. It is not in
inspect_evals; the Benchmark it produces is ours (`origin="screamingface"`).

## Dataset

The dev file `musique_ans_v1.0_dev.jsonl` from the `dgslibisey/MuSiQue` mirror at commit
`c8f4f8c9`, sha256-checked before a byte is parsed. The authors publish only a Google Drive
zip, whose dev file the mirror's is byte-identical to. CC BY 4.0.

## The prompt

One user message: every paragraph as `[idx] Title` + text, in the dataset's own order and
numbering, then the question, then the instruction to end the reply with two lines:

```
Supporting paragraphs: <the numbers of the paragraphs you used, comma-separated>
Answer: <the answer, in as few words as possible>
```

The paper's models were fine-tuned, so there is no official prompt to copy; the wording is ours.
The paragraph numbers are the dataset's `idx` because support F1 compares what the model cites
with the gold `is_supporting` idx.

## Scoring

Three scorers, three Named Scores, computed by the paper's own code copied verbatim into
`vendor/` (StonyBrookNLP/musique@922ac98f; `test_local_task_musique_vendor.py` pins each file's
upstream sha256):

| Named Score | What it is | Headline? |
|---|---|---|
| `musique_answer_f1` | best token F1 of the committed answer over the gold answer and its aliases | yes |
| `musique_answer_em` | exact match (0 or 1) after the paper's normalisation | no |
| `musique_support_f1` | set F1 of the cited paragraph numbers against the gold supporting ones | no |

The reply reader takes the **last** `Answer:` and `Supporting paragraphs:` in the reply (a model
may reason aloud first), tolerates markdown around the label, and grades a reply with no label
as a whole (answer = the whole reply, support = empty) rather than dropping it.

## Baselines

- Human answer F1 0.78 on 125 sampled questions (paper, Table 3).
- Best published answer F1 0.692 — Beam Retrieval, a fine-tuned retrieval pipeline on the test
  split (NAACL 2024), not a prompted model on dev. Our runs sit beside it, not on the same scale.

## Draft Feedback

Off (`with_check_surface=False`), per the MuSiQue spec's decision D14: not needed for launch,
and the import lane's feedback would expose token F1 as a closeness signal over a small pool
of candidate spans.

## Identity

The Benchmark revision hashes the Case Digest, the Task reference, the Hub pin **and the
sha256 of every `.py` file in this package** (`task_source=…`). Editing `musique.py` or
anything under `vendor/` is a new Benchmark: update the literal in
`tests/unit/inspect/test_published_revisions.py` and say why in the PR.

## Running it locally

```sh
# import (two clean-room replays + the two rows; already done — re-run only to re-seal)
uv run python -m screamingface_engine_inspect.importer \
    screamingface_engine_inspect.local_tasks.musique.musique:musique --key musique
# prepare the bundle
uv run python -m screamingface_engine.benchmarks.prepare --root /tmp/assets --bundle musique
```

On a developer Mac the Hub client may stall mid-file; `HF_HUB_DISABLE_XET=1` fixes it. See
`docs/adding-an-imported-benchmark.md`, "Importing a local Task".
