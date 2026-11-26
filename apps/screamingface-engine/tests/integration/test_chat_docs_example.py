"""DOC-1: the OpenAI SDK example of the docs page runs on the local stack (U7).

FEATURE: OpenAI-compatible Engine API, unit U7 (prd/docs.md DOC-1, DOC-S1). Plan decision D1: an
Engine integration test. The App runs the real executor in process, a fake gateway (an
`httpx.MockTransport`) answers each model call, and the `openai` SDK is the client. The test runs
the exact example file that the docs page shows
(public-docs/src/snippets/openai-chat/openai_sdk.py).
The only seam is `openai.OpenAI`: the test swaps it for a factory that keeps each argument of the
example and adds the in-process HTTP client, so no request leaves the machine.

STORY: as a developer, I copy the Python example of the docs page and run it against my local
stack; it prints the answer, the token count, and the status and cost of the ensemble.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import openai
import pytest
from _chat_sdk_stack import ChatStack, chat_stack

REPO = Path(__file__).resolve().parents[4]
DOCS = REPO / "public-docs"
SNIPPET = DOCS / "src" / "snippets" / "openai-chat" / "openai_sdk.py"
SECRET = "chat-docs-example-secret-0000000000000"
EXAMPLE_MODEL = "openrouter/deepseek/deepseek-v4-flash"
ANSWER = "Paris"
LOCAL_BASE_URL = "http://127.0.0.1:9108/v1"
# WHY: the Engine image and some CI checkouts hold only the app; in the monorepo the directory
# exists, so a moved snippet fails loudly instead of skipping.
pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="public-docs is not in this checkout")


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[ChatStack]:
    """The local App over the real executor, a filesystem blob store and the fake gateway."""
    with chat_stack(
        tmp_path,
        secret=SECRET,
        replies={EXAMPLE_MODEL: ANSWER},
        listed=(EXAMPLE_MODEL,),
        known={EXAMPLE_MODEL},
        default_model=EXAMPLE_MODEL,
    ) as built:
        # WHY: the example sends no identity header; a local stack needs none, and on a hosted
        # Engine the edge adds it from the Access token (CC-S4, CC-S5).
        built.app.state.runs_require_identity = False
        yield built


def _run_example(stack: ChatStack, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Run the docs example as a script; return the arguments it gave to `OpenAI(...)`."""
    seen: list[dict[str, Any]] = []
    real = openai.OpenAI

    def in_process(**kwargs: Any) -> openai.OpenAI:
        seen.append(dict(kwargs))
        local = {"base_url": "http://testserver/v1", "http_client": stack.http, "max_retries": 0}
        return real(**{**kwargs, **local})

    monkeypatch.setattr(openai, "OpenAI", in_process)
    source = SNIPPET.read_text(encoding="utf-8")
    exec(compile(source, str(SNIPPET), "exec"), {"__name__": "__main__"})
    return seen


def _printed(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return capsys.readouterr().out.splitlines()


def test_openai_sdk_example_runs_on_local_stack(
    stack: ChatStack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """DOC-1 (DOC-S1): the page example, unchanged, answers on the local stack."""
    monkeypatch.delenv("ENGINE_BASE_URL", raising=False)
    monkeypatch.delenv("CF_ACCESS_TOKEN", raising=False)
    assert f'model="{EXAMPLE_MODEL}"' in SNIPPET.read_text(encoding="utf-8")

    seen = _run_example(stack, monkeypatch)

    assert len(seen) == 1
    kwargs = seen[0]
    assert kwargs["base_url"] == LOCAL_BASE_URL
    assert isinstance(kwargs["api_key"], str) and kwargs["api_key"]
    assert kwargs["default_headers"] == {}
    lines = _printed(capsys)
    assert ANSWER in lines, f"{lines!r}"
    at = lines.index(ANSWER)
    assert lines[at + 1] == "14"
    assert lines[at + 2] == "answered 0.001"
    assert len(lines) > at + 3
    assert [sent["model"] for sent in stack.gateway.seen] == [EXAMPLE_MODEL]


def test_openai_sdk_example_sends_the_access_token_to_a_hosted_engine(
    stack: ChatStack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """DOC-1 (CC-S4): with two variables set, the example sends `Cf-Access-Token` when hosted."""
    monkeypatch.setenv("ENGINE_BASE_URL", "https://engine.invalid/v1")
    monkeypatch.setenv("CF_ACCESS_TOKEN", "access-token-for-test")

    seen = _run_example(stack, monkeypatch)

    assert seen[0]["base_url"] == "https://engine.invalid/v1"
    assert seen[0]["default_headers"] == {"Cf-Access-Token": "access-token-for-test"}
    assert ANSWER in _printed(capsys)
