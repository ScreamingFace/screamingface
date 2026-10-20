"""The unit 7 codemod: move SDK tests from today's recipe classes to the map/select/reduce surface.

Spec: docs/spec/2026-10-20-e4b-mapreduce-surface/prd/swap.md §4 (rules R1-R13). Step 7d runs it
with ``--to sx`` (the private names ``sx.*``, which lower to today's bytes), step 7e with
``--to sf`` (R13). A site it cannot rewrite keeps its text and gets one report line
``file:line: rule: reason``; that file goes to the hand group. Deleted in step 7f.

    uv run python scripts/migrate_surface.py --to sx tests/test_a.py ...
    uv run python scripts/migrate_surface.py --to sf tests/test_a.py ...
    uv run python scripts/migrate_surface.py --audit <base> [--allow FILE] tests/test_a.py ...

``--audit`` compares each file with ``git show <base>:<path>``: per test function, the counts of
``assert`` statements, ``pytest.raises``/``pytest.warns`` calls, and calls of names that start
with ``assert``/``_assert``/``expect``. A lower count or a missing function fails, unless the
allow file lists it (``path::function``, one per line: the group F deletions).
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

SX_IMPORT = "from screamingface import _surface as sx"
_SF_IMPORT = "import screamingface as sf"
_OLD = frozenset(
    {"Fusion", "Pipeline", "Vote", "Median", "Mean", "Pick", "Merge", "Rank", "Filter", "Concat"}
    | {"Judge", "Gate", "Reduce"}
)
_VALUES = _OLD - {"Pipeline", "Merge", "Concat"}  # reported when read as a value
_WRITERS = frozenset({"Model", "Pipeline", "Fusion", "samples"})
_REDUCERS = frozenset({"Vote", "Median", "Mean", "Pick", "Merge", "Rank", "Filter", "Concat"})
# The positional parameters of today's constructors, bound to their names.
_POSITIONAL = {
    "Fusion": ("members",),
    "Pipeline": ("stages",),
    "Pick": ("field",),
    "Rank": ("k",),
    "Concat": ("separator",),
    "Merge": ("fields",),
    "Judge": ("model",),
    "Gate": ("observe", "cmp", "threshold"),
    "Reduce": ("op", "mode"),
}
_FANOUT_OPTIONS = ("members", "signals", "quorum", "name")
_GATE_CMPS = frozenset({">=", ">", "<=", "<"})
_PAREN_PARENTS = (ast.Attribute, ast.Subscript, ast.BinOp, ast.UnaryOp, ast.Await)


class Hand(Exception):
    """A site the codemod cannot rewrite: it keeps its text and goes to the report."""

    def __init__(self, rule: str, reason: str) -> None:
        super().__init__(reason)
        self.rule = rule
        self.reason = reason


@dataclass(frozen=True)
class Migration:
    text: str
    report: list[str]


@dataclass(frozen=True)
class _Conv:
    """A reducer in the new form: its chain parts (a hoisted judge first) and its category."""

    parts: tuple[str, ...]
    narrow: bool = False  # Rank, Filter, Concat: a writer must follow


def _quote(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _call(name: str, positional: Sequence[str] = (), keywords: Sequence[str] = ()) -> str:
    return f"sx.{name}({', '.join([*positional, *keywords])})"


def _constant(node: ast.AST | None) -> object:
    """The value of a literal; None for a missing option; ``...`` for any other expression."""

    if node is None:
        return None
    return node.value if isinstance(node, ast.Constant) else ...


class _Source:
    """Byte offsets of ``ast`` nodes (``col_offset`` counts UTF-8 bytes)."""

    def __init__(self, text: str) -> None:
        self.data = text.encode()
        self._starts = [0]
        for line in self.data.splitlines(keepends=True):
            self._starts.append(self._starts[-1] + len(line))

    def span(self, node: ast.AST) -> tuple[int, int]:
        start = self._starts[node.lineno - 1] + node.col_offset  # type: ignore[attr-defined]
        end = self._starts[node.end_lineno - 1] + node.end_col_offset  # type: ignore[attr-defined]
        return start, end

    def splice(self, start: int, end: int, edits: Sequence[tuple[int, int, str]]) -> str:
        out, cursor = [], start
        for left, right, text in sorted(edits):
            out += [self.data[cursor:left].decode(), text]
            cursor = right
        return "".join([*out, self.data[cursor:end].decode()])


def _tops(node: ast.AST, wanted: Callable[[ast.AST], bool]) -> Iterator[ast.AST]:
    """The top-most descendants of ``node`` that ``wanted`` selects (``node`` excluded)."""

    for child in ast.iter_child_nodes(node):
        if wanted(child):
            yield child
        else:
            yield from _tops(child, wanted)


def _single_values(tree: ast.Module) -> dict[str, ast.expr]:
    """Names with exactly one assignment in the module, and their values."""

    counts = Counter(
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    )
    return {
        node.targets[0].id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and counts[node.targets[0].id] == 1
    }


def _single_returns(tree: ast.Module) -> dict[str, ast.expr]:
    """Module functions with exactly one ``return <value>``, and that value."""

    found: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            returns = [item for item in ast.walk(node) if isinstance(item, ast.Return)]
            if len(returns) == 1 and returns[0].value is not None:
                found[node.name] = returns[0].value
    return found


def _sf_alias(tree: ast.Module) -> str:
    for node in tree.body:
        if isinstance(node, ast.Import):
            for name in node.names:
                if name.name == "screamingface" and name.asname:
                    return name.asname
    return "sf"


class _Rewriter:
    def __init__(self, text: str, path: str) -> None:
        self.src = _Source(text)
        self.tree = ast.parse(text)
        self.path = path
        self.alias = _sf_alias(self.tree)
        self.parents = {
            child: parent
            for parent in ast.walk(self.tree)
            for child in ast.iter_child_nodes(parent)
        }
        self.values = _single_values(self.tree)
        self.returns = _single_returns(self.tree)
        self.report: list[tuple[int, str]] = []

    # ------------------------------------------------------------------ the text of a node

    def run(self) -> str:
        edits = [(*self.src.span(node), self.text(node)) for node in _tops(self.tree, self._target)]
        self._report_values()
        return self.src.splice(0, len(self.src.data), edits)

    def text(self, node: ast.AST) -> str:
        """The new text of ``node``: its old text with every old call inside it rewritten."""

        if not self._target(node):
            return self._inner(node)
        assert isinstance(node, ast.Call)
        try:
            new = self._rewrite(node)
        except Hand as hand:
            self.report.append((node.lineno, f"{hand.rule}: {hand.reason}"))
            return self.src.splice(*self.src.span(node), ())
        return f"({new})" if " >> " in new and self._needs_parens(node) else new

    def _inner(self, node: ast.AST) -> str:
        edits = [(*self.src.span(child), self.text(child)) for child in _tops(node, self._target)]
        return self.src.splice(*self.src.span(node), edits)

    def _needs_parens(self, node: ast.AST) -> bool:
        parent = self.parents.get(node)
        if isinstance(parent, ast.Call):
            return parent.func is node
        return isinstance(parent, _PAREN_PARENTS)

    def _target(self, node: ast.AST) -> bool:
        return isinstance(node, ast.Call) and (self._old(node) is not None or _is_then(node))

    def _old(self, node: ast.AST) -> str | None:
        """``X`` for a call ``sf.X(...)`` of today's surface, else None."""

        name = self._sf_name(node)
        return name if name in _OLD else None

    def _sf_name(self, node: ast.AST) -> str | None:
        if not isinstance(node, ast.Call):
            return None
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            return func.attr if func.value.id == self.alias else None
        return None

    def _report_values(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and node.attr == "synthesizer":
                self.report.append((node.lineno, "attr: .synthesizer reads an old Fusion field"))
            if self._read_as_value(node):
                assert isinstance(node, ast.Attribute)
                self.report.append(
                    (
                        node.lineno,
                        f"value: {self.alias}.{node.attr} is read as a value (isinstance, "
                        "attribute)",
                    )
                )

    def _read_as_value(self, node: ast.AST) -> bool:
        if not (isinstance(node, ast.Attribute) and node.attr in _VALUES):
            return False
        parent = self.parents.get(node)
        called = isinstance(parent, ast.Call) and parent.func is node
        return isinstance(node.value, ast.Name) and node.value.id == self.alias and not called

    # -------------------------------------------------------------------------- dispatch

    def _rewrite(self, call: ast.Call) -> str:
        name = self._old(call)
        if name is None:
            return self._then(call)
        handler = {
            "Fusion": self._fusion,
            "Pipeline": self._pipeline,
            "Gate": _no_gate,
        }.get(name, self._standalone)
        return handler(call)

    def _then(self, call: ast.Call) -> str:  # R12
        assert isinstance(call.func, ast.Attribute)
        right = self.text(call.args[0])
        if isinstance(call.args[0], ast.BoolOp | ast.IfExp | ast.Lambda | ast.Compare):
            right = f"({right})"
        return f"{self.text(call.func.value)} >> {right}"

    def _standalone(self, call: ast.Call) -> str:
        """A value outside a synthesizer slot: one part, or a hand case (a judge to hoist).

        A judge alone is its step: ``sx.Judge`` (scores) or ``sx.JudgePick`` (label). A reader
        that names it hoists the name (R7h); a synthesizer name reads its order here (R7)."""

        if self._sf_name(call) == "Judge":
            options = self._options(call)
            label = _constant(options.get("returns")) == "label"
            return self._judge_text("JudgePick" if label else "Judge", options)
        conv = self._convert(call)
        if len(conv.parts) != 1:
            raise Hand("R7h", "a judge reader outside a Fusion: hoist its sx.Judge by hand")
        return conv.parts[0]

    def _options(self, call: ast.Call) -> dict[str, ast.expr]:
        name = self._sf_name(call) or ""
        if any(isinstance(arg, ast.Starred) for arg in call.args) or any(
            keyword.arg is None for keyword in call.keywords
        ):
            raise Hand("args", f"a *args or **kwargs call of {name}")
        options = dict(zip(_POSITIONAL.get(name, ()), call.args, strict=False))
        options.update({str(keyword.arg): keyword.value for keyword in call.keywords})
        return options

    def _convert(self, call: ast.Call) -> _Conv:
        name = self._sf_name(call) or ""
        options = self._options(call)
        if name == "Reduce":
            return self._reduce(options)
        if name == "Judge":
            return self._judge_terminal(options)
        form = _REDUCER_FORMS.get(name)
        if form is None:
            raise Hand("R1", f"cannot resolve the reducer {name or 'call'}")
        return form(self, name, options)

    # ------------------------------------------------------------------ the reducers

    def _keywords(self, options: dict[str, ast.expr], rename: dict[str, str]) -> list[str]:
        return [
            f"{rename.get(key, key)}={self._over(key, value)}" for key, value in options.items()
        ]

    def _over(self, key: str, value: ast.expr) -> str:
        """``extract=sf.Extract("field", path=p)`` is ``over="field:p"``; else the value text."""

        path = self._field_extract(value) if key == "extract" else None
        return self.text(value) if path is None else _quote(f"field:{path}")

    def _field_extract(self, node: ast.expr) -> str | None:
        if not (isinstance(node, ast.Call) and self._sf_name(node) == "Extract"):
            return None
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        path = _constant(keywords.get("path"))
        only_path = len(node.args) == 1 and list(keywords) == ["path"]
        if only_path and _constant(node.args[0]) == "field" and isinstance(path, str):
            return path
        return None

    def _reader(self, name: str, options: dict[str, ast.expr]) -> _Conv:  # R3, R7h, R9
        judge = self._hoisted(options.pop("judge", None))
        gate = options.pop("gate", None)
        main = _call(name, keywords=self._keywords(options, {"extract": "over"}))
        if gate is not None:
            main = self._gate(gate, main)
        return _Conv((*judge, main))

    def _filter(self, name: str, options: dict[str, ast.expr]) -> _Conv:  # R3, R7h
        judge = self._hoisted(options.pop("judge", None))
        main = _call(name, keywords=self._keywords(options, {"extract": "over"}))
        return _Conv((*judge, main), narrow=True)

    def _prefix(self, name: str, options: dict[str, ast.expr]) -> _Conv:
        positional = [self.text(options.pop(key)) for key in _POSITIONAL[name] if key in options]
        main = _call(name, positional, self._keywords(options, {}))
        return _Conv((main,), narrow=name == "Concat")

    def _rank(self, name: str, options: dict[str, ast.expr]) -> _Conv:  # R8, R7h
        judge = self._hoisted(options.pop("by", None))
        by = self._by(options) if not judge else _quote("score:judge")
        k = self.text(options.pop("k"))
        main = _call("Rank", [k], [f"by={by}", *self._keywords(options, {})])
        return _Conv((*judge, main), narrow=True)

    def _by(self, options: dict[str, ast.expr]) -> str:
        if "by_field" in options:
            path = _constant(options.pop("by_field"))
            if not isinstance(path, str):
                raise Hand("R8", "a by_field that is not a literal")
            return _quote(f"field:{path}")
        if "by_signal" in options:
            return self._signal_key(options.pop("by_signal"))
        raise Hand("R8", "a Rank with no source")

    def _signal_key(self, node: ast.expr) -> str:
        """``"key"`` for ``sf.signal("key")``, else the value text (a Signal works for by=)."""

        if self._sf_name(node) == "signal" and isinstance(node, ast.Call) and node.args:
            key = _constant(node.args[0])
            if isinstance(key, str):
                return _quote(key)
        return self.text(node)

    def _pick(self, name: str, options: dict[str, ast.expr]) -> _Conv:  # R4, R5, R6
        output = [f"output={self.text(options.pop('output'))}"] if "output" in options else []
        if "equals" in options:
            return _Conv((self._first(options, output),))
        order = _constant(options.pop("order", None))
        if order not in (None, "max", "min"):
            raise Hand("R4", f"an order that is not 'max' or 'min': {order!r}")
        best = "ArgMin" if order == "min" else "ArgMax"
        if "by_signal" in options:
            return _Conv((_call(best, [self._signal_key(options.pop("by_signal"))], output),))
        path = _constant(options.pop("field", None))
        if not isinstance(path, str) or options:
            raise Hand("R5", "a field pick needs a literal field and no other option")
        return _Conv((_call(best, [_quote(f"field:{path}")], output),))

    def _first(self, options: dict[str, ast.expr], output: list[str]) -> str:  # R6
        equals = self.text(options.pop("equals"))
        normalize = options.pop("normalize", None)
        target = [self.text(options.pop("field"))]
        if normalize is not None:
            target.append(f"normalize={self.text(normalize)}")
        if options:
            raise Hand("R6", f"an option First does not take: {sorted(options)}")
        return _call("First", (), [f"where={_call('field', target)} == {equals}", *output])

    def _reduce(self, options: dict[str, ast.expr]) -> _Conv:  # R10
        op = _constant(options.pop("op", None))
        if op == "judge" and "mode" not in options:
            return self._reduce_judge(options)
        if "mode" in options or op not in _REDUCE_FORMS:
            raise Hand("R10", f"a Reduce op or mode with no new form: {op!r}")
        name, form = _REDUCE_FORMS[str(op)]
        return form(self, name, options)

    def _reduce_judge(self, options: dict[str, ast.expr]) -> _Conv:
        if "rubric" in options:
            raise Hand("R10", "a Reduce('judge') rubric override")
        judge = self._judge_call(options.pop("judge"))
        order = options.pop("order", None)
        return self._judge_terminal({**self._options(judge), **({"order": order} if order else {})})

    # ------------------------------------------------------------------------ the judge

    def _judge_terminal(self, options: dict[str, ast.expr]) -> _Conv:  # R7, R7l
        returns = _constant(options.get("returns"))
        if returns == "label":
            return _Conv((self._judge_text("JudgePick", options),))
        order = _constant(options.get("order"))
        best = "ArgMin" if order == "min" else "ArgMax"
        return _Conv((self._judge_text("Judge", options), _call(best, [_quote("score:judge")])))

    def _judge_text(self, name: str, options: dict[str, ast.expr]) -> str:
        if _constant(options.get("returns")) not in ("label", "scores"):
            raise Hand("R7", "a judge whose returns= is not a literal")
        if _constant(options.get("order")) not in (None, "max", "min"):
            raise Hand("R7", "a judge whose order= is not a literal")
        kept = {key: value for key, value in options.items() if key not in ("returns", "order")}
        model = self.text(kept.pop("model"))
        return _call(name, [model], self._keywords(kept, {}))

    def _resolve(self, node: ast.expr) -> ast.expr | None:
        """The value of a name with one assignment, or of a call of a one-return function."""

        if isinstance(node, ast.Name):
            return self.values.get(node.id)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return self.returns.get(node.func.id)
        return node

    def _judge_call(self, node: ast.expr) -> ast.Call:
        resolved = self._resolve(node) if isinstance(node, ast.Name) else node
        if not (isinstance(resolved, ast.Call) and self._sf_name(resolved) == "Judge"):
            raise Hand("R7h", "a judge that is not a sf.Judge(...) call or a name for one")
        return resolved

    def _hoisted(self, node: ast.expr | None) -> tuple[str, ...]:
        """The ``sx.Judge`` step that a judge reader needs before it (R7h): the judge's name, or
        the literal judge in its new form."""

        if node is None:
            return ()
        judge = self._judge_call(node)
        if _constant(self._options(judge).get("returns")) != "scores":
            raise Hand("R7h", "a reader's judge must return scores")
        if isinstance(node, ast.Name):
            return (node.id,)
        return (self._judge_text("Judge", self._options(judge)),)

    # -------------------------------------------------------------------------- the gate

    def _gate(self, node: ast.expr, then: str) -> str:  # R9
        if not (isinstance(node, ast.Call) and self._sf_name(node) == "Gate"):
            raise Hand("R9", "a gate that is not a sf.Gate(...) call")
        options = self._options(node)
        ref = _gate_ref(_constant(options.get("observe")))
        cmp = _constant(options.get("cmp"))
        if cmp not in _GATE_CMPS:
            raise Hand("R9", f"a gate cmp that is not a literal comparison: {cmp!r}")
        keywords = [f"when={ref} {cmp} {self.text(options['threshold'])}", f"then={then}"]
        keywords += self._otherwise(options.get("otherwise"))
        keywords += self._band(ref, options.get("abstain_band"))
        return _call("Gate", (), keywords)

    def _otherwise(self, node: ast.expr | None) -> list[str]:
        if node is None or _constant(node) == "abstain":
            return []
        kind = self._kind(node)
        if kind == "judge":
            if _constant(self._options(self._judge_call(node)).get("returns")) != "label":
                raise Hand("R9", "a gate otherwise= judge must return a label")
            return [f"otherwise={self.text(node)}"]  # R7l: a label judge is sx.JudgePick
        if kind in ("route", "writer"):
            return [f"otherwise={_call('Synthesize', [self.text(node)])}"]
        raise Hand("R9", "a gate otherwise= that is not a label judge, a Model or a route")

    def _band(self, ref: str, node: ast.expr | None) -> list[str]:
        if node is None or _constant(node) is None:
            return []
        if not (isinstance(node, ast.Tuple) and len(node.elts) == 2):
            raise Hand("R9", "an abstain_band that is not a literal pair")
        low, high = (self.text(item) for item in node.elts)
        return [f"abstain_if={ref}.between({low}, {high})"]

    # ------------------------------------------------------------- Fusion and Pipeline

    def _kind(self, node: ast.expr, depth: int = 0) -> str | None:
        """route | writer | reducer | judge | context, or None when it cannot be resolved."""

        resolved = self._resolve(node)
        if resolved is not node:  # a name or a function call: its one value, if any
            return None if resolved is None or depth >= 8 else self._kind(resolved, depth + 1)
        return (
            "route" if isinstance(_constant(node), str) else _call_kind(self._sf_name(node), node)
        )

    def _fanout(self, options: dict[str, ast.expr]) -> str:
        members = self.text(options.pop("members"))
        kept = [key for key in ("signals", "quorum", "name") if key in options]
        return _call("Fanout", [members], [f"{key}={self.text(options.pop(key))}" for key in kept])

    def _fusion(self, call: ast.Call) -> str:  # R1, R1o, R1w, R7, R7l, R7h
        options = self._options(call)
        optional = _constant(options.pop("optional", None))
        parts = self._terminal(options.pop("synthesizer"))
        fanout = self._fanout(options)
        if options or optional not in (None, True, False):
            raise Hand("R1", f"a Fusion option with no new form: {sorted(options) or 'optional'}")
        if optional is True:
            return _call("Pipeline", [f"[{', '.join([fanout, *parts])}]"], ["optional=True"])
        return " >> ".join([fanout, *parts])

    def _terminal(self, node: ast.expr) -> tuple[str, ...]:
        kind = self._kind(node)
        if kind in ("route", "writer"):
            return (_call("Synthesize", [self.text(node)]),)  # R1w
        if kind is None or kind == "context":
            raise Hand("R1", "cannot resolve the kind of the synthesizer")
        if not isinstance(node, ast.Call):
            return self._named_terminal(node, kind)
        conv = self._convert(node)
        if conv.narrow:
            raise Hand(
                "R2",
                f"a selection needs its writer stage: {self.alias}.Pipeline([{self.alias}.Fusion"
                "(...), writer])",
            )
        return conv.parts

    def _named_terminal(self, node: ast.expr, kind: str) -> tuple[str, ...]:
        """A reducer or a judge held in a name: the name, after its definition's rewrite."""

        resolved = self._resolve(node)
        if kind == "judge" and isinstance(node, ast.Name):
            parts = self._judge_terminal(self._options(self._judge_call(node))).parts
            return (node.id, *parts[1:])
        conv = self._convert(resolved) if isinstance(resolved, ast.Call) else None
        if conv is None or conv.narrow or len(conv.parts) != 1:
            raise Hand("R1", "a selection or a judge reader held in a name or a function")
        return (self.text(node),)

    def _pipeline(self, call: ast.Call) -> str:  # R2, R11
        options = self._options(call)
        stages = options.get("stages")
        items = stages.elts if isinstance(stages, ast.List) else []
        plain = len(items) < 2 or any(isinstance(item, ast.Starred) for item in items)
        head = None if plain else self._selection_head(items[0])
        if head is None:
            return self._inner(call)
        _, writer, *rest = items
        parts = [*head, _call("Synthesize", [self.text(writer)]), *map(self.text, rest)]
        kept = [key for key in ("name", "optional") if key in options]
        keywords = [f"{key}={self.text(options[key])}" for key in kept]
        if keywords:
            return _call("Pipeline", [f"[{', '.join(parts)}]"], keywords)
        return " >> ".join(parts)

    def _selection_head(self, node: ast.expr) -> tuple[str, ...] | None:
        """``Fanout >> [judge] >> selection`` for ``sf.Fusion(M, synthesizer=<selection>)``, or
        the bare ``Fanout`` for ``synthesizer=sf.Reduce("context")`` (R11); else None."""

        if not (isinstance(node, ast.Call) and self._sf_name(node) == "Fusion"):
            return None
        options = self._options(node)
        synthesizer = options.pop("synthesizer", None)
        if not isinstance(synthesizer, ast.Call) or set(options) - set(_FANOUT_OPTIONS):
            return None
        return self._head_parts(options, synthesizer)

    def _head_parts(
        self, options: dict[str, ast.expr], synthesizer: ast.Call
    ) -> tuple[str, ...] | None:
        if self._is_context(synthesizer):
            return (self._fanout(options),)
        conv = self._convert(synthesizer) if self._kind(synthesizer) == "reducer" else None
        return None if conv is None or not conv.narrow else (self._fanout(options), *conv.parts)

    def _is_context(self, node: ast.Call) -> bool:
        if self._sf_name(node) != "Reduce":
            return False
        return [_constant(arg) for arg in node.args] == ["context"] and not node.keywords


def _is_then(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "then"
        and len(node.args) == 1
        and not node.keywords
    )


def _no_gate(call: ast.Call) -> str:
    raise Hand("R9", "a sf.Gate outside sf.Vote(gate=...)")


def _gate_ref(observe: object) -> str:
    if observe == "agreement":
        return "sx.agreement()"
    method, _, name = str(observe).partition(":")
    if method not in ("chosen", "mean") or not name:
        raise Hand("R9", f"a gate observe that is not a literal reference: {observe!r}")
    return f"sx.signal({_quote(name)}).{method}()"


_KINDS = {
    **dict.fromkeys(_WRITERS, "writer"),
    **dict.fromkeys(_REDUCERS, "reducer"),
    "Judge": "judge",
}


def _call_kind(name: str | None, node: ast.expr) -> str | None:
    if name != "Reduce" or not isinstance(node, ast.Call):
        return _KINDS.get(name or "")
    op = [_constant(arg) for arg in node.args[:1]]
    return {"context": "context", "judge": "judge"}.get(str(op[0]) if op else "", "reducer")


_Form = Callable[[_Rewriter, str, dict[str, ast.expr]], _Conv]
_REDUCER_FORMS: dict[str, _Form] = {
    "Vote": _Rewriter._reader,
    "Median": _Rewriter._reader,
    "Mean": _Rewriter._reader,
    "Pick": _Rewriter._pick,
    "Rank": _Rewriter._rank,
    "Filter": _Rewriter._filter,
    "Concat": _Rewriter._prefix,
    "Merge": _Rewriter._prefix,
}
_REDUCE_FORMS: dict[str, tuple[str, _Form]] = {
    "plurality": ("Vote", _Rewriter._reader),
    "weighted": ("Vote", _Rewriter._reader),
    "median": ("Median", _Rewriter._reader),
    "mean": ("Mean", _Rewriter._reader),
    "argmax": ("Pick", _Rewriter._pick),
    "pick_field": ("Pick", _Rewriter._pick),
    "top_k": ("Rank", _Rewriter._rank),
    "filter": ("Filter", _Rewriter._filter),
    "concat": ("Concat", _Rewriter._prefix),
    "merge": ("Merge", _Rewriter._prefix),
}


# ------------------------------------------------------------------------------ the imports


def _with_sx_import(text: str) -> str:
    tree = ast.parse(text)
    if any(_is_sx_import(node) for node in tree.body):
        return text
    lines = text.splitlines(keepends=True)
    imports = [node for node in tree.body if isinstance(node, ast.Import | ast.ImportFrom)]
    sf_import = [node for node in imports if ast.unparse(node) == _SF_IMPORT]
    anchor = (sf_import or imports or [None])[-1]
    at = 0 if anchor is None else anchor.end_lineno or 0
    return "".join([*lines[:at], SX_IMPORT + "\n", *lines[at:]])


def _is_sx_import(node: ast.stmt) -> bool:
    return isinstance(node, ast.ImportFrom) and ast.unparse(node) == SX_IMPORT


def _to_sf(text: str, path: str) -> Migration:  # R13
    tree = ast.parse(text)
    source = _Source(text)
    edits = [
        (*source.span(node.value), "sf")
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "sx"
    ]
    moved = source.splice(0, len(source.data), edits)
    lines = moved.splitlines(keepends=True)
    has_sf = any(ast.unparse(node) == _SF_IMPORT for node in tree.body)
    report = []
    for node in tree.body:
        if _is_sx_import(node):
            lines[node.lineno - 1] = "" if has_sf else _SF_IMPORT + "\n"
        elif "as sx" in ast.unparse(node):
            report.append(f"{path}:{node.lineno}: R13: an sx import with other names")
    return Migration("".join(lines), report)


def migrate_source(text: str, *, to: str = "sx", path: str = "<source>") -> Migration:
    """The new text of one module and its hand-case report (``file:line: rule: reason``)."""

    if to == "sf":
        return _to_sf(text, path)
    rewriter = _Rewriter(text, path)
    new = rewriter.run()
    if new != text and "sx." in new:
        new = _with_sx_import(new)
    report = [f"{path}:{line}: {message}" for line, message in sorted(rewriter.report)]
    return Migration(new, report)


# -------------------------------------------------------------------------------- the audit

_COUNTS = ("assert", "raises", "helper")


def _assertion_kind(node: ast.AST) -> str | None:
    if isinstance(node, ast.Assert):
        return "assert"
    func = node.func if isinstance(node, ast.Call) else None
    name = str(getattr(func, "attr", None) or getattr(func, "id", ""))
    on_pytest = isinstance(func, ast.Attribute) and getattr(func.value, "id", "") == "pytest"
    if on_pytest and name in ("raises", "warns"):
        return "raises"
    return "helper" if name.startswith(("assert", "_assert", "expect")) else None


def _test_functions(tree: ast.Module) -> Iterator[tuple[str, ast.AST]]:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            "test"
        ):
            yield node.name, node
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    yield f"{node.name}::{item.name}", item


