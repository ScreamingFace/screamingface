"""Which functions a Benchmark row may name as a scorer argument (OME-1602, PR 6).

drop hands inspect's ``f1`` its own ``extract_answer``; the row names it as the reference
``inspect_evals.drop.drop:extract_answer`` and grading imports it. One rule decides which
references a row may carry, read at two moments: the importer refuses a row it could not write
safely, and assembly refuses a hand-edited row the same way. Checked by spelling only; nothing
here imports the eval.

The rule: a ``module:attribute`` reference whose module sits inside the package holding the
eval's Task module or its scorer's module.

Worked example, drop (Task ``inspect_evals.drop.drop:drop``, scorer ``inspect_ai.scorer:f1``):
the Task's package is ``inspect_evals.drop`` and the scorer's is ``inspect_ai``, so
``inspect_evals.drop.drop:extract_answer`` may be named, while ``inspect_evals.gsm8k.gsm8k:x``
(another eval) and ``textwrap:dedent`` (the standard library) may not.
"""

from __future__ import annotations

import re

#: ``package.module:function``: dotted identifiers, one colon, one plain attribute.
FUNCTION_REFERENCE: re.Pattern[str] = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*")


def _owning_package(dotted: str) -> str:
    """The package a ``module:attribute`` (or bare module) lives in; a top-level module owns
    itself."""

    module: str = dotted.partition(":")[0]
    return module.rpartition(".")[0] or module


def function_reference_problem(reference: str, *, task: str, scorer: str) -> str | None:
    """Why a row may not name ``reference`` as a scorer argument, or None when it may.

    ``task`` and ``scorer`` are the eval's Task and scorer, as dotted references or module
    names. The answer completes a sentence that starts with the reference.
    """

    if FUNCTION_REFERENCE.fullmatch(reference) is None:
        return "is not a module:attribute function reference"
    module: str = reference.partition(":")[0]
    for owner in (_owning_package(task), _owning_package(scorer)):
        if module == owner or module.startswith(f"{owner}."):
            return None
    return (
        f"points outside the eval's own package ({_owning_package(task)} or "
        f"{_owning_package(scorer)}); a row may only name the eval's own functions"
    )


__all__ = ["FUNCTION_REFERENCE", "function_reference_problem"]
