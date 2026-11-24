"""The chat docs pages show each tested snippet and use no old name (U8, U9).

FEATURE: SDK model inference, unit U8. public-docs has no test runner, so this SDK test reads
the page sources from the repo: the API page /sf-client/api/chat and the OpenAI guide page.
tests/test_model_inference_docs_snippets.py runs each snippet file that these pages show. The
test skips when public-docs is not in the checkout.

STORY: as a developer, I read the Chat page, copy an example, and it is the same file
that an SDK test runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DOCS = REPO / "public-docs"
API_PAGE = DOCS / "src/pages/sf-client/api/ChatPage.vue"
GUIDE = DOCS / "src/pages/sf-client/guides/OpenAiApiPage.vue"
SNIPPETS = DOCS / "src/snippets/chat"
pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="public-docs is not in this checkout")
API_SNIPPETS = (
    "plain_call.py",
    "openai_form.py",
    "model_per_call.py",
    "tools.py",
    "stream.py",
    "async_call.py",
    "endpoint_openai.py",
    "openai_one_line.py",
)


@pytest.mark.parametrize("name", API_SNIPPETS)
def test_api_page_shows_each_tested_snippet(name: str) -> None:
    """The API page imports each snippet file that the SDK test runs, as the raw file."""
    source = API_PAGE.read_text(encoding="utf-8")
    assert f"@/snippets/chat/{name}?raw" in source
    assert (SNIPPETS / name).is_file()


def test_guide_page_shows_the_sdk_way_to_get_the_candidate_url4() -> None:
    """The guide shows endpoint().model first and keeps the evaluation way as an alternative."""
    source = GUIDE.read_text(encoding="utf-8")
    assert "@/snippets/chat/candidate_url4.py?raw" in source
    assert (SNIPPETS / "candidate_url4.py").is_file()
    assert "endpoint().model" in source
    assert "chat.endpoint().model" in source
    assert "@/snippets/openai-chat/candidate_url4.py?raw" in source


@pytest.mark.parametrize("page", [API_PAGE, GUIDE], ids=["api-page", "guide-page"])
def test_pages_have_no_old_name(page: Path) -> None:
    """D13 to D16: no sf.InferenceClient; the call is chat.completions.create."""
    source = page.read_text(encoding="utf-8")
    assert "ModelInference" not in source
    assert "chat.complete(" not in source
    assert "InferenceClient" not in source
    assert "inference-client" not in source


def test_api_page_states_the_one_line_change_and_its_limits() -> None:
    """MI-45 (D18 to D25): the page shows the change of the client line and says what does not
    change with it."""
    source = API_PAGE.read_text(encoding="utf-8")
    for phrase in (
        "Move from the OpenAI SDK",
        "openai.OpenAI(...)",
        "sf.Client(...)",
        "openai.AsyncOpenAI(...)",
        "api_key",
        "base_url",
        "model_dump()",
        # The limits (ans:Q8, Q10, Q11).
        "client.responses",
        "openai.RateLimitError",
        "functions",
    ):
        assert phrase in source, phrase
