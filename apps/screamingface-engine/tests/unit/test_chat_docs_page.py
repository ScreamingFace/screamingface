"""DOC-2 of prd/docs.md (DOC-S2): the docs page states each limit of the chat endpoint.

FEATURE: OpenAI-compatible Engine API, unit U7 (prd/docs.md DOC-2). public-docs has no test
runner, so this Engine unit test reads the page source from the repo. It skips when public-docs
is not in the checkout.

STORY: as a developer, I read the docs page of the chat endpoint and find each limit stated
before an agent trips over it.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
DOCS = REPO / "public-docs"
PAGE = DOCS / "src/pages/sf-client/guides/OpenAiApiPage.vue"
SNIPPETS = DOCS / "src/snippets/openai-chat"
pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="public-docs is not in this checkout")

LIMITS: dict[str, tuple[str, ...]] = {
    "sampling-fields": ("ignores the sampling fields", "tool_choice", "Set them in the recipe"),
    "unknown-fields": ("ignores unknown top-level request fields",),
    "usage-sum": ("sum of the whole ensemble", "screamingface.final_step.usage"),
    "final-step-null": (
        "final_step and its usage are null",
        "ends in a reducer",
        "no single final step",
        "same route with the same parameters",
        "finish_reason is stop",
    ),
    "tools-final-model-step": ("must end in a model step", "such as Vote"),
    "tools-cascade-gate": ("refuses each Cascade and each Gate", "Cascade abstains"),
    "tools-unique-final-step": ("final step of the recipe must be unique",),
    "corrective-loop": ("refuses a recipe with a corrective loop",),
    "benchmark-linked": ("refuses a benchmark-linked expression", "Candidate URL4"),
    "cache-zero-tokens": ("counts 0 tokens",),
    "unpriced-cost": ("cost_usd is null when one call of the run has no price",),
    "run-limit": ("24 runs in flight for each user", "429 overloaded", "local_max_concurrent_runs"),
    "body-limit": ("at most 8,000,000 bytes", "413 request_too_large"),
    "model-length": ("at most 32,000 characters", "413 request_too_large"),
    "large-bodies": (
        "At most four bodies above 1,000,000 bytes",
        "429 overloaded",
        "30 seconds",
        "408 request_timeout",
    ),
    "time-limit": ("chat_max_wait_s seconds (600 by default)", "504 timeout"),
    "remote-media": ("refuses remote picture URLs", "data: URIs"),
    "unsupported-fields": ("refuses n above 1, logprobs and audio",),
    "buffered-stream": ("The stream is buffered",),
    "turn-cost": ("Each turn runs the full ensemble",),
    "web-search-default": ("Web search is on by default", "web_search=false"),
    "web-search-cost": (
        "adds tokens and cost to each step that searches",
        "576 prompt tokens",
        "16 prompt tokens with web_search=false",
    ),
    "tools-final-step-search": (
        "the final step searches only when the provider does the search itself",
        "400 recipe_not_supported",
    ),
    "engine-search-tools": ("call one of your tools by name", "web_search=false"),
    "pictures-with-tools": ("final model must be able to read pictures",),
    "error-envelope": ("OpenAI error envelope", "x-should-retry"),
    "other-api-formats": ("Claude Code and Codex need other API formats",),
}

_ITEM = re.compile(r'<li\b[^>]*\bdata-limit="([a-z0-9-]+)"[^>]*>(.*?)</li>', re.DOTALL)


def _limit_items(source: str) -> dict[str, str]:
    """The plain text of each limit item of the page, by its data-limit key."""

    items: dict[str, str] = {}
    for match in _ITEM.finditer(source):
        key, body = match.group(1), match.group(2)
        assert key not in items, f"the limit {key!r} is listed twice"
        text = html.unescape(re.sub(r"<[^>]+>", "", body))
        items[key] = " ".join(text.split())
    return items


def test_page_lists_every_documented_limit() -> None:
    items = _limit_items(PAGE.read_text(encoding="utf-8"))
    missing = sorted(set(LIMITS) - set(items))
    unknown = sorted(set(items) - set(LIMITS))
    assert set(items) == set(LIMITS), f"missing limits: {missing}; unknown limits: {unknown}"
    for key, phrases in LIMITS.items():
        for phrase in phrases:
            assert phrase in items[key], f"the limit {key!r} does not state {phrase!r}"


@pytest.mark.parametrize("name", ["openai_sdk.py", "candidate_url4.py"])
def test_page_shows_each_tested_snippet(name: str) -> None:
    """The page imports each snippet file that an Engine test runs, as the raw file."""
    source = PAGE.read_text(encoding="utf-8")
    assert f"@/snippets/openai-chat/{name}?raw" in source
    assert (SNIPPETS / name).is_file()
