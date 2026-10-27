"""Run actions must remain available inside the table at every responsive breakpoint.

This stylesheet contract complements the rendered-button Node tests. Descend into media
rules so a narrow-screen override cannot silently hide otherwise-correct rendered actions.
"""

from collections.abc import Iterable, Iterator
from pathlib import Path

import tinycss2
from tinycss2 import ast

PORTAL = Path(__file__).resolve().parents[2] / "portal"


def _style_rules(nodes: Iterable[ast.Node]) -> Iterator[ast.QualifiedRule]:
    for node in nodes:
        if isinstance(node, ast.QualifiedRule):
            yield node
        elif isinstance(node, ast.AtRule) and node.content is not None:
            yield from _style_rules(
                tinycss2.parse_rule_list(node.content, skip_comments=True, skip_whitespace=True)
            )


def test_run_actions_are_not_hidden_by_responsive_styles() -> None:
    for stylesheet in PORTAL.glob("*.css"):
        rules = tinycss2.parse_stylesheet(
            stylesheet.read_text(encoding="utf-8"), skip_comments=True, skip_whitespace=True
        )
        for rule in _style_rules(rules):
            selector = tinycss2.serialize(rule.prelude)
            if ".col-run" not in selector and ".run-actions" not in selector:
                continue
            for declaration in tinycss2.parse_declaration_list(rule.content):
                if not isinstance(declaration, ast.Declaration):
                    continue
                value = tinycss2.serialize(declaration.value).strip().lower()
                assert (declaration.lower_name, value) not in {
                    ("display", "none"),
                    ("visibility", "hidden"),
                    ("visibility", "collapse"),
                    ("content-visibility", "hidden"),
                    ("opacity", "0"),
                }, f"{stylesheet.name}: {selector.strip()} hides the Run actions"
