"""ContractEval's deterministic grading — the paper's definitions, reproduced exactly.

The reference harness is https://github.com/olivialiu121/ContractEval (MIT). It is CITED here
rather than vendored: we execute nothing from it, we reproduce four small functions, and the
full transcription lives in `docs/spec/2026-09-09-OME-1148-contracteval-span-extraction.md` §2.

INVARIANT — this module is protocol, not preference. Every rule below is the reference's
behaviour including its quirks. A change that makes one of these prettier moves our published
numbers off the paper's, so each carries the file and line range it mirrors and a test that
names it as protocol alignment.

AIDEV-NOTE: there is NO F1 here. ContractEval's F1/F2 are computed from a DATASET-level
confusion matrix over rows, not per case — see `aggregate.py`. The per-case verdict is a
boolean. If you came here looking for span overlap or partial credit, the protocol has none.
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

    AIDEV-NOTE: secondary metric. It is absent from the reference's headline results CSV and is
    merged in afterwards as a mean over POSITIVE rows only (spec F-5) — `aggregate.py` owns that
    population rule, not this function.
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


__all__ = ["is_abstention", "jaccard", "normalized", "verdict"]
