"""Per-model openness classification (OME-1181, spec §2.4).

Pure logic, no DB. `classify_model` answers about ONE declared model route, which is a
different question from `classify_providers`' one verdict per submission — see OME-1179 D1:
the aggregation stays any-closed-wins, only its input changes.
"""

from __future__ import annotations

import pytest

from scoreboard.classification.openness import classify_model, classify_providers

# FEATURE: OME-1179 Q1 — "open" means weights you can download and run, whatever the licence
# says about commercial use. That is why mistral-large (research licence) is open here and
# gemini (API only) is not.
OPEN_ROUTES = [
    "openrouter/meta-llama/Llama-3.1-70B-Instruct",
    "openrouter/qwen/Qwen2.5-72B-Instruct",
    "openrouter/deepseek/deepseek-v4-pro",
    "openrouter/mistralai/mistral-large-2411",
    "openrouter/mistralai/Mistral-7B-Instruct-v0.3",
]

CLOSED_ROUTES = [
    "openrouter/openai/gpt-5.5",
    "openrouter/anthropic/claude-opus-4.8",
    "openrouter/google/gemini-3-pro",
    "openrouter/google/gemini-3-flash-preview",
]

# INVARIANT: these three are why a specific model rule must beat its owner rule. Each ships
# downloadable weights under a name whose OWNER is on the closed list, so a plain
# owner-substring match files them closed — which is exactly the OME-1145 complaint.
OWNER_CONTRADICTS_MODEL = [
    ("openrouter/openai/gpt-oss-120b", "openai"),
    ("openrouter/google/gemma-2-27b-it", "google"),
]


@pytest.mark.parametrize("route", OPEN_ROUTES)
def test_downloadable_weights_classify_open(route: str) -> None:
    assert classify_model(route) == "open"


@pytest.mark.parametrize("route", CLOSED_ROUTES)
def test_api_only_models_classify_closed(route: str) -> None:
    assert classify_model(route) == "closed"


@pytest.mark.parametrize(("route", "owner"), OWNER_CONTRADICTS_MODEL)
def test_a_specific_model_rule_beats_its_owner_rule(route: str, owner: str) -> None:
    """WHY both assertions: the first fails if the carve-out is missing, the second fails if
    the carve-out was written so broadly that it swallowed the owner rule with it."""
    assert classify_model(route) == "open"
    assert owner in route
    assert classify_model(f"openrouter/{owner}/something-proprietary") == "closed"


def test_kimi_is_recognised_at_all() -> None:
    """moonshotai matches nothing in the registry today, so it falls to the unknown default.

    On the live draco-3pass board this single omission is the difference between 0% and 29%:
    it closes `best_open_source` and `pareto_lean`, both all-open-weights fusions.
    """
    assert classify_model("openrouter/moonshotai/kimi-k2.6") == "open"


def test_an_unrecognised_model_is_unknown_and_not_closed() -> None:
    """INVARIANT: `unknown` must not collapse into `closed`.

    Both close an entry under OME-1179 D1, so a test asserting only "it is not open" would
    pass against a classifier that lost the distinction. D4 requires the count of unrecognised
    models to be reportable, which is impossible once the two verdicts are the same value.
    """
    verdict = classify_model("acme/never-heard-of-this-one")

    assert verdict == "unknown"
    assert verdict != "closed"


@pytest.mark.parametrize("route", OPEN_ROUTES + CLOSED_ROUTES)
def test_the_routing_prefix_does_not_change_the_verdict(route: str) -> None:
    """INVARIANT: routing is not openness.

    Every live draco-3pass route is `openrouter/`-prefixed, and `openrouter` is on the closed
    provider marker list.
    """
    bare = route.removeprefix("openrouter/")

    assert bare != route
    assert classify_model(bare) == classify_model(route)


def test_an_unrecognised_model_stays_unknown_even_when_openrouter_carried_it() -> None:
    """INVARIANT: the routing prefix must be stripped BEFORE the closed markers are consulted.

    WHY this exists next to the parametrised prefix test above rather than instead of it: that
    test cannot fail for a recognised model. `_MODEL_RULES` checks the open markers first, so
    an open model wins on its own name and `openrouter` is never reached — the strip is
    redundant for every route in OPEN_ROUTES, and CLOSED_ROUTES are closed either way. Removing
    `_strip_routing_prefix` entirely leaves that whole parametrisation green (found by mutation
    testing, 2026-09-11).

    The unknown case is the one that needs it. Without the strip, `openrouter` matches
    `_CLOSED_PROVIDER_MARKERS` and an unrecognised model is published as a confident `closed`
    instead of an honest `unknown` — which destroys the count OME-1179 D4 requires, and does it
    silently, since a stale registry then looks like a real closed verdict.
    """
    assert classify_model("acme/never-heard-of-this-one") == "unknown"
    assert classify_model("openrouter/acme/never-heard-of-this-one") == "unknown"


