# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai,
# huggingface_hub), absent in the default (extra-less) install the typecheck gate runs against;
# it is loaded only behind `inspect_available()`, like every other module in this package.
"""FRAMES with the gold articles given, as a LOCAL inspect Task (OME-1481).

Think of it as an open-book exam: each question comes with the exact Wikipedia pages its
writers used, frozen as they read on 2024-09-19, and the examiner is the paper's own marking
sheet read out to our house Judge. A loader prints the booklet (articles, then the question),
a scorer has the Judge say TRUE or FALSE, and one `@task` binds them. This is the paper's
"Oracle" setting: nothing is searched.

Execution order, as the importer and the Engine see it:

    1. `frames_oracle()` → `load_frames()`: fetch three pinned files (the FRAMES questions
       file, and the snapshot's question and article files), refuse any whose sha256 differs,
       and join them by row index (`samples_from`), refusing a row whose prompt the snapshot
       was not built for. Each row becomes a Sample whose `input` is the Candidate's whole
       prompt (`CASE_TEMPLATE`), whose `target` is the gold answer and whose metadata keeps the
       bare question for the Judge.
    2. the importer replays that twice in a clean child and seals the Cases by digest, leaving
       out questions 77 and 141 by name (the row's `excluded_sample_ids`); at build, prepare
       replays it once more and serves nothing unless the digest matches.
    3. the Candidate answers once per Case. A prompt longer than its context window comes back
       from the provider as a 400, and that one Case fails (`aigateway_http_400`).
    4. at grading, `frames_judge` sends the Judge the paper's Figure 6 prompt with the
       question, the Candidate's whole reply and the gold answer; `Decision: TRUE` scores 1.0,
       `FALSE` 0.0. A reply with no decision is redrawn twice, then the Case fails as
       `judge_reply_invalid`, never scored. The headline is the mean: plain accuracy.

INVARIANT: `CASE_TEMPLATE` and the article rendering are Benchmark identity (inside the Case
Digest), and `JUDGE_TEMPLATE` is the paper's text (inside the Task source pin); an edit to
either is a new Benchmark. `tests/unit/inspect/test_local_task_frames.py` pins the bytes.

WHY our own Candidate prompt: the paper publishes no oracle template, only that the prompt
"includes the question along with all the ground truth Wikipedia articles". The articles come
first and the question last, so the model reads the evidence before the ask.

References:
    - Paper: https://arxiv.org/abs/2409.12941 (Krishna et al., 2024), Figure 6 for the judge
    - Questions: https://huggingface.co/datasets/google/frames-benchmark
    - Articles: https://huggingface.co/datasets/khoaguin/frames-wikipedia-2024-09-19 (each
      gold article at its last revision before 2024-09-19; its card lists what the text lacks)
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessage, ChatMessageSystem, ChatMessageUser, get_model
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState, generate

from screamingface_engine_inspect.judge_redraw import JudgedItem, judge_until_parsed

# ── pins ────────────────────────────────────────────────────────────────────────────────────
QUESTIONS_REPO = "google/frames-benchmark"
QUESTIONS_REVISION = "58d9fb6330f3ab1316d1eca12e5e8ef23dcc22ef"
QUESTIONS_FILE = "test.tsv"
QUESTIONS_SHA256 = "4255093c93b595b5b04c7c8dde290b48ec87d72ca0fb0b760d9dd02740d669ff"

SNAPSHOT_REPO = "khoaguin/frames-wikipedia-2024-09-19"
SNAPSHOT_REVISION = "6ada7fb7acfe0f1125b17337d1783b1f51ffd975"
SNAPSHOT_QUESTIONS_FILE = "questions.jsonl"
SNAPSHOT_QUESTIONS_SHA256 = "1a1a6f1d831039ed993fc2f787f671b3e06fa6a20ee200f307a48221d0e10541"
ARTICLES_FILE = "articles.jsonl"
ARTICLES_SHA256 = "c93063fcdc98c5acc755131df9a86ff8bb236982bd7812699a55100bdd89f1db"

#: The judge, as the scorer calls it through the gateway provider: the house judge every
#: judged Benchmark here pins. The paper graded with Gemini-Pro-1.5; the row's JudgeSpec pins
#: the same model as this default (benchmark identity), see its WHY note in `benchmarks.py`.
JUDGE_MODEL = "screamingface/openrouter/openai/gpt-5.4"

# ── the Candidate's prompt (ours: the paper publishes none) ─────────────────────────────────
CASE_TEMPLATE = (
    "Answer the question using the Wikipedia articles below.\n\n{articles}\n\nQuestion: {question}"
)
ARTICLE_TEMPLATE = "=== Article {number}: {title} ===\n{text}"
ARTICLE_SEPARATOR = "\n\n"

# ── the Judge's prompt: Figure 6, from the paper's LaTeX source (auto_rate_prompt.tex) ─────
JUDGE_SYSTEM = "You are a helpful assistant."
# WHY these exact bytes: the paper's figure is its only statement of the rater; each `\\` in
# its source is a line break here, its curly apostrophe and en dash are kept, and its
# <<question>>, <<LLM_response>> and <<ground_truth_answer>> slots are the three fields.
JUDGE_TEMPLATE = (
    "===Task===\n"
    "\n"
    "I need your help in evaluating an answer provided by an LLM against a ground truth answer. "
    "Your task is to determine if the ground truth answer is present in the LLM’s response. "
    "Please analyze the provided data and make a decision.\n"
    "===Instructions===\n"
    '1. Carefully compare the "Predicted Answer" with the "Ground Truth Answer".\n'
    "2. Consider the substance of the answers – look for equivalent information or correct "
    "answers. Do not focus on exact wording unless the exact wording is crucial to the meaning.\n"
    "3. Your final decision should be based on whether the meaning and the vital facts of the "
    '"Ground Truth Answer" are present in the "Predicted Answer:"\n'
    "\n"
    "===Input Data===\n"
    "- Question: {question}\n"
    "- Predicted Answer: {answer}\n"
    "- Ground Truth Answer: {target}\n"
    "\n"
    "===Output Format===\n"
    "Provide your final evaluation in the following format:\n"
    '"Explanation:" (How you made the decision?)\n'
    '"Decision:" ("TRUE" or "FALSE" )\n'
    "\n"
    "Please proceed with the evaluation."
)

#: The judge's labels, however it decorates them: `Decision: TRUE`, `**Decision:** FALSE`,
#: `"Decision:" ("TRUE")`. The verdict word must follow the label, so a TRUE in prose is
#: never read as the decision.
_DECISION = re.compile(r'decision["*_\s]*:["*_\s(]*(true|false)\b', re.IGNORECASE)
_DECISION_LABEL = re.compile(r'decision["*_\s]*:', re.IGNORECASE)
_EXPLANATION_LABEL = re.compile(r'explanation["*_\s]*:', re.IGNORECASE)
_EXPLANATION_EDGES = ' \t\r\n"*_'


# ── dataset loader ──────────────────────────────────────────────────────────────────────────
def load_frames() -> MemoryDataset:
    """Download the three pinned files, refuse a wrong sha256, join them into Samples."""

    from huggingface_hub import hf_hub_download  # recorded by the importer's Case Source recorder

    def pinned(repo: str, revision: str, filename: str, sha256: str) -> bytes:
        path: str = hf_hub_download(
            repo_id=repo, filename=filename, revision=revision, repo_type="dataset"
        )
        data: bytes = Path(path).read_bytes()
        actual: str = hashlib.sha256(data).hexdigest()
        if actual != sha256:
            raise ValueError(f"{repo}/{filename} has sha256 {actual}, expected {sha256}")
        return data

    samples: list[Sample] = samples_from(
        pinned(QUESTIONS_REPO, QUESTIONS_REVISION, QUESTIONS_FILE, QUESTIONS_SHA256),
        pinned(
            SNAPSHOT_REPO, SNAPSHOT_REVISION, SNAPSHOT_QUESTIONS_FILE, SNAPSHOT_QUESTIONS_SHA256
        ),
        pinned(SNAPSHOT_REPO, SNAPSHOT_REVISION, ARTICLES_FILE, ARTICLES_SHA256),
    )
    return MemoryDataset(samples=samples, name="frames_oracle")


def samples_from(questions: bytes, snapshot_questions: bytes, articles: bytes) -> list[Sample]:
    """Join the questions file to the snapshot by row index, one Sample per FRAMES row.

    INVARIANT: a row is joined only to the snapshot row built for its exact prompt (the
    snapshot records each prompt's sha256), and every article key it names must be in the
    snapshot; anything else is refused, never paired with the wrong articles.
    """

    # WHY the limit: one questions cell holds a long list of links, past csv's 128 KiB default.
    csv.field_size_limit(sys.maxsize)
    rows: list[dict[str, str]] = list(
        csv.DictReader(questions.decode("utf-8").splitlines(keepends=True), delimiter="\t")
    )
    links: list[dict[str, Any]] = [
        json.loads(line) for line in snapshot_questions.decode("utf-8").splitlines() if line
    ]
    by_key: dict[str, dict[str, Any]] = {
        row["key"]: row
        for row in (json.loads(line) for line in articles.decode("utf-8").splitlines() if line)
    }
    if len(rows) != len(links):
        raise ValueError(f"{len(rows)} questions but {len(links)} snapshot rows")
    samples: list[Sample] = []
    for row, link in zip(rows, links, strict=True):
        index: int = int(row[""])
        prompt: str = row["Prompt"]
        if link["index"] != index:
            raise ValueError(f"row {index}: the snapshot row is {link['index']}")
        if hashlib.sha256(prompt.encode("utf-8")).hexdigest() != link["prompt_sha256"]:
            raise ValueError(f"row {index}: the snapshot was built for another prompt")
        texts: list[tuple[str, str]] = []
        for key in link["articles"]:
            if key not in by_key:
                raise ValueError(f"row {index}: article {key} is not in the snapshot")
            texts.append((by_key[key]["title"], by_key[key]["text"]))
        missing: list[str] = [article["title"] for article in link["missing_articles"]]
        samples.append(
            record_to_sample(
                index, prompt, row["Answer"], texts, row["reasoning_types"], missing=missing
            )
        )
    return samples


def record_to_sample(
    index: int,
    question: str,
    answer: str,
    articles: Sequence[tuple[str, str]],
    reasoning_types: str,
    *,
    missing: Sequence[str],
) -> Sample:
    """One FRAMES row → the Candidate's prompt, the gold answer, and the Judge's question.

    ``articles`` are (title, text) in the row's link order. ``missing`` names gold articles
    deleted from Wikipedia before they could be frozen (row 540 keeps 19 of its 20).
    """

    rendered: str = ARTICLE_SEPARATOR.join(
        ARTICLE_TEMPLATE.format(number=number, title=title, text=text)
        for number, (title, text) in enumerate(articles, start=1)
    )
    return Sample(
        id=index,
        input=CASE_TEMPLATE.format(articles=rendered, question=question),
        target=answer,
        metadata={
            "question": question,
            "reasoning_types": reasoning_types,
            "missing_articles": list(missing),
        },
    )


# ── the Judge ───────────────────────────────────────────────────────────────────────────────
def judge_user_text(question: str, answer: str, target: str) -> str:
    """Figure 6 with its three slots filled; braces in the values reach the judge as written."""

    return JUDGE_TEMPLATE.format(question=question, answer=answer, target=target)


def parse_decision(reply: str) -> tuple[bool, str] | None:
    """The judge's verdict (True = TRUE) and its explanation, or None when it gave no decision.

    The LAST labelled decision wins, so a judge that corrects itself is read as corrected. The
    explanation is the text after the last ``Explanation:`` label before that decision, up to
    the next ``Decision:`` label; empty when the judge wrote none.
    """

    decisions: list[re.Match[str]] = list(_DECISION.finditer(reply))
    if not decisions:
        return None
    decision: re.Match[str] = decisions[-1]
    labels: list[re.Match[str]] = [
        label for label in _EXPLANATION_LABEL.finditer(reply) if label.end() <= decision.start()
    ]
    explanation: str = ""
    if labels:
        start: int = labels[-1].end()
        stop: re.Match[str] | None = _DECISION_LABEL.search(reply, start)
        end: int = decision.start() if stop is None else stop.start()
        explanation = reply[start:end].strip(_EXPLANATION_EDGES)
    return decision.group(1).upper() == "TRUE", explanation


@scorer(metrics=[mean(), stderr()])
def frames_judge(judge_model: str = JUDGE_MODEL) -> Scorer:
    """Grade one reply with the paper's auto-rater: TRUE scores 1.0, FALSE 0.0.

    The Judge sees the bare question, the Candidate's whole reply and the gold answer, never
    the articles: the paper's rater checks whether the gold answer's substance is in the reply.
    A reply with no decision is redrawn through :func:`judge_until_parsed` (twice at most,
    each a fresh sample outside the gateway cache); after that it raises
    ``JudgeReplyUnparseable``, which the scorer adapter turns into ``judge_reply_invalid``.

    Args:
        judge_model: the gateway judge, ``screamingface/<model>``; the row pins the same one.

    Returns:
        The inspect scorer. Its Score's value is 1.0 or 0.0, its explanation the judge's.

    Raises:
        KeyError: the Sample carries no question (a broken Case, never "nothing to ask").
    """

    async def score(state: TaskState, target: Target) -> Score:
        judge: Any = get_model(judge_model)
        prompt: list[ChatMessage] = [
            ChatMessageSystem(content=JUDGE_SYSTEM),
            ChatMessageUser(
                content=judge_user_text(
                    state.metadata["question"], state.output.completion, target.text
                )
            ),
        ]
        judged: JudgedItem[tuple[bool, str]] = await judge_until_parsed(
            judge, prompt, parse_decision, item=f"case {state.sample_id}"
        )
        correct, explanation = judged.verdict
        # The reasoning types ride the Check into the Report, so a run can be cut per type
        # (the paper's Figure 3).
        reasoning_types: object = state.metadata.get("reasoning_types")
        metadata: dict[str, Any] = {"judge_redraws": judged.redraws}
        if isinstance(reasoning_types, str):
            metadata["reasoning_types"] = reasoning_types
        return Score(value=1.0 if correct else 0.0, explanation=explanation, metadata=metadata)

    return score


# ── the Task ────────────────────────────────────────────────────────────────────────────────
@task
def frames_oracle() -> Task:
    """FRAMES, articles given: 824 questions, each with its gold Wikipedia articles pasted in."""

    return Task(dataset=load_frames(), solver=generate(), scorer=frames_judge())
