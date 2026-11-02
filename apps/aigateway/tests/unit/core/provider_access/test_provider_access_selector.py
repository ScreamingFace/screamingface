"""`Selector` — the ONE interpretation point for `X-Profile` (OME-1200, spec §3.2 / §3.6).

# INVARIANT: absent, blank and whitespace-only headers all mean the default selector and are
# NOT explicit; any other value is refused here at the parse step and nowhere else —
# implementations never see a named selector (Stage D sunset; the compatibility-window policy
# retired in the OME-1138 close-out, L4a).
"""

from __future__ import annotations

import pytest

from aigateway.core.provider_access import (
    DEFAULT_SELECTOR_NAME,
    Selector,
    SelectorUnsupported,
)


@pytest.mark.parametrize("raw", [None, "", "   ", "\t", " \t "])
def test_absent_and_blank_headers_are_the_implicit_default(raw: str | None) -> None:
    selector = Selector.from_header(raw)

    assert selector == Selector(DEFAULT_SELECTOR_NAME, explicit=False)
    assert selector.is_default


def test_selectors_are_immutable_values() -> None:
    selector = Selector.from_header(None)

    with pytest.raises(AttributeError):
        setattr(selector, "name", "other")
    assert hash(selector) == hash(Selector(DEFAULT_SELECTOR_NAME, explicit=False))


# --- the sunset (Stage D): every present selector is refused ----------------------------------


@pytest.mark.parametrize("raw", ["work", " personal ", "default", "\tw\t"])
def test_every_present_selector_is_refused(raw: str) -> None:
    """# WHY a literal `default` is refused too: admitting it needs the D4 equivalence proof
    (spec §3.6) — an owner decision, not an implementation default."""
    with pytest.raises(SelectorUnsupported) as info:
        Selector.from_header(raw)

    assert raw.strip() not in str(info.value)
    assert not hasattr(info.value, "requested")
