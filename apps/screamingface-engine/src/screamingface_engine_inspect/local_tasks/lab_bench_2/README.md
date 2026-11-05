# LABBench2 FigQA2 image and TableQA2 image

[LABBench2](https://arxiv.org/abs/2604.09554) (Laurent et al., 2026) is the successor to
LAB-Bench, from the same authors: about 1,900 biology research tasks in 15 subsets. This
package covers the two subsets that are one picture plus a question, the shape a single-shot
Benchmark can serve:

| Task | Config | Cases | The picture |
|---|---|---|---|
| `lab_bench_2_figqa2_img` | `figqa2-img` | 101 | one figure from a biology paper, `figure.png` |
| `lab_bench_2_tableqa2_img` | `tableqa2-img` | 100 | one table from a biology paper, `table.png` |

This is a **local Task** (OME-1733): inspect_evals lists LABBench2 only as an
[external eval](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/register/lab_bench_2),
whose code is not in the pinned `inspect-evals` package. The `pdf` and `retrieve` variants of
FigQA2 and TableQA2, and the other 13 subsets, are out of scope: they hand the model a PDF or
need tools.

## Cases

[`EdisonScientific/labbench2`](https://huggingface.co/datasets/EdisonScientific/labbench2)
at `3678e7e3`, gated (accept its terms once; the build reads it with `HF_TOKEN`). Case `k` is
the `k`-th row of the config, in file order; the dataset's own id rides the Case metadata.

Each row names a folder in the authors' public bucket, `labbench2-data-public`, holding one
PNG. `figures.py` lists the folder through the bucket's JSON API, downloads the file into the
import's own cache (`INSPECT_EVALS_CACHE_DIR/lab_bench_2/…`), and checks it against the
bucket's md5. The importer then seals the picture inside the Case, so nothing is fetched at
run time. The figures are not a recorded Case Source (our own urllib, as GDPval's reference
files): the Case Digest is their pin, and a figure the authors replace fails the next build.
Largest Case with its picture inline: 5.53 MB (FigQA2), under the 8 MB Case limit.

## The prompt

The authors' file mode, from their harness at
[`0cabab27`](https://github.com/EdisonScientific/labbench2/tree/0cabab27f6a23a5bc060a4699205709f1be7e93f)
(`vendor/labbench2.py`): one user message, the question, then

```
Attached files:
- figure.png

Use only the exact base filenames above. Copy them exactly, including case and extension. Do not rename them or use full paths.
```

then the picture. No system message, no generation settings, no tools.

## Scoring

The authors' exact-match judge prompt (`vendor/labbench2.py`, byte for byte), filled with the
question text the Candidate saw, the ideal answer and the answer as given. The judge is
`openrouter/anthropic/claude-sonnet-4.5`, the default grader of both the authors' harness and
the inspect port, at temperature 0. The verdict is the reply's last `result` line, read by the
inspect port's own pattern (`vendor/lab_bench_port.py`).

- correct → 1; incorrect or unsure → 0 (the authors' `LLMJudgeEvaluator`);
- an empty answer → 0, with no judge call (the authors' "No output provided");
- a reply with no verdict is redrawn, twice at most; a third fails the Case by name, and the
  Benchmark counts it 0, as the authors' evaluator scores any judge failure 0.0.

Benchmark score is the mean over the Cases run.

## Named deviations

- **No response schema.** The authors and the port ask the judge for a JSON
  `{rationale, result}` object. Our judge provider sends only the row's pinned params, so
  every reply is read by the port's fallback, the `result` line their prompt asks for.
- **A refusal counts 0, not unscored.** The inspect port leaves a Case unscored after three
  content-filtered judge replies; the authors' harness, which this Benchmark follows, scores it
  0.0.
- **The authors' current harness, not the port's copy.** The port at
  [`081864a`](https://github.com/Generality-Labs/lab-bench/tree/081864af494b180ecf6aae3f7333e384c0d227af/src/lab_bench_2)
  predates two of the authors' changes: the exact-match prompt's rule for an answer that is
  not a number (2026-10-07) and the "Attached files" lines (2026-10-15). Its file mode sends
  "In your answer, refer to files using only their base names (not full paths)." instead.

## Licence

CC BY-SA 4.0, the dataset card and the authors' harness (owner decision on OME-1733,
2026-10-28, on LAB-Bench v1's terms). The figures and tables come from published papers whose
own terms are not stated. `vendor/labbench2.py` is a verbatim excerpt of the CC BY-SA harness
and stays under that licence; `vendor/lab_bench_port.py` is MIT.

## Identity

The fingerprint hashes everything that defines these Benchmarks, the sha256 of every `.py`
file in this package included (`task_source=…`), `vendor/` too. Editing any of it moves the
fingerprint: `tests/unit/inspect/test_benchmark_fingerprints.py` goes red, and the Benchmark
keeps its hand-set `published_revision`. Whether that id moves too is the owner's call, under
[Changing a Benchmark's published revision](../../../../docs/adding-an-imported-benchmark.md#changing-a-benchmarks-published-revision).
