"""ContractEval's deterministic grading — the paper's definitions, reproduced exactly.

The reference harness is https://github.com/olivialiu121/ContractEval (MIT), pinned at commit
f2de74479bb067a13da2fd034972eec6905563b2 (repo tip at the 2026-09-09 fetch). It is CITED here
rather than vendored: we execute nothing from it, we reproduce four small functions, and the
full transcription lives in `docs/spec/2026-09-17-OME-1148-contracteval-containment.md` §2.
The functions this module mirrors are committed verbatim as test material in
`tests/unit/_contracteval_reference.py`, and `test_contracteval_parity.py` proves the two agree
over real CUAD gold spans — so a "tidy-up" here fails CI instead of moving our F1 silently.

INVARIANT — this module is protocol, not preference. Every rule below is the reference's
behaviour including its quirks. A change that makes one of these prettier moves our published
numbers off the paper's, so each carries the file and line range it mirrors and a test that
names it as protocol alignment.

Moved verbatim from the hand-built `benchmarks/contracteval/grading.py` (OME-1527); `f1` is the
hand-built confusion-matrix reducer's formula, unchanged, so the Task's whole-run metric
(`contracteval.py`) computes the number the hand-built Benchmark published.

No inspect import: the parity test runs in the extra-less install.
"""

from __future__ import annotations

from collections.abc import Sequence

# WHY these four characters: proprietary_model.py applies `.strip(" \n`")` to both the model
# output and every gold span before comparing, so a fenced or padded reply is not penalised.
_WRAPPER = " \n`"

# WHY a substring test and not `startswith`: proprietary_model.py's empty-label branch uses
# `.startswith('no related clause')`, but Evaluation.py (lines 60-71) IGNORES `classification`
# for negative rows and recomputes the abstention with `'no related clause' in ...`. The
# published numbers therefore come from the substring form; `startswith` is dead code in the
# metric path. Mirrored: substring (spec F-3).
_ABSTENTION = "no related clause"

# WHY these and not `string.punctuation`: get_jaccard (Evaluation.py lines 106-122) removes
# exactly this set before lowercasing.
_JACCARD_STRIPPED = (".", ",", ";", ":")


def normalized(text: str) -> str:
    """Strip the reference's wrapper characters from one side of a comparison."""

    return text.strip(_WRAPPER)


def is_abstention(output: str) -> bool:
    """Did the model claim no clause applies? — Evaluation.py lines 50 and 63."""

    return _ABSTENTION in normalized(output).casefold()


def verdict(output: str, gold_spans: Sequence[str]) -> bool:
    """Is this row correct? — proprietary_model.py's ``check_include``, lines 96-102.

    INVARIANT: all-or-nothing. A positive row is correct only when EVERY gold span appears
    verbatim inside the reply; there is no partial credit in this protocol. A negative row is
    correct only when the model abstains.
    """

    if not gold_spans:
        return is_abstention(output)
    reply = normalized(output)
    return all(normalized(span) in reply for span in gold_spans)


def jaccard(gold_spans: Sequence[str], output: str) -> float:
    """Token-set overlap — ``get_jaccard``, Evaluation.py lines 106-122.

    AIDEV-NOTE: per-Case evidence only. The reference merges it in afterwards as a mean over
    POSITIVE rows only (spec F-5); that whole-run number is not served (see the Task README).
    """

    gold = _jaccard_tokens(" ".join(gold_spans))
    pred = _jaccard_tokens(normalized(output))
    union = gold | pred
    if not union:
        return 0.0
    return len(gold & pred) / len(union)


def _jaccard_tokens(text: str) -> set[str]:
    """Normalise one side into the reference's token set.

    WHY `split(" ")` and not `.split()`: the bare separator form keeps EMPTY-STRING tokens from
    runs of whitespace, and those empties join the set and inflate the union — so the reference
    scores "alpha beta" against "alpha  beta" as 2/3, not 1.0. That is the published behaviour
    (spec F-5); `.split()` would silently raise every model's Jaccard.
    """

    for token in _JACCARD_STRIPPED:
        text = text.replace(token, "")
    return set(text.casefold().replace("/", " ").split(" "))


def f1(true_positives: int, false_negatives: int, false_positives: int) -> float:
    """The paper's F1 from a run's confusion-matrix cells — Evaluation.py lines 73-77.

    Worked example: 3 found clauses (TP), 2 missed (FN), 1 answer where none exists (FP) →
    precision 3/4 = 0.75, recall 3/5 = 0.6, F1 = 2 · 0.75 · 0.6 / 1.35 = 0.6667. True
    negatives (rightly declined) do not enter it: that is why an always-declining model,
    right on 70% of rows, scores 0.

    NAMED DEVIATION: the reference computes 2PR/(P+R) with no zero guard and raises
    ZeroDivisionError for a model that never scores a TP. With 70.3% of rows negative, an
    always-abstaining model is realistic rather than hypothetical, so we return the limit 0.0.
    """

    found: int = true_positives + false_positives
    existing: int = true_positives + false_negatives
    precision: float = true_positives / found if found else 0.0
    recall: float = true_positives / existing if existing else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


__all__ = ["f1", "is_abstention", "jaccard", "normalized", "verdict"]
