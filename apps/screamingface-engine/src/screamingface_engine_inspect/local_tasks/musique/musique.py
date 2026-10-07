# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai,
# huggingface_hub), absent in the default (extra-less) install the typecheck gate runs against;
# it is loaded only behind `inspect_available()`, like every other module in this package.
"""MuSiQue-Ans as a LOCAL inspect Task — our own eval in inspect's shape (OME-1513).

Think of it as writing the exam the way inspect_evals writes theirs, then handing it to the
same importer: a dataset loader that prints the question booklet, a scorer that marks one
reply, and one `@task` that binds them. No routes, no result envelope, no revision function —
the importer seals the Cases by digest and the plugin's shared serving path does the rest.

Execution order, as the importer and the Engine see it:

    1. `musique()` → `load_musique_dev()`: fetch the pinned dev file from the Hub mirror
       (commit pin + sha256, refused on mismatch), render each row into a Sample whose
       `input` is the exact Candidate-facing text (`CASE_TEMPLATE`), whose `target` is the
       answer plus its aliases, and whose `metadata` keeps the gold supporting paragraph
       numbers for the support scorer.
    2. the importer replays that twice in a clean child and seals the 2,417 Cases by digest;
       at build, `prepare` replays it once more and serves nothing unless the digest matches.
    3. at grading, the scorer adapter calls each scorer with the Candidate's reply:
       `extract_answer` / `extract_support` read the two committed lines (the LAST label
       wins), and the vendored paper code turns them into numbers — three scorers, three
       Named Scores, answer F1 the Headline.

INVARIANT: `CASE_TEMPLATE` and the paragraph rendering are Benchmark identity (they sit inside
the Case Digest); an edit is a new Benchmark, not a tweak. `tests/unit/inspect/
test_local_task_musique.py` pins the bytes.

INVARIANT: the numbers come from the paper's own scorer, copied verbatim into `vendor/`
(StonyBrookNLP/musique@922ac98f, CC BY 4.0); this module adds no normalisation of its own.

WHY no official prompt: the paper's models were fine-tuned, so the wording here is ours. The
reply ends with `Supporting paragraphs:` then `Answer:` so a model may reason first and still
commit a clean span; paragraphs show the dataset's own `idx` because support F1 compares the
numbers the model cites with the gold `is_supporting` idx.

References:
    - Paper: https://aclanthology.org/2022.tacl-1.31/
    - Reference harness: https://github.com/StonyBrookNLP/musique
    - Case Source: https://huggingface.co/datasets/dgslibisey/MuSiQue (dev file byte-identical
      to the authors' Google Drive zip)
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState, generate

from screamingface_engine_inspect.local_tasks.musique.vendor.answer import (
    compute_exact,
    compute_f1,
    metric_max_over_ground_truths,
)
from screamingface_engine_inspect.local_tasks.musique.vendor.support import SupportMetric

# ── pins (the hand-built PR's revision_inputs.py, minus the protocol/preparer revisions:
#    here the Case Digest and the scorer reference carry that identity) ──────────────────
DATASET = "dgslibisey/MuSiQue"
DATASET_REVISION = "c8f4f8c9465fb69d31a8eae894c3fd509c4ca321"
DATASET_FILE = "musique_ans_v1.0_dev.jsonl"
DATASET_SHA256 = "15fa63794d18a94ce12411aca6e2327e65b6e83b0b1490efab3f1962e48abf3b"

# ── the prompt (byte-identical to the hand-built PR's prompts.py) ─────────────────────
CASE_TEMPLATE = (
    "Answer the question using the numbered paragraphs below.\n"
    "\n"
    "{paragraphs}\n"
    "\n"
    "Question: {question}\n"
    "\n"
    "Think it through if that helps, then end your reply with these two lines, in this order:\n"
    "Supporting paragraphs: <the numbers of the paragraphs you used, comma-separated>\n"
    "Answer: <the answer, in as few words as possible>"
)
PARAGRAPH_TEMPLATE = "[{idx}] {title}\n{text}"
PARAGRAPH_SEPARATOR = "\n\n"


# ── dataset loader (bbeh's data.py) ───────────────────────────────────────────────────
def load_musique_dev() -> MemoryDataset:
    """Download the pinned dev file, refuse a wrong sha256, render each row into a Sample."""

    from huggingface_hub import hf_hub_download  # recorded by the importer's Case Source recorder

    path: str = hf_hub_download(
        repo_id=DATASET, filename=DATASET_FILE, revision=DATASET_REVISION, repo_type="dataset"
    )
    data: bytes = Path(path).read_bytes()
    actual: str = hashlib.sha256(data).hexdigest()
    if actual != DATASET_SHA256:
        raise ValueError(f"{DATASET_FILE} has sha256 {actual}, expected {DATASET_SHA256}")
    samples: list[Sample] = [
        _record_to_sample(json.loads(line)) for line in data.decode("utf-8").splitlines() if line
    ]
    return MemoryDataset(samples=samples, name="musique_ans_dev")


def _record_to_sample(row: dict[str, Any]) -> Sample:
    """One dev row → the Candidate-facing input, the answer key (answer + aliases), the support."""

    paragraphs: str = PARAGRAPH_SEPARATOR.join(
        PARAGRAPH_TEMPLATE.format(idx=p["idx"], title=p["title"], text=p["paragraph_text"])
        for p in row["paragraphs"]
    )
    return Sample(
        id=row["id"],
        input=CASE_TEMPLATE.format(paragraphs=paragraphs, question=row["question"]),
        # Target as a list: [answer, *aliases] — the official ground-truth order.
        target=[row["answer"], *row["answer_aliases"]],
        metadata={
            "supporting_idx": sorted(p["idx"] for p in row["paragraphs"] if p["is_supporting"]),
            "hop_type": row["id"].split("__", 1)[0],
        },
    )


# ── reply reader (the hand-built PR's answering.py, condensed) ───────────────────────
_ANSWER_LABEL = re.compile(re.escape("Answer:"), re.IGNORECASE)
_SUPPORT_LABEL = re.compile(re.escape("Supporting paragraphs:"), re.IGNORECASE)
_NUMBER = re.compile(r"[0-9]+")


def _committed_value(text: str, label: re.Pattern[str], *, stop: re.Pattern[str]) -> str | None:
    """The value after the LAST ``label`` (rest of line, else next non-empty line), or None."""

    hits = list(label.finditer(text))
    if not hits:
        return None
    rest: str = text[hits[-1].end() :]
    stop_hit = stop.search(rest)
    if stop_hit is not None:
        rest = rest[: stop_hit.start()]
    first, _, remainder = rest.partition("\n")
    lines: list[str] = [first, *remainder.splitlines()]
    value: str = next((line.strip() for line in lines if line.strip()), "")
    return value


def extract_answer(completion: str) -> str:
    value: str | None = _committed_value(completion, _ANSWER_LABEL, stop=_SUPPORT_LABEL)
    return completion.strip() if value is None else value


def extract_support(completion: str) -> list[int]:
    value: str | None = _committed_value(completion, _SUPPORT_LABEL, stop=_ANSWER_LABEL)
    return [] if value is None else sorted({int(n) for n in _NUMBER.findall(value)})


# ── scorers (bbeh's bbeh_scorer; three here because MuSiQue reports three numbers) ────
@scorer(metrics=[mean(), stderr()])
def musique_answer_f1() -> Scorer:
    """Headline: best token F1 of the committed answer over the answer and its aliases."""

    async def score(state: TaskState, target: Target) -> Score:
        answer: str = extract_answer(state.output.completion)
        ground_truths: Sequence[str] = list(target.target)
        f1: float = float(metric_max_over_ground_truths(compute_f1, answer, ground_truths))
        return Score(value=f1, answer=answer)

    return score


@scorer(metrics=[mean(), stderr()])
def musique_answer_em() -> Scorer:
    """Exact match (0 or 1) of the normalised committed answer against any ground truth."""

    async def score(state: TaskState, target: Target) -> Score:
        answer: str = extract_answer(state.output.completion)
        exact: int = int(metric_max_over_ground_truths(compute_exact, answer, list(target.target)))
        return Score(value=float(exact), answer=answer)

    return score


@scorer(metrics=[mean(), stderr()])
def musique_support_f1() -> Scorer:
    """Support F1: cited paragraph numbers against the gold `is_supporting` ones."""

    async def score(state: TaskState, target: Target) -> Score:
        predicted: list[int] = extract_support(state.output.completion)
        gold: list[int] = list(state.metadata.get("supporting_idx", []))
        metric: SupportMetric = SupportMetric()  # fresh: upstream accumulates across calls
        metric(predicted, gold)
        _, f1 = metric.get_metric()
        return Score(value=float(f1), answer=",".join(str(n) for n in predicted))

    return score


# ── the Task (bbeh's bbeh()) ─────────────────────────────────────────────────────────
@task
def musique() -> Task:
    """MuSiQue-Ans dev: 2,417 answerable multi-hop questions over 20 numbered paragraphs."""

    return Task(
        dataset=load_musique_dev(),
        solver=generate(),
        scorer=[musique_answer_f1(), musique_answer_em(), musique_support_f1()],
    )