def assertion_counts(text: str) -> dict[str, dict[str, int]]:
    """Per test function (a parametrized one counts once): its assert, raises, helper counts."""

    counts: dict[str, dict[str, int]] = {}
    for name, function in _test_functions(ast.parse(text)):
        found = Counter(_assertion_kind(node) for node in ast.walk(function))
        counts[name] = {kind: found[kind] for kind in _COUNTS}
    return counts


def audit_source(path: str, old: str, new: str, allowed: frozenset[str]) -> list[str]:
    """The test functions of ``old`` that ``new`` lost or that lost an assertion, unless the
    allow list (``path::function``) names them."""

    before, after = assertion_counts(old), assertion_counts(new)
    problems = []
    for name, counts in before.items():
        if f"{path}::{name}" in allowed:
            continue
        if name not in after:
            problems.append(f"{path}::{name}: missing")
            continue
        problems += [
            f"{path}::{name}: {kind} {counts[kind]} -> {after[name][kind]}"
            for kind in _COUNTS
            if after[name][kind] < counts[kind]
        ]
    return problems


def _git_base(base: str, path: Path) -> str | None:
    shown = subprocess.run(
        ["git", "show", f"{base}:./{path.as_posix()}"], capture_output=True, text=True, check=False
    )
    return shown.stdout if shown.returncode == 0 else None


