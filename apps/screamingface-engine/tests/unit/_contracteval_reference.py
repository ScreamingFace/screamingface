"""ContractEval's reference grading logic, transcribed verbatim — TEST MATERIAL ONLY.

DO NOT EDIT to make a test pass. This file exists so that our grading can be proved equal to
the paper's, and it is only evidence while it stays a faithful copy. If our board must diverge,
the divergence belongs in the spec as a named deviation and in a test that asserts it — never
in a quiet edit here.

Source: https://github.com/olivialiu121/ContractEval (MIT), fetched 2026-09-09 at commit
f2de74479bb067a13da2fd034972eec6905563b2 — the frozen blobs the line references below point at:
https://github.com/olivialiu121/ContractEval/blob/f2de74479bb067a13da2fd034972eec6905563b2/proprietary_model.py
https://github.com/olivialiu121/ContractEval/blob/f2de74479bb067a13da2fd034972eec6905563b2/Evaluation.py
Paper: https://arxiv.org/abs/2508.03080 · https://aclanthology.org/2025.nllp-1.19/

WHY transcribed rather than vendored wholesale: the upstream files are analysis scripts that
import matplotlib and read CSVs from a results directory. Nothing here executes any of that —
these are the four pure functions the metric path actually depends on, copied from:

    ``proprietary_model.py`` lines 96-102  → ``check_include``   (the per-row verdict)
    ``Evaluation.py``        lines 50, 63  → ``abstain_metric``  (the abstention test)
    ``Evaluation.py``        lines 106-122 → ``get_jaccard``     (token-set overlap)
    ``Evaluation.py``        lines 73-77   → ``confusion_scores``(P/R/F1/F2 and accuracy)

AIDEV-NOTE: ``confusion_scores`` reproduces the reference INCLUDING its missing zero guard, so
it raises ZeroDivisionError exactly where the original does. Our board deviates there on
purpose (spec §3) and ``test_contracteval_parity`` asserts the deviation rather than hiding it.
"""

from __future__ import annotations

from collections.abc import Sequence


def check_include(output: str, label: Sequence[str]) -> bool:
    """proprietary_model.py lines 96-102 — the per-row verdict."""

    if len(label) == 0:
        return output.strip(" \n`").lower().startswith("no related clause")
    return all(substr.strip(" \n`") in output.strip(" \n`") for substr in label)


def abstain_metric(output: str) -> bool:
    """Evaluation.py lines 50 and 63 — the abstention test the METRICS use.

    Note this is a substring test, while ``check_include``'s empty-label branch uses
    ``startswith``. Evaluation.py ignores ``classification`` for negative rows and recomputes
    with ``in``, so the substring form is what produced the published numbers.
    """

    return "no related clause" in output.strip(" \n`").lower()


def get_jaccard(gt: str, pred: str) -> float:
    """Evaluation.py lines 106-122 — verbatim, including the empty-token union inflation."""

    remove_tokens = [".", ",", ";", ":"]
    for token in remove_tokens:
        gt = gt.replace(token, "")
        pred = pred.replace(token, "")
    gt = gt.lower()
    pred = pred.lower()
    gt = gt.replace("/", " ")
    pred = pred.replace("/", " ")
    gt_words = set(gt.split(" "))
    pred_words = set(pred.split(" "))
    intersection = gt_words.intersection(pred_words)
    union = gt_words.union(pred_words)
    return len(intersection) / len(union)


def confusion_scores(tp: int, tn: int, fn: int, fp: int) -> dict[str, float]:
    """Evaluation.py lines 73-77 — verbatim, INCLUDING the absent zero guard on f1/f2."""

    acc = (tp + tn) / (tp + tn + fn + fp) if (tp + tn + fn + fp) > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1_score = (2 * precision * recall) / (precision + recall)
    f2_score = (5 * precision * recall) / (4 * precision + recall)
    return {
        "accuracy": acc,
        "precision": precision,
        "recall": recall,
        "f1": f1_score,
        "f2": f2_score,
    }


__all__ = ["abstain_metric", "check_include", "confusion_scores", "get_jaccard"]
