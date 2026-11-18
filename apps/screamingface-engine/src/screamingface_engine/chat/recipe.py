"""The chat recipe check: the model value rule, the final positions and the re-point.

The model value of a chat request is a URL4 recipe or a gateway model id (CC-S1, plan decision
D4). The check finds each final position of a recipe (prd/tool-calls.md §3.1) and refuses the
recipes that the chat route cannot run (CC-S13, CC-S14, TC-S7 to TC-S9, TC-S22, TC-S23). With
tools, the run moves each final model step to the final-step route (prd/tool-calls.md §3.2).

This is the only chat module that may import the url4 engine (plan decision D7). It reads the
structure of the recipe only; it never reads the `_sf_recipe` descriptor, which a client recipe
can omit or fake.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from screamingface_engine.benchmarks.operation_outputs import parsed_iterate_body
from screamingface_engine.benchmarks.picture_admission import _candidate_recipes
from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from url4.core.errors import Url4Error
from url4.core.nodes import Expression, Iteration, Node, RelExpr, Source, Text, VarRef, walk
from url4.core.parser import build
from url4.core.render import render

__all__ = [
    "CHAT_ROUTE_PREFIX",
    "FINAL_STEP_NOT_MODEL_MESSAGE",
    "FINAL_STEP_ROUTE",
    "LINKED_EXPRESSION_MESSAGE",
    "CheckedRecipe",
    "FinalPosition",
    "PositionKind",
    "RecipeRefusal",
    "RefusalCode",
    "RepointError",
    "check_recipe",
    "final_positions",
    "is_recipe_value",
    "one_model_recipe",
    "repoint_final_steps",
]

CHAT_ROUTE_PREFIX = "/ensemble/chat/v1/"
FINAL_STEP_ROUTE = "/ensemble/chat/v1/final"

FINAL_STEP_NOT_MODEL_MESSAGE = (
    "With tools, the last step of the recipe must be a model step. Add a final model stage, "
    "for example cascade >> model."
)
LINKED_EXPRESSION_MESSAGE = (
    "the model value is a benchmark-linked expression; send the Candidate URL4 as the model"
)
_INVALID_MESSAGE = "the model value is not a valid URL4 recipe"
_NO_FINAL_FORM_MESSAGE = "the final form of the recipe is not known"
_DANGLING_MESSAGE = "the recipe names a final step that it does not define"
_CHAT_ROUTE_MESSAGE = "the recipe names a route that only the Engine may use"
_LOOP_MESSAGE = "a corrective loop needs a Benchmark; the chat route does not run it"
_UNKNOWN_MESSAGE = "with tools, the check cannot find the last step of the recipe"

RefusalCode = Literal["recipe_invalid", "recipe_not_supported", "final_step_not_model"]
PositionKind = Literal["model", "reducer", "step", "outcome", "loop", "unknown"]

_REFERENCE = re.compile(r"\$([A-Za-z0-9_]+)")
# WHY: in lock-step with FINAL_BINDING of packages/screamingface/src/screamingface/
# _operation_bindings.py, the final forms that the SDK writes as the root intent;
# test_final_binding_is_in_lock_step_with_the_sdk binds the two.
_FINAL_BINDING = re.compile(r"model_\d+|synthesis_\d+|loop_candidate|gate_\d+_block")
_STEP_BINDING = re.compile(r"model_\d+|synthesis_\d+")
_GATE_BLOCK = re.compile(r"gate_(\d+)_block")
_LOOP_BINDING = "loop_candidate"
_OUTCOMES = frozenset({"abstain", "fail_closed", "skip"})

type _Groups = dict[tuple[str, ...], frozenset[str]]
type _Flat = dict[tuple[tuple[str, ...], str], Node]


class RecipeRefusal(ValueError):
    """The chat route refuses the recipe. The message never echoes recipe text."""

    def __init__(self, code: RefusalCode, message: str) -> None:
        super().__init__(message)
        self.code: RefusalCode = code
        self.message = message


class RepointError(ValueError):
    """The re-point could not prove that its copy changed only the selected steps."""


@dataclass(frozen=True)
class FinalPosition:
    """One place whose output can be the answer of the recipe (prd/tool-calls.md §3.1)."""

    kind: PositionKind
    binding: str | None
    scope: tuple[str, ...]
    route: str | None


@dataclass(frozen=True)
class CheckedRecipe:
    """A parsed recipe that passed the check, with its final positions."""

    root: Expression
    positions: tuple[FinalPosition, ...]


def is_recipe_value(model: str) -> bool:
    """CC-S1: a value that starts with "(" after white space is a URL4; else a model id."""

    return model.lstrip().startswith("(")


def one_model_recipe(model_id: str) -> str:
    """D4: the one-model recipe that runs a gateway model id on its route."""

    if not model_id or "~" in model_id or model_id.startswith("/"):
        raise ValueError("the model id is not a route path")
    if "" in model_id.split("/"):
        raise ValueError("the model id has an empty path segment")
    # WHY: this is encode_route_id of world/models/registry.py, which a shared leaf cannot import.
    route = model_id.replace(":", "~")
    text = f"(model_1:0.0:/{route}($input)!'')!'$model_1'"
    if not _is_one_model_tree(text, "/" + route):
        raise ValueError("the model id does not give a one-model recipe")
    return text


def _is_one_model_tree(text: str, path: str) -> bool:
    try:
        root = build(text)
    except Url4Error:
        return False
    expected = Source(
        value=RelExpr(path=path, context="$input", intent=Text("")), name="model_1", weight=0.0
    )
    return isinstance(root, Expression) and root.sources == (expected,)


def final_positions(root: Expression) -> tuple[FinalPosition, ...]:
    """tool-calls §3.1: every final position of the recipe. It never raises."""

    name = _root_final_name(root)
    if name is None:
        return (FinalPosition("unknown", None, (), None),)
    return tuple(_classify(root, name, ()))


def check_recipe(expression: str, *, with_tools: bool) -> CheckedRecipe:
    """Parse and check a client recipe; raise RecipeRefusal when the chat route cannot run it.

    The order: the chat route prefix (TC-S23), the parse, a benchmark-linked root (CC-S15), the
    final form (CC-S13), a corrective loop (CC-S14), and with tools only, a reducer or step final
    (TC-S7, TC-S22) and then an unknown final (TC-S9). Without tools, the other finals run as built.
    """

    # WHY: a text test, not a walk of the parsed paths, so it also finds the prefix in a body that
    # does not parse; a prompt that only quotes the prefix is refused too (TC-S23 fails closed).
    if CHAT_ROUTE_PREFIX in expression:
        raise RecipeRefusal("recipe_not_supported", _CHAT_ROUTE_MESSAGE)
    root = _parse(expression)
    # WHY the scan of picture admission: one rule for a top-level `candidate` Text source
    # (CC-S15), the Candidate URL4 of a benchmark-linked expression.
    if _candidate_recipes(expression):
        raise RecipeRefusal("recipe_invalid", LINKED_EXPRESSION_MESSAGE)
    name = _root_final_name(root)
    if name is None:
        raise RecipeRefusal("recipe_invalid", _NO_FINAL_FORM_MESSAGE)
    # WHY: CC-S13 is the form of the root, so a name with no root source is invalid, tools or not.
    # TC-S9 is a real source that the check cannot classify: refused with tools, else run as built.
    if _find_source(root, name) is None:
        raise RecipeRefusal("recipe_invalid", _DANGLING_MESSAGE)
    positions = tuple(_classify(root, name, ()))
    kinds: set[PositionKind] = {position.kind for position in positions}
    if "loop" in kinds or _has_loop(root):
        raise RecipeRefusal("recipe_not_supported", _LOOP_MESSAGE)
    if with_tools:
        _check_tool_kinds(kinds)
    return CheckedRecipe(root, positions)


def _has_loop(expr: Expression) -> bool:
    """CC-S14: a corrective loop at any depth, Gate branch bodies included."""

    return any(_is_loop(node) for node in walk(expr))


def _is_loop(node: Node) -> bool:
    """A loop source, or a branch body that holds one; a body that does not parse is not read."""

    if isinstance(node, Source) and node.name == _LOOP_BINDING:
        return True
    body = parsed_iterate_body(node) if isinstance(node, Iteration) else None
    return body is not None and _has_loop(body)


def _parse(expression: str) -> Expression:
    try:
        root = build(expression)
    except Url4Error as exc:
        raise RecipeRefusal("recipe_invalid", _INVALID_MESSAGE) from exc
    if not isinstance(root, Expression):
        raise RecipeRefusal("recipe_invalid", _INVALID_MESSAGE)
    return root


def _check_tool_kinds(kinds: set[PositionKind]) -> None:
    if kinds & {"reducer", "step"}:
        raise RecipeRefusal("final_step_not_model", FINAL_STEP_NOT_MODEL_MESSAGE)
    if "unknown" in kinds:
        raise RecipeRefusal("recipe_not_supported", _UNKNOWN_MESSAGE)


def _reference(intent: Node | None) -> str | None:
    """The name that an intent refers to: a quoted `$name` text or a plain `$name`."""

    if isinstance(intent, VarRef):
        return intent.name if not intent.path else None
    match = _REFERENCE.fullmatch(intent.value) if isinstance(intent, Text) else None
    return match.group(1) if match else None


def _root_final_name(root: Expression) -> str | None:
    name = _reference(root.intent)
    return name if name is not None and _FINAL_BINDING.fullmatch(name) else None


def _find_source(expr: Expression, name: str) -> Source | None:
    return next(
        (node for node in expr.sources if isinstance(node, Source) and node.name == name), None
    )


def _unknown(name: str | None, scope: tuple[str, ...]) -> FinalPosition:
    return FinalPosition("unknown", name, scope, None)


def _classify(expr: Expression, name: str, scope: tuple[str, ...]) -> list[FinalPosition]:
    """The final positions behind one name in one scope (tool-calls §3.1, row by row)."""

    source = _find_source(expr, name)
    if name == _LOOP_BINDING:
        positions = [FinalPosition("loop", _LOOP_BINDING, scope, None)]
    elif source is None:
        positions = [_unknown(name, scope)]
    elif _STEP_BINDING.fullmatch(name):
        positions = [_step_position(source.value, name, scope)]
    else:
        positions = _gate_positions(source, name, scope)
    return positions


def _step_position(value: Node, name: str, scope: tuple[str, ...]) -> FinalPosition:
    """A model or synthesis step: a model route, a reducer on the combine route, or unknown."""

    position = _unknown(name, scope)
    if not isinstance(value, RelExpr):
        return position
    if value.path == COMBINE_ROUTE:
        if name.startswith("synthesis_"):
            position = FinalPosition("reducer", name, scope, None)
    elif value.path.startswith(FINAL_STEP_ROUTE + "/") or not value.path.startswith("/ensemble/"):
        # WHY: a path under the final-step route is a model step of the run's own re-pointed
        # copy (TC-31); check_recipe refuses that prefix in a client recipe before this point.
        position = FinalPosition("model", name, scope, value.path)
    return position


def _gate_positions(source: Source, name: str, scope: tuple[str, ...]) -> list[FinalPosition]:
    """Each branch of a Gate block, read from its gate spec; one unknown when it cannot be read."""

    match = _GATE_BLOCK.fullmatch(name)
    block = source.value
    spec = _gate_spec(block, match.group(1)) if match and isinstance(block, Expression) else None
    if match is None or spec is None or not isinstance(block, Expression):
        return [_unknown(name, scope)]
    inner = (*scope, name)
    number = match.group(1)
    positions: list[FinalPosition] = []
    for branch, body_name in (
        ("then", f"gate_{number}_then"),
        ("otherwise", f"gate_{number}_else"),
    ):
        positions.extend(_branch_positions(block, spec, branch, body_name, inner))
    return positions


def _gate_spec(block: Expression, number: str) -> dict[str, Any] | None:
    decide = _find_source(block, f"gate_{number}_decide")
    value = decide.value if decide is not None else None
    if not isinstance(value, RelExpr) or not isinstance(value.intent, Text):
        return None
    try:
        spec = json.loads(value.intent.value)
    except ValueError:
        return None
    return spec if isinstance(spec, dict) else None


def _branch_positions(
    block: Expression, spec: dict[str, Any], branch: str, body_name: str, scope: tuple[str, ...]
) -> list[FinalPosition]:
    kind = spec.get(branch)
    if kind in _OUTCOMES:
        positions = [FinalPosition("outcome", None, scope, None)]
    elif kind == "step":
        positions = [FinalPosition("step", _terminal(spec, branch), scope, None)]
    elif kind == "recipe":
        positions = _recipe_branch(block, body_name, scope)
    else:
        positions = [_unknown(None, scope)]
    return positions


def _terminal(spec: dict[str, Any], branch: str) -> str | None:
    terminal = spec.get("terminal")
    binding = terminal.get(branch) if isinstance(terminal, dict) else None
    return binding if isinstance(binding, str) else None


def _recipe_branch(
    block: Expression, body_name: str, scope: tuple[str, ...]
) -> list[FinalPosition]:
    """A recipe branch: parse its body (tool-calls §3.2 step 2) and classify it again."""

    body_source = _find_source(block, body_name)
    iteration = body_source.value if body_source is not None else None
    body = parsed_iterate_body(iteration) if isinstance(iteration, Iteration) else None
    name = _reference(body.intent) if body is not None else None
    if body is None or name is None:
        return [_unknown(body_name, scope)]
    return _classify(body, name, (*scope, body_name))


def repoint_final_steps(root: Expression, positions: Sequence[FinalPosition]) -> str:
    """tool-calls §3.2 steps 1-5: the text of the run's copy with each final model re-pointed.

    Each selected source is found by its binding name and scope, never by its path. Its path
    gets the final-step prefix and it gets a `binding` parameter when it has none. The copy must
    parse back to the same tree, and only the selected sources may differ; else RepointError.
    """

    groups = _group(positions)
    try:
        new_root = _repoint_scope(root, (), groups)
        text = render(new_root)
        _prove(root, new_root, text, groups)
    except Url4Error as exc:
        raise RepointError("the re-pointed recipe does not round-trip") from exc
    return text


def _group(positions: Sequence[FinalPosition]) -> _Groups:
    groups: dict[tuple[str, ...], set[str]] = {}
    for position in positions:
        if position.kind != "model" or position.binding is None or position.route is None:
            raise RepointError("only a model step can move to the final-step route")
        groups.setdefault(position.scope, set()).add(position.binding)
    return {scope: frozenset(names) for scope, names in groups.items()}


def _repoint_scope(expr: Expression, scope: tuple[str, ...], groups: _Groups) -> Expression:
    selected = groups.get(scope, frozenset())
    depth = len(scope)
    deeper = {key[depth] for key in groups if len(key) > depth and key[:depth] == scope}
    sources = tuple(_repoint_source(node, scope, selected, deeper, groups) for node in expr.sources)
    return replace(expr, sources=sources)


def _repoint_source(
    node: Node,
    scope: tuple[str, ...],
    selected: frozenset[str],
    deeper: set[str],
    groups: _Groups,
) -> Node:
    name = node.name if isinstance(node, Source) else None
    if isinstance(node, Source) and name is not None and name in selected:
        node = replace(node, value=_final_step(node.value, name))
    elif isinstance(node, Source) and name is not None and name in deeper:
        node = replace(node, value=_descend(node.value, (*scope, name), groups))
    return node


def _final_step(value: Node, binding: str) -> RelExpr:
    if not isinstance(value, RelExpr):
        raise RepointError("a selected step is not a model call")
    has_binding = any(key == "binding" for key, _ in value.params)
    params = value.params if has_binding else (("binding", binding), *value.params)
    return replace(value, path=FINAL_STEP_ROUTE + value.path, params=params)


def _descend(value: Node, scope: tuple[str, ...], groups: _Groups) -> Node:
    if isinstance(value, Expression):
        return _repoint_scope(value, scope, groups)
    if isinstance(value, Iteration):
        return _repoint_iteration(value, scope, groups)
    raise RepointError("a scope of the recipe is not a block or a branch body")


def _repoint_iteration(iteration: Iteration, scope: tuple[str, ...], groups: _Groups) -> Iteration:
    """Re-point inside a branch body, then write the body text again (tool-calls §3.2 step 5)."""

    body = parsed_iterate_body(iteration)
    if body is None or iteration.intent is None:
        raise RepointError("a branch body does not parse")
    rendered = render(_repoint_scope(body, scope, groups))
    suffix = ")!" + iteration.intent
    if not (rendered.startswith("(") and rendered.endswith(suffix)):
        raise RepointError("a branch body does not render in its own form")
    return replace(iteration, body=rendered[1 : -len(suffix)])


def _prove(root: Expression, new_root: Expression, text: str, groups: _Groups) -> None:
    """The copy parses to the new tree, and only the selected sources changed."""

    if build(text) != new_root:
        raise RepointError("the re-pointed recipe does not parse to the same tree")
    old, new = _flatten(root, ()), _flatten(new_root, ())
    selected = {(scope, name) for scope, names in groups.items() for name in names}
    if old.keys() != new.keys() or not selected <= old.keys():
        raise RepointError("the re-point changed the shape of the recipe")
    for key, before in old.items():
        same = _only_route_changed(before, new[key]) if key in selected else before == new[key]
        if not same:
            raise RepointError("the re-point changed a source that it did not select")


def _only_route_changed(before: Node, after: Node) -> bool:
    if not isinstance(before, Source) or not isinstance(after, Source):
        return False
    old, new = before.value, after.value
    if not isinstance(old, RelExpr) or not isinstance(new, RelExpr):
        return False
    restored = replace(new, path=old.path, params=old.params)
    return new.path == FINAL_STEP_ROUTE + old.path and replace(after, value=restored) == before


def _flatten(expr: Expression, scope: tuple[str, ...]) -> _Flat:
    """Each source by scope and name; a block and a parsed branch body are flattened too."""

    flat: _Flat = {(scope, ""): replace(expr, sources=())}
    for index, node in enumerate(expr.sources):
        name = node.name if isinstance(node, Source) and node.name else f"#{index}"
        flat.update(_flatten_source(node, (*scope, name)))
    return flat


def _flatten_source(node: Node, path: tuple[str, ...]) -> _Flat:
    scope, name = path[:-1], path[-1]
    value = node.value if isinstance(node, Source) else None
    body = parsed_iterate_body(value) if isinstance(value, Iteration) else None
    if isinstance(node, Source) and isinstance(value, Iteration) and body is not None:
        return {(scope, name): replace(node, value=replace(value, body="")), **_flatten(body, path)}
    if isinstance(node, Source) and isinstance(value, Expression):
        return {
            (scope, name): replace(node, value=replace(value, sources=())),
            **_flatten(value, path),
        }
    return {(scope, name): node}
