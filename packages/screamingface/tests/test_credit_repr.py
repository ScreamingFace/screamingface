"""`sf.credits()` renders a static credit card in a notebook (OME-1935).

FEATURE: E5 P3 follow-on — the `CreditStatus` that `sf.credits()`, `Client.credits()` and
`AsyncClient.credits()` return displays as the connection panel's credit card.

STORY: as a researcher in a notebook, I run `sf.credits()` and read my balance and
allowance at a glance, with the reason when one is unavailable.

The HTML is parsed and each assertion reads one element's exact text or classes, never a
substring of the markup (amounts and timestamps vary).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from html.parser import HTMLParser

import pytest

from screamingface.credit import CreditAmount, CreditStatus

_AS_OF = datetime(2026, 11, 17, 9, 30, tzinfo=UTC)


@dataclass
class _Element:
    tag: str
    classes: frozenset[str]
    text: str = ""


@dataclass
class _Markup(HTMLParser):
    """Every element with a class, its classes and its own text, in document order."""

    elements: list[_Element] = field(default_factory=list)
    _open: list[_Element] = field(default_factory=list)

    def __post_init__(self) -> None:
        HTMLParser.__init__(self)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = frozenset((dict(attrs).get("class") or "").split())
        element = _Element(tag, classes)
        if tag != "style":
            self.elements.append(element)
        self._open.append(element)

    def handle_endtag(self, tag: str) -> None:
        if self._open:
            self._open.pop()

    def handle_data(self, data: str) -> None:
        if self._open and self._open[-1].tag != "style":
            self._open[-1].text += data

    def texts(self, css_class: str) -> list[str]:
        return [element.text for element in self.elements if css_class in element.classes]


def _parse(markup: str) -> _Markup:
    parser = _Markup()
    parser.feed(markup)
    return parser


def _available(amount: str) -> CreditAmount:
    return CreditAmount("available", Decimal(amount), _AS_OF)


def _unavailable(reason: str) -> CreditAmount:
    return CreditAmount("unavailable", reason=reason)


def _byok(account: CreditAmount, key: CreditAmount) -> CreditStatus:
    return CreditStatus(
        "openrouter", account, key, _unavailable("hosted_unavailable"), "a" * 64, True
    )


def _hosted(allowance: CreditAmount) -> CreditStatus:
    hidden = _unavailable("hosted_unavailable")
    return CreditStatus("openrouter", hidden, allowance, allowance, "a" * 64, False)


def test_byok_card_shows_account_balance_first_and_key_allowance_beside_it() -> None:
    card = _parse(_byok(_available("24.5"), _available("80"))._repr_html_())

    assert card.texts("sf-credits__label") == ["Account balance", "Key allowance"]
    assert card.texts("sf-credits__value") == ["$24.50", "$80.00"]
    assert card.texts("sf-credits__stamp") == ["Checked 2026-11-17 09:30 UTC"] * 2
    assert card.texts("sf-credits__help") == [
        "Key allowance is a spending cap, not additional credit."
    ]


def test_hosted_card_shows_one_allowance_and_never_the_account() -> None:
    card = _parse(_hosted(_available("12.4"))._repr_html_())

    assert card.texts("sf-credits__label") == ["Hosted allowance"]
    assert card.texts("sf-credits__value") == ["$12.40"]


def test_stale_amount_keeps_its_last_value_and_says_so() -> None:
    stale = CreditAmount("stale", Decimal("3"), _AS_OF, "lookup_failed")
    card = _parse(_byok(stale, _available("80"))._repr_html_())

    assert card.texts("sf-credits__value")[0] == "$3.00"
    assert card.texts("sf-credits__note")[0] == "Refresh failed · last known value"


def test_unlimited_key_says_no_key_limit() -> None:
    unlimited = CreditAmount("unlimited", as_of=_AS_OF)
    card = _parse(_byok(_available("24.5"), unlimited)._repr_html_())

    assert card.texts("sf-credits__value")[1] == "No key limit"


@pytest.mark.parametrize(
    ("reason", "label"),
    [
        ("not_connected", "Not connected"),
        ("credential_rejected", "Key rejected"),
        ("lookup_failed", "Lookup failed"),
        ("unsupported", "Not supported"),
        ("invalid_response", "Unreadable response"),
    ],
)
def test_an_unavailable_amount_says_why(reason: str, label: str) -> None:
    # INVARIANT: an unavailable amount names its cause; a known amount beside it stays visible.
    card = _parse(_byok(_unavailable(reason), _available("80"))._repr_html_())

    assert card.texts("sf-credits__value") == ["Unavailable", "$80.00"]
    assert card.texts("sf-credits__note")[0] == label


@pytest.mark.parametrize(
    ("reason", "note"),
    [
        (
            "management_key_required",
            "Add a management key in account settings to see this balance.",
        ),
        ("account_unverified", "Account association could not be verified."),
    ],
)
def test_management_key_and_unverified_notes_are_unchanged(reason: str, note: str) -> None:
    card = _parse(_byok(_unavailable(reason), _available("80"))._repr_html_())

    assert card.texts("sf-credits__note")[0] == note


def test_nothing_known_renders_one_neutral_unavailable_box() -> None:
    # WHY: a failed lookup loses the hosted marker, so the card must not guess the layout.
    failed = CreditStatus(
        "openrouter",
        _unavailable("lookup_failed"),
        _unavailable("lookup_failed"),
        _unavailable("hosted_unavailable"),
    )
    card = _parse(failed._repr_html_())

    assert card.texts("sf-credits__label") == ["Credits unavailable"]
    assert card.texts("sf-credits__value") == ["Unavailable"]
    assert card.texts("sf-credits__note") == ["Lookup failed"]
    assert card.texts("sf-credits__help") == []


def test_a_partial_failure_keeps_the_known_amount() -> None:
    card = _parse(_byok(_unavailable("lookup_failed"), _available("12.4"))._repr_html_())

    assert card.texts("sf-credits__label") == ["Account balance", "Key allowance"]
    assert card.texts("sf-credits__value") == ["Unavailable", "$12.40"]


def test_card_root_carries_the_theme_and_no_maths_classes() -> None:
    # INVARIANT (OME-1226): `$` amounts must never be typeset as maths, and the `--sf-*`
    # theme tokens must apply outside the connection panel.
    card = _parse(_byok(_available("24.5"), _available("80"))._repr_html_())

    assert {"sf-ui", "mathjax_ignore", "tex2jax_ignore"} <= card.elements[0].classes


def test_panel_shares_the_reason_labels() -> None:
    from screamingface._ui.credit_view import credit_html

    panel = _parse(
        credit_html(_byok(_available("24.5"), _unavailable("credential_rejected")), hosted=False)
    )

    assert panel.texts("sf-credits__note")[1] == "Key rejected"


def test_panel_never_uses_the_neutral_box_when_it_knows_the_mode() -> None:
    from screamingface._ui.credit_view import credit_html

    failed = _byok(_unavailable("lookup_failed"), _unavailable("lookup_failed"))
    panel = _parse(credit_html(failed, hosted=False))

    assert panel.texts("sf-credits__label") == ["Account balance", "Key allowance"]


# Independent review of PR #1883 (OME-1935): the shapes below reach the SDK in practice.


@pytest.mark.parametrize(
    ("account_reason", "note"),
    [
        (
            "management_key_required",
            "Add a management key in account settings to see this balance.",
        ),
        ("account_unverified", "Account association could not be verified."),
    ],
)
def test_neutral_box_keeps_the_account_note_the_user_can_act_on(
    account_reason: str, note: str
) -> None:
    # WHY: OpenRouter can answer `/key` without `limit_remaining`; the key is then
    # unreadable, and the management-key hint is the only actionable thing to say.
    status = _byok(_unavailable(account_reason), _unavailable("invalid_response"))
    card = _parse(status._repr_html_())

    assert card.texts("sf-credits__label") == ["Credits unavailable"]
    assert card.texts("sf-credits__note") == [note]


def test_the_sdk_failed_lookup_result_renders_the_neutral_box() -> None:
    from screamingface.credit import _unavailable as sdk_unavailable

    card = _parse(sdk_unavailable("openrouter")._repr_html_())

    assert card.texts("sf-credits__label") == ["Credits unavailable"]
    assert card.texts("sf-credits__note") == ["Lookup failed"]


@pytest.mark.parametrize(
    ("reason", "label"), [("not_connected", "Not connected"), ("unsupported", "Not supported")]
)
def test_gateway_wide_unavailable_results_render_the_neutral_box(reason: str, label: str) -> None:
    # The Gateway leaves `hosted` at its default `hosted_unavailable` for these.
    status = CreditStatus(
        "openrouter", _unavailable(reason), _unavailable(reason), _unavailable("hosted_unavailable")
    )
    card = _parse(status._repr_html_())

    assert card.texts("sf-credits__label") == ["Credits unavailable"]
    assert card.texts("sf-credits__note") == [label]


def test_hosted_with_a_failed_key_lookup_keeps_the_hosted_layout() -> None:
    card = _parse(_hosted(_unavailable("lookup_failed"))._repr_html_())

    assert card.texts("sf-credits__label") == ["Hosted allowance"]
    assert card.texts("sf-credits__note") == ["Lookup failed"]


def test_hosted_allowance_without_a_reading_says_so() -> None:
    # The Engine reports `hosted_unavailable` with no job identity, or for a hosted key
    # with no per-key limit.
    card = _parse(_hosted(_unavailable("hosted_unavailable"))._repr_html_())

    assert card.texts("sf-credits__value") == ["Unavailable"]
    assert card.texts("sf-credits__note") == ["Not available on hosted"]


def test_hosted_panel_keeps_its_layout_when_every_amount_is_unavailable() -> None:
    from screamingface._ui.credit_view import credit_html

    failed = _byok(_unavailable("lookup_failed"), _unavailable("lookup_failed"))
    panel = _parse(credit_html(failed, hosted=True))

    assert panel.texts("sf-credits__label") == ["Hosted allowance"]
