"""COPIED third-party code — the ARC Prize harness's reply parser. Do not edit below the header.

What this is
    The reply parser of the ARC Prize Foundation's model-testing harness, copied from
    https://github.com/arcprize/arc-agi-benchmarking at commit
    9e2828fb5bd3ab43f6b9fc545595b82b67473b93. The file's own docstring links to its upstream blob
    at that commit; the sha256 below is of the upstream file, which has no docstring of its own,
    so it is exactly the code after our header:

    - ``parsing.py`` — ``parse_and_validate_json``: a ``\\boxed{...}`` grid first, else the last
      bracketed JSON in the reply; raises ``ValueError`` when neither is a list of lists,
      upstream sha256 67f6be50f339537bacac646f290cd782c47eb5fc4ccd4900a5b8bf9a4389917a

    License: MIT (``LICENSE`` here is the repo's ``LICENSE.md``; the repo's end-of-file hook
    added the final newline upstream lacks, and its words are unchanged).

Why a copy instead of a dependency
    The harness is not published as a package, and a run cannot reach GitHub. Our number means
    the ARC Prize harness's number only while the code that reads a reply is the harness's code
    (OME-1476 spec, D4).

The ONLY change we made
    The module docstring is ours: a header that links to the upstream blob at the pinned commit.
    ``tests/unit/inspect/test_local_task_arc_agi_2_vendor.py`` drops it and demands the upstream
    sha256 above, so any other edit fails CI.

What is NOT copied, and why
    The prompt builder (``prompts/prompt_manager.py`` + ``system_prompt.txt``) is restated in
    ``..arc_agi_2`` instead: the template file ends without a newline and the builder has a
    whitespace-only line, both of which the repo's whitespace hooks would rewrite. The restated
    template's sha256 equals the upstream file's, and a fixture prompt equals the upstream
    builder's output byte for byte (``test_local_task_arc_agi_2.py`` pins both).

INVARIANT: this file IS how the exam reads an answer. Upstream quirks stay, including that a
reply ending in ``}`` is tried as a dict and gives up rather than scanning further back.
``..arc_agi_2`` is the only caller, and it calls ``parse_and_validate_json`` and nothing else.
"""
