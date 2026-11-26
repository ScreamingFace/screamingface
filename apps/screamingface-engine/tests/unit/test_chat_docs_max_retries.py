"""RR-23 of the chat endpoint review round 2 (RR-S19): each OpenAI client in the Engine docs
snippets passes max_retries=0.

FEATURE: OpenAI-compatible Engine API, review round 2, unit U-H1. The OpenAI SDK retries a lost
connection by default, and each try is a new paid run of the ensemble. public-docs has no test
runner, so this Engine unit test reads the snippet source from the repo. It skips when public-docs
is not in the checkout.

STORY: as a developer, I copy an OpenAI client from the docs and get no retry that pays twice.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
DOCS = REPO / "public-docs"
SNIPPETS = DOCS / "src/snippets/openai-chat"
pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="public-docs is not in this checkout")


def _openai_clients(tree: ast.AST) -> list[ast.Call]:
    """The calls of OpenAI or AsyncOpenAI that pass base_url."""

    clients: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name not in ("OpenAI", "AsyncOpenAI"):
            continue
        if any(keyword.arg == "base_url" for keyword in node.keywords):
            clients.append(node)
    return clients


def test_docs_openai_clients_pass_max_retries_zero() -> None:
    found = 0
    for path in sorted(SNIPPETS.glob("*.py")):
        for call in _openai_clients(ast.parse(path.read_text(encoding="utf-8"))):
            found += 1
            values = [keyword.value for keyword in call.keywords if keyword.arg == "max_retries"]
            assert len(values) == 1, f"{path.name}:{call.lineno} has no max_retries"
            assert isinstance(values[0], ast.Constant) and values[0].value == 0, (
                f"{path.name}:{call.lineno} does not pass max_retries=0"
            )
    assert found >= 1
