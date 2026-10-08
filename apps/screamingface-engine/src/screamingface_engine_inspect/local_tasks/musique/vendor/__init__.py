"""COPIED third-party code — the official MuSiQue scorer. Do not edit below the headers.

What this is
    The paper's own scoring code, copied from https://github.com/StonyBrookNLP/musique at commit
    922ac98f19a201998dbdae6d7f2887a5258dbdeb (the ``metrics/`` package). Each file's own
    docstring links to its upstream blob at that commit; the sha256 below is of the upstream
    file's code after its module docstring, which is what the test checks:

    - ``metric.py``  — the abstract accumulator base,
      upstream code sha256 caef22392788f4dc03719df96e1872b2900f1e4774e2e951533c9a17d0dc69f9
    - ``answer.py``  — SQuAD-style normalisation, token F1 and exact match, max over aliases,
      upstream code sha256 36e249e93436617dd9bbbced66a36167b285bfe612ffad9fafc6ad5a5e0843be
    - ``support.py`` — HotpotQA-style set F1 over supporting paragraph numbers,
      upstream code sha256 aff8cf854483627edc7e777f6dd996255671e3590140574909e1b10c84232dc3

    License: CC BY 4.0, covering the data and the code. ``LICENSE`` here is the repo's licence
    text; the repo's whitespace hooks trimmed one trailing space and the final blank line from it,
    and its words are unchanged.

Why a copy instead of a dependency
    The scorer is not published as a package, and a run cannot reach GitHub. The spec's rule is
    that our number means what the paper's number means, so the code that scores is the paper's
    code, not a re-implementation of it (spec D8).

The ONLY two changes we made
    1. Each file's module docstring is ours: a header that links to the upstream blob at the
       pinned commit. The authors' own docstrings are not repeated here (owner rule: a vendored
       file's docstring points at its source, it never copies the source's docstring).
    2. ``from metrics.metric import Metric`` became ``from .metric import Metric`` in
       ``answer.py`` and ``support.py``, so the copy imports inside this package.
    ``tests/unit/inspect/test_local_task_musique_vendor.py`` drops the header, reverses that one
    line and demands the upstream code sha256 above, so any third edit fails CI.

INVARIANT: these files ARE the exam's marking scheme. Upstream quirks stay, including the
duplicated ``f1, em = 1.0, 1.0`` line in ``support.py``. ``..musique`` is the only caller, and it
calls the functions and nothing else.
"""
