"""Bake the ContractEval (CUAD test) assets: the public questions and the private gold spans.

    <out>/cases.json          [{id, input}]                 — public, the Candidate-facing text
    <out>/answers/<id>.json   {source_id, title, question,  — private, read by aggregate.py
                               gold_spans, is_positive}       and the check endpoint

INVARIANT: `cases.json` carries NO gold span. It is the Candidate-facing input and the grader is
pure substring containment, so a leaked span would not merely hint at the answer — it would BE
the answer, pasted into the prompt. The dataset is public on HF; this boundary keeps the ENGINE
from serving the key.

CUAD row shape: `id` · `title` (contract) · `context` (full contract text) · `question` (one of
41 clause categories) · `answers: {text: [...], answer_start: [...]}`. An empty `answers.text`
means no clause of that category exists — 2,938 of the 4,182 rows (70.3%).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.contracteval.pins import (
    DATASET,
    DATASET_REVISION,
    DATASET_SPLIT,
    MAX_CONTEXT_TOKENS,
)
from screamingface_engine.benchmarks.contracteval.prompts import render_case_input
from screamingface_engine.benchmarks.deployment import BenchmarkAssetPreparationError

# WHY 4 and not a tokenizer: `tiktoken` is not an engine dependency and this guard exists to
# fail a build, not to bill anyone. Measured over all 4,182 real contexts the true ratio is 4.75
# chars/token, so dividing by 4 OVER-estimates the token count — the conservative direction for
# a tripwire. See pins.MAX_CONTEXT_TOKENS.
_CHARS_PER_TOKEN = 4


class PrepareError(BenchmarkAssetPreparationError):
    """One ContractEval row could not be baked — the build stops rather than shipping it."""


def _text(value: object, case_id: int, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PrepareError(f"case {case_id}: {field} must be non-empty text")
    return value


def _gold_spans(row: dict[str, Any], case_id: int) -> list[str]:
    answers = row.get("answers")
    spans = answers.get("text") if isinstance(answers, dict) else None
    if spans is None or isinstance(spans, str):
        raise PrepareError(f"case {case_id}: answers.text must be a list of gold spans")
    collected: list[str] = []
    for span in spans:
        if not isinstance(span, str) or not span.strip():
            raise PrepareError(f"case {case_id}: every gold span must be non-empty text")
        collected.append(span)
    return collected


def case_records(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, Any]]:
    """Validate the pinned rows into public Cases and the private answer key."""

    cases: list[dict[str, Any]] = []
    answers: dict[int, Any] = {}
    for case_id, row in enumerate(rows, start=1):
        context = _text(row.get("context"), case_id, "context")
        question = _text(row.get("question"), case_id, "question")
        if len(context) // _CHARS_PER_TOKEN > MAX_CONTEXT_TOKENS:
            raise PrepareError(
                f"case {case_id}: contract exceeds the context budget of "
                f"{MAX_CONTEXT_TOKENS} tokens — refusing to bake it rather than truncate"
            )
        spans = _gold_spans(row, case_id)
        cases.append({"id": case_id, "input": render_case_input(context, question)})
        answers[case_id] = {
            "source_id": row.get("id"),
            "title": row.get("title"),
            "question": question,
            "gold_spans": spans,
            # WHY stored rather than derived downstream: the confusion matrix needs a Case's
            # polarity even when the Candidate's reply is missing, and `gold_spans == []` is the
            # same shape a corrupt record would present.
            "is_positive": bool(spans),
        }
    return cases, answers


def emit(rows: list[dict[str, Any]], out: Path) -> dict[str, Any]:
    """Write the public cases file and the private answer key. Returns the audit summary."""

    cases, answers = case_records(rows)
    answers_dir = out / "answers"
    answers_dir.mkdir(parents=True, exist_ok=True)
    for case_id, record in answers.items():
        (answers_dir / f"{case_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    (out / "cases.json").write_text(
        json.dumps(cases, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    positives = sum(1 for record in answers.values() if record["is_positive"])
    return {
        "cases": len(cases),
        # WHY published: the negative share is what tells a reader an always-abstaining model
        # scores ~70% accuracy here, which is why F1 and not accuracy is the headline (spec D-2).
        "positive_cases": positives,
        "negative_cases": len(cases) - positives,
        "dataset_revision": DATASET_REVISION,
        "split": DATASET_SPLIT,
        "out": str(out),
    }


def load_rows() -> list[dict[str, Any]]:
    """Load the pinned split. Build time only — ``datasets`` is not an engine dependency."""

    try:
        datasets_mod = importlib.import_module("datasets")
    except ModuleNotFoundError as exc:
        raise PrepareError(
            "the `datasets` package is required to prepare a benchmark — "
            "`uv pip install datasets` in the build environment"
        ) from exc
    loaded = datasets_mod.load_dataset(DATASET, revision=DATASET_REVISION, split=DATASET_SPLIT)
    return [dict(row) for row in loaded]


def prepare(out: Path) -> dict[str, Any]:
    """Bake the ContractEval assets into ``out``, returning the audit summary."""

    return emit(load_rows(), out)


__all__ = ["PrepareError", "case_records", "emit", "load_rows", "prepare"]
