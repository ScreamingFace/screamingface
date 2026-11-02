"""Every judged Benchmark's pinned judge settings must pass aigateway's rules for its provider.

A judged row pins its judge's settings (`JudgeSpec.params`), and every judge call goes through
the gateway, which refuses a setting its provider has no rule for, or a value outside the
rule's schema, with a 400 before dispatch. The tests that grade a row use a fake judge that
accepts anything, so a refused setting slipped through: air_bench first pinned
`reasoning_effort=none`, which the gateway refuses on OpenRouter (only low, medium and high are
proven there, OME-993). A run would have paid for 5,694 Candidate calls and then failed every
judge call (review finding on OME-1602, 2026-10-19).

The rules are read from aigateway's source with `ast`, never imported: aigateway is a separate
uv project and is not installed here (the same approach as
`test_declared_models_match_aigateway.py`). What it checks is the literal rule list and the
literal `reasoning_effort` ladder, which is exactly what a judge row drifts from.
"""

from __future__ import annotations

import ast
from pathlib import Path

from screamingface_engine_inspect.benchmarks import BENCHMARKS

_REPO_ROOT = Path(__file__).resolve().parents[4]
_OPENROUTER_RULES = (
    _REPO_ROOT / "apps/aigateway/src/aigateway/plugins/openrouter_provider/parameters.py"
)
#: The only provider our judges route through today; a judge on another one fails the test
#: below by name, so the check is extended rather than silently skipped.
_OPENROUTER_PREFIX = "openrouter/"


def _openrouter_rule_names() -> set[str]:
    """The caller-facing names of the gateway's `direct_rule(...)` entries for OpenRouter."""

    tree: ast.Module = ast.parse(_OPENROUTER_RULES.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "direct_rule"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            names.add(node.args[0].value)
    return names


def _openrouter_reasoning_efforts() -> set[str]:
    """The `enum=` ladder of `OPENROUTER_REASONING_EFFORT_SCHEMA`, as the gateway spells it."""

    tree: ast.Module = ast.parse(_OPENROUTER_RULES.read_text())
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "OPENROUTER_REASONING_EFFORT_SCHEMA"
                for target in node.targets
            )
            and isinstance(node.value, ast.Call)
        ):
            for keyword in node.value.keywords:
                if keyword.arg == "enum" and isinstance(keyword.value, ast.Tuple):
                    return {
                        element.value
                        for element in keyword.value.elts
                        if isinstance(element, ast.Constant) and isinstance(element.value, str)
                    }
    raise AssertionError(
        f"OPENROUTER_REASONING_EFFORT_SCHEMA's enum not found in {_OPENROUTER_RULES}"
    )


def test_the_gateway_source_still_holds_what_this_check_reads() -> None:
    # WHY: an empty read would make the next test pass everything. These are the names the
    # check relies on today; if aigateway renames them, this fails first and says where.
    assert {
        "max_tokens",
        "temperature",
        "reasoning_effort",
        "web_search",
    } <= _openrouter_rule_names()
    assert _openrouter_reasoning_efforts() == {"low", "medium", "high"}


def test_every_judges_pinned_settings_pass_the_gateways_openrouter_rules() -> None:
    rule_names: set[str] = _openrouter_rule_names()
    efforts: set[str] = _openrouter_reasoning_efforts()
    problems: list[str] = []
    for spec in BENCHMARKS:
        if spec.judge is None:
            continue
        if not spec.judge.model.startswith(_OPENROUTER_PREFIX):
            problems.append(
                f"{spec.key}: judge {spec.judge.model!r} is not on OpenRouter; extend this "
                "check to its provider's rules before pinning it"
            )
            continue
        for name, value in spec.judge.params:
            if name not in rule_names:
                problems.append(f"{spec.key}: the gateway has no OpenRouter rule for {name!r}")
            elif name == "reasoning_effort" and value not in efforts:
                problems.append(
                    f"{spec.key}: reasoning_effort={value!r}; the gateway accepts only "
                    f"{sorted(efforts)} on OpenRouter"
                )
    assert not problems, "\n".join(problems)
