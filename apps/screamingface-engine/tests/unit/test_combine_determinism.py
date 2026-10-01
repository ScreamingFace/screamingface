"""Same inputs, same output, same evidence bytes (FW-3, FW-H3; OME-1289 E4a, unit 1).

FEATURE: a replay of a reducer Candidate must match the original byte for byte.
INVARIANT: no iteration order of a dict or set, and no hash seed, reaches an output.
"""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from combine_support import context_text, run, spec_text, vote_spec

# Twelve members, four 2-way ties for the top score, plus unicode values that casefold.
_BODY = """
from combine_support import context_text, run, spec_text, vote_spec

_WORDS = ["\\u00c9", "stra\\u00dfe", "\\u00e9", "STRASSE", "x", "y", "x", "y",
          "\\u4e16\\u754c", "k", "\\u4e16\\u754c", "z"]


def scenario() -> str:
    texts = [f"the answer is {word}" for word in _WORDS]
    output, calls = run(spec_text(vote_spec(12)), context_text(texts))
    combine = calls[0].combine
    assert combine is not None
    return output + "\\n" + combine.model_dump_json(by_alias=True)
"""
_SCRIPT = _BODY + "\nprint(scenario(), end='')\n"
_SEEDS = range(20)


def _in_process() -> str:
    namespace: dict[str, Any] = {}
    exec(_BODY, namespace)
    return namespace["scenario"]()


def _in_new_process(seed: int) -> str:
    here = str(Path(__file__).parent)
    env = {
        **os.environ,
        "PYTHONHASHSEED": str(seed),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": os.pathsep.join(filter(None, [here, os.environ.get("PYTHONPATH")])),
    }
    done = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        env=env,
        capture_output=True,
        encoding="utf-8",
        check=True,
        timeout=120,
    )
    return done.stdout


def test_endpoint_output_and_evidence_are_identical_across_hash_seeds() -> None:
    with ThreadPoolExecutor(max_workers=5) as pool:
        outputs = list(pool.map(_in_new_process, _SEEDS))
    assert set(outputs) == {_in_process()}


def test_endpoint_is_identical_over_100_in_process_runs() -> None:
    texts = [f"say {word}" for word in ("a", "b", "b", "a", "c", "é", "É", "c")]
    intent = spec_text(vote_spec(8))
    context = context_text(texts)
    results = set()
    for _ in range(100):
        output, calls = run(intent, context)
        assert calls[0].combine is not None
        results.add((output, calls[0].combine.model_dump_json(by_alias=True)))
    assert len(results) == 1
    output = next(iter(results))[0]
    assert output == texts[0]  # a (2), b (2), c (2), é (2): the first holder of the first tie