def _audit(base: str, paths: Sequence[Path], allow: Path | None) -> int:
    allowed = frozenset(allow.read_text().split()) if allow else frozenset()
    problems: list[str] = []
    for path in paths:
        old = _git_base(base, path)
        if old is not None:
            new = path.read_text() if path.exists() else ""
            problems += audit_source(path.as_posix(), old, new, allowed)
    sys.stdout.write("".join(f"{line}\n" for line in problems) or "audit: no lost assertion\n")
    return 1 if problems else 0


def _migrate(to: str, paths: Sequence[Path]) -> int:
    changed, report = [], []
    for path in paths:
        text = path.read_text()
        result = migrate_source(text, to=to, path=path.as_posix())
        report += result.report
        if result.text != text:
            path.write_text(result.text)
            changed.append(str(path))
    if changed:
        subprocess.run([sys.executable, "-m", "ruff", "format", "-q", *changed], check=True)
    sys.stdout.write("".join(f"{line}\n" for line in report))
    sys.stdout.write(f"migrate_surface: {len(changed)} changed, {len(report)} hand cases\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--to", choices=("sx", "sf"))
    mode.add_argument("--audit", metavar="BASE")
    parser.add_argument("--allow", type=Path, help="the allowed deletions, path::function")
    args = parser.parse_args(argv)
    if args.audit:
        return _audit(args.audit, args.paths, args.allow)
    return _migrate(args.to, args.paths)


if __name__ == "__main__":
    raise SystemExit(main())
