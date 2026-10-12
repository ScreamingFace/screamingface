"""D-1b in the builders: an intent string ends at an unquoted '!' (Spec B §8).

`expr('a', intent='Answer now!')` is refused, as the parser refuses the same
text, but with a message for builder callers: pass `text(...)` to send a
literal prompt that holds '!'.
"""

from __future__ import annotations

import pytest

from url4 import build, expr, render, text
from url4.core.errors import ParseError


def test_a_builder_intent_with_a_bang_is_refused_with_a_builder_message() -> None:
    with pytest.raises(ParseError, match=r"text\('Answer now!'\)"):
        expr("a", intent="Answer now!")


def test_text_carries_a_literal_bang_and_round_trips() -> None:
    tree = expr("a", intent=text("Answer now!"))
    assert build(render(tree)) == tree
