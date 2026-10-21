# MedMCQA, the validation split

[MedMCQA: A Large-scale Multi-Subject Multi-Choice Dataset for Medical domain Question Answering](https://arxiv.org/abs/2203.14371)
(Pal et al., CHIL 2022). Four-option questions from Indian medical entrance exams (AIIMS and
NEET PG) across 21 subjects. 4,183 Cases.

This is a **local Task** (OME-1696) we wrote in inspect's shape: inspect_evals has no MedMCQA.

## Cases

The full validation split of [`openlifescienceai/medmcqa`](https://huggingface.co/datasets/openlifescienceai/medmcqa)
at commit `91c6572c`, file `data/validation-00000-of-00001.parquet`, sha256 `b768a1ea…`. The
loader refuses the file if its sha256 differs. Validation, not test, because the test split's
answers are withheld (its key is `-1`); LLM papers report on this split ("dev").

Each row becomes its question, its four options `opa`..`opd` lettered A to D in dataset order
(no shuffle), and the letter of the correct option (`cop` 0..3).

## Asking and scoring

inspect's standard `multiple_choice()` instruction (answer with `ANSWER: $LETTER`), and
inspect's `choice()` scorer against the key letter. No judge. Benchmark score is plain accuracy
over the Cases run.

Four rows repeat the correct option's text under a second letter (one, `0447b9a2`, has four
identical options). Grading is by letter, as on every published number, so picking the twin
scores 0. They stay in, because the published numbers count all 4,183.

## Licence

Apache-2.0, the dataset card's header at the pinned revision; its Licensing section is blank.
The authors' [GitHub repository](https://github.com/medmcqa/medmcqa) is MIT.
