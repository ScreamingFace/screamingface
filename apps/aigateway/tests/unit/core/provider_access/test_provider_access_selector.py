"""`Selector` — the ONE interpretation point for `X-Profile` (OME-1200, spec §3.2 / §3.6).

# INVARIANT: absent, blank and whitespace-only headers all mean the default selector and are
# NOT explicit; anything else is the stripped value and explicit. The sunset policy is enforced
# here at the parse step and nowhere else — implementations never consult it.
"""

from __future__ import annotations

import pytest

from aigateway.core.provider_access import (
    DEFAULT_SELECTOR_NAME,
    Selector,
    SelectorPolicy,
    SelectorUnsupported,
)


@pytest.mark.parametrize("raw", [None, "", "   ", "\t", " \t "])
def test_absent_and_blank_headers_are_the_implicit_default(raw: str | None) -> None:
    selector = Selector.from_header(raw)

    assert selector == Selector(DEFAULT_SELECTOR_NAME, explicit=False)
    assert selector.is_default


def test_a_literal_default_is_the_default_selector_but_explicit() -> None:
    selector = Selector.from_header("default")

    assert selector.name == DEFAULT_SELECTOR_NAME
    assert selector.is_default
    assert selector.explicit


@pytest.mark.parametrize(("raw", "name"), [("work", "work"), ("  work  ", "work"), ("\tw\t", "w")])
def test_a_named_header_is_stripped_and_explicit(raw: str, name: str) -> None:
    selector = Selector.from_header(raw)

    assert selector == Selector(name, explicit=True)
    assert not selector.is_default


def test_selectors_are_immutable_values() -> None:
    selector = Selector.from_header("work")

    with pytest.raises(AttributeError):
        setattr(selector, "name", "other")
    assert hash(selector) == hash(Selector("work", explicit=True))


# --- the sunset policy (Stage D; HONOUR is the window default) -------------------------------


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_the_reject_policy_still_admits_an_absent_selector(raw: str | None) -> None:
    selector = Selector.from_header(raw, policy=SelectorPolicy.REJECT_EXPLICIT)

    assert selector == Selector(DEFAULT_SELECTOR_NAME, explicit=False)


@pytest.mark.parametrize("raw", ["work", " personal ", "default"])
def test_the_reject_policy_refuses_every_present_selector(raw: str) -> None:
    """# AIDEV-NOTE: a literal `default` is refused too until the D4 equivalence proof exists
    (spec §3.6); admitting it is an owner decision, not an implementation default."""
    with pytest.raises(SelectorUnsupported) as info:
        Selector.from_header(raw, policy=SelectorPolicy.REJECT_EXPLICIT)

    assert info.value.requested == raw.strip()


def test_the_honour_policy_is_the_default_and_admits_named_selectors() -> None:
    assert Selector.from_header("work") == Selector.from_header(
        "work", policy=SelectorPolicy.HONOUR
    )
