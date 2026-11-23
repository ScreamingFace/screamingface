"""The docs pages of InferenceClient show each tested snippet and use no old name (U8).

FEATURE: SDK model inference, unit U8. public-docs has no test runner, so this SDK test reads the
page sources from the repo: the API page /sf-client/api/inference-client and the OpenAI guide
page. tests/test_model_inference_docs_snippets.py runs each snippet file that these pages show.
The test skips when public-docs is not in the checkout.

STORY: as a developer, I read the InferenceClient page, copy an example, and it is the same file
that an SDK test runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DOCS = REPO / "public-docs"
API_PAGE = DOCS / "src/pages/sf-client/api/InferenceClientPage.vue"
GUIDE = DOCS / "src/pages/sf-client/guides/OpenAiApiPage.vue"
SNIPPETS = DOCS / "src/snippets/inference-client"
pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="public-docs is not in this checkout")
API_SNIPPETS = (
    "plain_call.py",
    "model_per_call.py",
    "tools.py",
    "stream.py",
    "async_call.py",
    "endpoint_openai.py",
)


@pytest.mark.parametrize("name", API_SNIPPETS)
def test_api_page_shows_each_tested_snippet(name: str) -> None:
    """The API page imports each snippet file that the SDK test runs, as the raw file."""
    source = API_PAGE.read_text(encoding="utf-8")
    assert f"@/snippets/inference-client/{name}?raw" in source
    assert (SNIPPETS / name).is_file()


def test_guide_page_shows_the_sdk_way_to_get_the_candidate_url4() -> None:
    """The guide shows endpoint().model first and keeps the evaluation way as an alternative."""
    source = GUIDE.read_text(encoding="utf-8")
    assert "@/snippets/inference-client/candidate_url4.py?raw" in source
    assert (SNIPPETS / "candidate_url4.py").is_file()
    assert "endpoint().model" in source
    assert "@/snippets/openai-chat/candidate_url4.py?raw" in source


@pytest.mark.parametrize("page", [API_PAGE, GUIDE], ids=["api-page", "guide-page"])
def test_pages_have_no_old_name(page: Path) -> None:
    """D11 and D12: the class is InferenceClient and the call is chat.completions.create."""
    source = page.read_text(encoding="utf-8")
    assert "ModelInference" not in source
    assert "chat.complete(" not in source
