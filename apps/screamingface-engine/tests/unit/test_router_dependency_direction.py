"""The routing policy and the operation-call leaf never load the Router record codec (Unit 5.2).

FEATURE: Router Recipe extension (contracts C5, C6, C15). The policy decides; `router_decision`
reads and writes the C5 draft and record. `operation_calls` only carries a record it is handed.

INVARIANT: `world.routing_policy` imports exactly one Engine module, the shared vocabulary
`router_vocabulary`, which holds the outcome, reason and parse words a decision and its record
share.
INVARIANT: importing the policy or `operation_calls` in a fresh interpreter does not load
`router_decision`; there the record is a type only.
INVARIANT: DECIDE recomputes KEYWORDS itself, and importing it loads no RE2: only a regex
selector that runs does.
WHY: a decision that depended on its record codec would change whenever the record's reader did,
and the shared operation-call leaf would load a codec it never runs.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import subprocess
import sys
from types import ModuleType

import pytest

from screamingface_engine.world import routing_policy

_CODEC = "screamingface_engine.router_decision"


def _engine_imports(module: ModuleType) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    return {name for name in imported if name.startswith("screamingface_engine")}


def test_the_policy_imports_only_the_shared_vocabulary() -> None:
    assert _engine_imports(routing_policy) == {"screamingface_engine.router_vocabulary"}


@pytest.mark.parametrize(
    "module",
    ["screamingface_engine.world.routing_policy", "screamingface_engine.operation_calls"],
)
def test_importing_it_does_not_load_the_record_codec(module: str) -> None:
    script = f"import sys, {module}; print({_CODEC!r} in sys.modules)"

    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True, timeout=120
    )

    assert done.stdout.strip() == "False"


def test_decide_recomputes_keywords_and_loads_re2_only_when_a_selector_runs() -> None:
    assert importlib.util.find_spec("screamingface_engine.world.router_keywords") is None
    loaded = ("screamingface_engine.combine.operators.extract", "re2")
    script = (
        "import sys, screamingface_engine.world.router_decide as d; "
        f"print(callable(d.keyword_labels), [m for m in {loaded!r} if m in sys.modules])"
    )

    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True, timeout=120
    )

    assert done.stdout.strip() == "True []"
