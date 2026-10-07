"""COPIED third-party code — the official MuSiQue scorer. Do not edit.

What this is
    The paper's own scoring code, copied from https://github.com/StonyBrookNLP/musique at commit
    922ac98f19a201998dbdae6d7f2887a5258dbdeb (the `metrics/` package):

    - ``metric.py``  — the abstract accumulator base,
      upstream sha256 c858d1bfda2f0b005065e87a402cd2f82154eb7eed5916845ae130759cc3a299
    - ``answer.py``  — SQuAD-style normalisation, token F1 and exact match, max over aliases,
      upstream sha256 10368f619b4d5ef5d83748c05a96c0afd332a14ab5c010740c98d58dfaefe974
    - ``support.py`` — HotpotQA-style set F1 over supporting paragraph numbers,
      upstream sha256 ac16c0daf458a6a4d6db97682c2340fe5b5936a947bf32c04dc3bf16406077c6

    License: CC BY 4.0, covering the data and the code. ``LICENSE`` here is the repo's licence
    text; the repo's whitespace hooks trimmed one trailing space and the final blank line from it,
    and its words are unchanged.

Why a copy instead of a dependency
    The scorer is not published as a package, and a run cannot reach GitHub. The spec's rule is
    that our number means what the paper's number means, so the code that scores is the paper's
    code, not a re-implementation of it (spec D8).

The ONLY change we made
    ``from metrics.metric import Metric`` became ``from .metric import Metric`` in ``answer.py``
    and ``support.py``, so the copy imports inside this package. There is no banner in the files
    themselves: ``tests/unit/test_musique_vendor.py`` reverses that one line and demands the
    upstream sha256 above, so any second edit fails CI.

INVARIANT: these files ARE the exam's marking scheme. Upstream quirks stay, including the
duplicated ``f1, em = 1.0, 1.0`` line in ``support.py``. ``..grading`` is the only caller, and it
calls the functions and nothing else.
"""
