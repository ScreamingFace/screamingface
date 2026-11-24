"""The README section "Call an ensemble as a chat model" shows the names of
recipe.chat, client.chat and sf.chat (U7, U9).

FEATURE: SDK model inference, unit U7. The code of the section needs an Engine, so this test
only compiles it and checks its names.
"""

from __future__ import annotations

import re
from pathlib import Path

_README = Path(__file__).resolve().parents[1] / "README.md"
_HEADING = "## Call an ensemble as a chat model"
_NEXT_HEADING = re.compile(r"^## ", re.MULTILINE)
_CODE = re.compile(r"```python\n(.*?)\n```", re.DOTALL)


def _section() -> str:
    text = _README.read_text(encoding="utf-8")
    assert text.count(_HEADING) == 1, f"README.md must have {_HEADING!r} once"
    rest = text[text.index(_HEADING) + len(_HEADING) :]
    end = _NEXT_HEADING.search(rest)
    return rest if end is None else rest[: end.start()]


def test_each_code_block_of_the_section_compiles() -> None:
    blocks = _CODE.findall(_section())
    assert len(blocks) == 7
    for block in blocks:
        compile(block, "README.md", "exec")


def test_the_section_names_the_api() -> None:
    section = _section()
    for phrase in (
        "ensemble.chat.completions.create(",
        "client.chat.completions.create(",
        "sf.chat.completions.create(",
        'model="openrouter/a"',
        "stream=True",
        "sf.AsyncClient()",
        ".chat.endpoint()",
        "IgnoredParameterWarning",
        # U10 (D18): the one-line change from the OpenAI SDK.
        "openai.OpenAI(...)",
        'sf.Client(api_key="sk-...")',
        "model_dump()",
        "client.responses",
        # U11 (D26): tool calls are turned off.
        "tools_not_available",
        "Tools are not available yet",
    ):
        assert phrase in section, phrase


def test_the_section_has_no_old_name() -> None:
    section = _section()
    assert "ModelInference" not in section and "chat.complete(" not in section
    assert "InferenceClient" not in section
