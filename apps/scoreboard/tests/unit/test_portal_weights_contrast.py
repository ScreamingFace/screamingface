"""OME-1425: the leaderboard's "Closed weights" label meets WCAG AA in both themes.

The label sat on the vendored SFDS `.status:not(.on)` whisper tone, 2.77:1 on the light
background. The portal now gives closed rows their own rule at full `--ink-2`, and both
modifier rules out-rank the base off-state by specificity rather than by load order.

The stylesheets are parsed with tinycss2 and the rules compared by their parsed selector and
declarations, not by searching the CSS text.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import tinycss2
from tinycss2 import ast

PORTAL = Path(__file__).resolve().parents[2] / "portal"
LIGHT_BLOCK = ':root, [data-theme="light"]'
DARK_BLOCK = '[data-theme="dark"]'
BASE_OFF_STATE = ".status:not(.on)"
OPEN_RULE = ".status.status--open:not(.on)"
CLOSED_RULE = ".status.status--closed:not(.on)"
AA_NORMAL_TEXT = 4.5


def _rules(stylesheet: str) -> dict[str, list[ast.Declaration]]:
    """Map each top-level rule's selector text to its declarations."""
    path = PORTAL / stylesheet
    parsed = tinycss2.parse_stylesheet(
        path.read_text(encoding="utf-8"), skip_comments=True, skip_whitespace=True
    )
    rules: dict[str, list[ast.Declaration]] = {}
    for node in parsed:
        if isinstance(node, ast.QualifiedRule):
            selector = tinycss2.serialize(node.prelude).strip()
            body = tinycss2.parse_blocks_contents(
                node.content, skip_comments=True, skip_whitespace=True
            )
            declarations = [d for d in body if isinstance(d, ast.Declaration)]
            rules.setdefault(selector, []).extend(declarations)
    return rules


def _value(declarations: list[ast.Declaration], name: str) -> str:
    matches = [d for d in declarations if d.lower_name == name]
    assert len(matches) == 1, f"expected one {name} declaration, found {len(matches)}"
    return tinycss2.serialize(matches[0].value).strip()


def _specificity(selector: str) -> tuple[int, int, int]:
    """(ids, classes + pseudo-classes, types) for one compound selector."""
    return _specificity_of(tinycss2.parse_component_value_list(selector))


def _specificity_of(tokens: list[ast.Node]) -> tuple[int, int, int]:
    ids = classes = types = 0
    previous: ast.Node | None = None
    for token in tokens:
        after_marker = isinstance(previous, ast.LiteralToken) and previous.value in {".", ":"}
        if isinstance(token, ast.HashToken):
            ids += 1
        elif isinstance(token, ast.IdentToken):
            if after_marker:
                classes += 1
            else:
                types += 1
        elif isinstance(token, ast.FunctionBlock) and token.lower_name == "not":
            inner = _specificity_of(token.arguments)
            ids, classes, types = ids + inner[0], classes + inner[1], types + inner[2]
        previous = token
    return ids, classes, types


def _theme_tokens(block: str) -> dict[str, str]:
    """Custom properties for one theme: the light block, overlaid by `block`."""
    rules = _rules("tokens.css")
    merged: dict[str, str] = {}
    for selector in dict.fromkeys([LIGHT_BLOCK, block]):
        for declaration in rules[selector]:
            if declaration.name.startswith("--"):
                merged[declaration.name] = tinycss2.serialize(declaration.value).strip()
    return merged


def _resolve(tokens: dict[str, str], name: str) -> tuple[int, int, int]:
    """Follow var() references to a #rrggbb colour."""
    value = tinycss2.parse_one_component_value(tokens[name])
    if isinstance(value, ast.FunctionBlock) and value.lower_name == "var":
        target = next(a for a in value.arguments if isinstance(a, ast.IdentToken))
        return _resolve(tokens, target.value)
    assert isinstance(value, ast.HashToken), f"{name} is not a hex colour: {tokens[name]}"
    digits = value.value
    assert len(digits) == 6, f"{name} is not #rrggbb: {tokens[name]}"
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_closed_weights_text_uses_full_ink_2() -> None:
    rules = _rules("portal.css")
    assert CLOSED_RULE in rules
    assert _value(rules[CLOSED_RULE], "color") == "var(--ink-2)"


def test_open_weights_keeps_full_ink_text_and_square() -> None:
    rules = _rules("portal.css")
    assert _value(rules[OPEN_RULE], "color") == "var(--ink)"
    assert _value(rules[".status.status--open .sq"], "background") == "var(--ink)"


def test_the_vendored_off_state_is_left_untouched() -> None:
    rules = _rules("style.css")
    assert _value(rules[BASE_OFF_STATE], "color") == (
        "color-mix(in oklch, var(--ink-2) 64%, transparent)"
    )


@pytest.mark.parametrize("selector", [OPEN_RULE, CLOSED_RULE])
def test_weights_rules_outrank_the_off_state_by_specificity(selector: str) -> None:
    assert _specificity(selector) > _specificity(BASE_OFF_STATE)


@pytest.mark.parametrize("theme", [LIGHT_BLOCK, DARK_BLOCK])
@pytest.mark.parametrize("background", ["--bg", "--surface"])
def test_closed_weights_text_meets_aa(theme: str, background: str) -> None:
    tokens = _theme_tokens(theme)
    ratio = _contrast(_resolve(tokens, "--ink-2"), _resolve(tokens, background))
    assert ratio >= AA_NORMAL_TEXT, f"{theme} {background}: {ratio:.2f}:1"