@pytest.mark.parametrize(
    "route",
    [
        "openrouter/openai/not-gemma-proprietary",
        "openrouter/anthropic/kimi-wrapper",
        "openrouter/google/not-qwen-api",
        "openrouter/openai/gpt-5.5-llama-killer",
        "openrouter/anthropic/claude-with-mistral-flavour",
    ],
)
def test_a_crafted_model_name_cannot_buy_an_open_verdict(route: str) -> None:
    """INVARIANT: routes are CLIENT-SUBMITTED, so the classifier is an adversarial surface.

    Matching an open marker anywhere in the whole route lets a submitter name a proprietary
    model `not-gemma-proprietary` and be published as open — the fail-closed contract inverted
    by choosing a string. Found in review of PR #922; every route here returned `open`.

    The rule is therefore structural, not textual: the OWNER segment decides, and a family
    exception must belong to that owner. `google/gemma-*` is open because Google ships Gemma's
    weights; `openai/not-gemma-anything` is not, because OpenAI does not.
    """
    assert classify_model(route) == "closed"


def test_an_owner_family_exception_is_scoped_to_that_owner() -> None:
    """`gpt-oss` is OpenAI's and `gemma` is Google's. Neither name may travel."""
    assert classify_model("openrouter/openai/gpt-oss-120b") == "open"
    assert classify_model("openrouter/google/gemma-2-27b-it") == "open"

    assert classify_model("openrouter/google/gpt-oss-120b") == "closed"
    assert classify_model("openrouter/anthropic/gemma-2-27b-it") == "closed"


# Every `custom_llm_provider` the Gateway registers, read off
# `apps/aigateway/src/aigateway/plugins/*_provider/plugin.py`. Hardcoded because apps never
# import another app's internals; this list is the contract between them, and it drifts only
# when a provider is added there without being taught here — which is exactly what this catches.
REGISTERED_GATEWAY_PROVIDERS = [
    ("openai/gpt-5.5", "closed"),
    ("anthropic/claude-opus-4.8", "closed"),
    ("gemini-cli/gemini-2.5-flash", "closed"),
    ("codex/gpt-5.4-mini", "closed"),
    ("antigravity/gemini-3-pro", "closed"),
    ("huggingface/meta-llama/Llama-3.1-70B", "open"),
    ("ollama/llama3.1:70b", "open"),
]


@pytest.mark.parametrize(("route", "expected"), REGISTERED_GATEWAY_PROVIDERS)
def test_every_registered_gateway_provider_is_classified(route: str, expected: str) -> None:
    """INVARIANT: an owner the Gateway actually supports must never read as a registry gap.

    `unknown` and `closed` both close the entry under OME-1179 D1, so a miss here changes no
    percentage. It corrupts the D4 count: an ordinary supported API-only provider reported as
    unrecognised makes the staleness signal meaningless, because the number stops meaning
    "models the registry has not been taught about".

    `gemini-cli`, `codex` and `antigravity` were all missing — found in review of PR #922. The
    eighth registered provider, `openrouter`, is a routing prefix rather than an owner and is
    covered by the prefix tests above.
    """
    assert classify_model(route) == expected


def test_a_route_with_no_owner_segment_is_unknown() -> None:
    """Fail closed on a shape the registry cannot reason about, rather than guessing from the
    bare string — which is how the crafted-name hole above was opened in the first place.
    """
    assert classify_model("claude-opus-4.8") == "unknown"
    assert classify_model("openrouter/claude-opus-4.8") == "unknown"


def test_the_existing_row_level_classifier_is_untouched() -> None:
    """GUARD: `classify_providers` still serves `_current_split` and `_compute_trend` until
    OME-1145 replaces them. Its provider-prefix behaviour must not shift under this change —
    including the `openrouter` verdict, which is correct for a PROVIDER and wrong only when
    a model route is fed to it.
    """
    assert classify_providers(["openrouter"]) == "closed"
    assert classify_providers(["huggingface"]) == "open"
    assert classify_providers([]) == "closed"
