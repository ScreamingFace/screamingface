"""MSG-1: every user-facing message and public docstring names the new surface only (O13, swap §6).

FEATURE: a message that says "use sf.Pick" after ``sf.Pick`` is gone is a bug, so this test finds
the messages by a scan, not by a list. It reads, with ``ast``, every string under ``S/`` that a
``raise`` holds, that a call of an ``*Error`` / ``*Exception`` / ``*Warning`` class or of
``warnings.warn`` holds (this covers ``return ValueError(...)`` helpers such as
``_cannot_rebuild``), and every module-level text constant those name (in the module, or one
``from x import NAME`` hop away). It also reads the docstrings of every object of ``sf.__all__``
and ``sf.report.__all__``, with their public methods and properties.
INVARIANT: ``sf.Fusion`` is the public shortcut (surface §3b), so ``S/_surface/fusion.py`` (its
messages and its docstring) is exempt from the ``Fusion`` and ``synthesizer`` patterns, as a
per-module exemption (7e review). Every allow-list entry must still match a site (no stale entry),
and no entry may hide a message that a new-surface value reaches (erratum U3c).
"""

from __future__ import annotations

import ast
import inspect
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from _combine_flow_fixtures import flow_operators
from _nodes import (
    FilterNode,
    JudgeNode,
    MergeNode,
    PickNode,
    RankNode,
    ReduceNode,
    VoteNode,
    fusion_node,
)

import screamingface as sf
from screamingface import report
from screamingface._evaluation.candidate import compile_candidate
from screamingface._ui.report_view import _members_html
from screamingface.reducer import Reducer, _narrowed

_SRC = Path(sf.__file__).parent
_SHORTCUT = "_surface/fusion.py"

# pattern -> why it names an old API
_FORBIDDEN: dict[str, str] = {
    r"sf\.(Pick|Reduce)\b": "a deleted class",
    r"returns=": "sf.Judge / sf.JudgePick replace Judge(returns=)",
    r"by_field(?!@)": "by= replaces by_field= (by_field@1 is a wire op id)",
    r"by_signal(?!@)": "by= replaces by_signal= (by_signal@1 is a wire op id)",
    r"\.then\(": "Recipe.then is gone: use >>",
    r"\bPick\b": "sf.ArgMax / sf.ArgMin / sf.First replace Pick",
    r"\bReduce\b": "the steps replace sf.Reduce",
    r"abstain_band=": "abstain_if= replaces the gate's abstain_band=",
    r"extract=": "over= replaces extract=",
}
# The patterns S/_surface/fusion.py is exempt from: the sf.Fusion shortcut names itself.
_FUSION_WORDS: dict[str, str] = {
    r"\bFusion\b": "a fanout block (sf.Fanout) replaces the Fusion; sf.Fusion is the shortcut only",
    r"synthesizer": "the terminal step (sf.Synthesize) replaces the synthesizer",
}

# (module, substring) -> why it stays. Only internal-only messages: no new-surface value reaches
# them (U3c), and each entry must still match a site. Empty: 7g reworded the internal node
# messages too (they name ReduceNode or the step a block lowers from).
_ALLOWED: dict[tuple[str, str], str] = {}


@dataclass(frozen=True, slots=True)
class _Site:
    module: str  # the path under S/, e.g. "fusion.py"
    line: int
    text: str


def _strings(node: ast.AST) -> Iterator[str]:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child.value


def _names(node: ast.AST) -> Iterator[str]:
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            yield child.id


def _callee(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_message_call(call: ast.Call) -> bool:
    name = _callee(call)
    return name.endswith(("Error", "Exception", "Warning")) or name == "warn"


def _message_nodes(tree: ast.Module) -> Iterator[ast.AST]:
    """(a) the expression of every raise, (b) every error, warning or warn call."""

    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None:
            yield node.exc
        elif isinstance(node, ast.Call) and _is_message_call(node):
            yield node


def _constants(tree: ast.Module) -> dict[str, tuple[int, list[str]]]:
    """Module-level ``NAME = <text>`` constants: name -> (line, its strings)."""

    found: dict[str, tuple[int, list[str]]] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None or not isinstance(value, ast.Constant | ast.JoinedStr | ast.BinOp):
            continue
        texts = list(_strings(value))
        for target in targets:
            if isinstance(target, ast.Name) and texts:
                found[target.id] = (node.lineno, texts)
    return found


def _imports(tree: ast.Module) -> dict[str, tuple[str, str]]:
    """``from screamingface.x import NAME [as alias]``: alias -> (module path, NAME)."""

    found: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("screamingface")
        ):
            path = node.module.removeprefix("screamingface").lstrip(".").replace(".", "/")
            for alias in node.names:
                found[alias.asname or alias.name] = (path, alias.name)
    return found


def _module_path(path: str) -> Path:
    as_file = _SRC / f"{path}.py"
    return as_file if as_file.exists() else _SRC / path / "__init__.py"


def _message_sites() -> list[_Site]:
    trees = {
        path.relative_to(_SRC).as_posix(): ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(_SRC.rglob("*.py"))
    }
    sites: list[_Site] = []
    for module, tree in trees.items():
        constants, imports = _constants(tree), _imports(tree)
        for node in _message_nodes(tree):
            line = getattr(node, "lineno", 0)
            sites.extend(_Site(module, line, text) for text in _strings(node))
            for name in set(_names(node)):
                if name in constants:
                    at, texts = constants[name]
                    sites.extend(_Site(module, at, text) for text in texts)
                elif name in imports:
                    source, original = imports[name]
                    other = _module_path(source).relative_to(_SRC).as_posix()
                    hop = _constants(trees[other]) if other in trees else {}
                    if original in hop:
                        at, texts = hop[original]
                        sites.extend(_Site(other, at, text) for text in texts)
    # WHY a dict: a raise of an error call is read twice (the raise and the call)
    return list(dict.fromkeys(sites))


def _file(value: object) -> str:
    """The S/-relative file an object is defined in (the per-module exemption reads it)."""

    source = inspect.getsourcefile(value)  # type: ignore[arg-type]
    assert source is not None
    return Path(source).resolve().relative_to(_SRC.resolve()).as_posix()


def _member_doc(member: object) -> str | None:
    """The docstring of a public method or property of a class."""

    if isinstance(member, property):
        return member.__doc__
    if isinstance(member, classmethod | staticmethod):
        return member.__func__.__doc__
    return member.__doc__ if inspect.isfunction(member) else None


def _ours(value: object) -> bool:
    return (getattr(value, "__module__", "") or "").startswith("screamingface")


def _documented(value: object) -> Iterator[tuple[str, _Site]]:
    """(qualified name, site) of a public object's docstring and of its public methods and
    properties."""

    if not (inspect.isclass(value) or inspect.isfunction(value)) or not _ours(value):
        return
    if value.__doc__:
        yield f"{value.__module__}.{value.__qualname__}", _Site(_file(value), 0, value.__doc__)
    if not inspect.isclass(value):
        return
    for klass in (klass for klass in value.__mro__ if _ours(klass)):
        for attr, member in vars(klass).items():
            doc = None if attr.startswith("_") else _member_doc(member)
            if doc:
                name = f"{klass.__module__}.{klass.__qualname__}.{attr}"
                yield name, _Site(_file(klass), 0, doc)


def _docstring_sites() -> list[_Site]:
    sites: dict[str, _Site] = {}
    for namespace in (sf, report):
        for public in namespace.__all__:
            for name, site in _documented(getattr(namespace, public)):
                sites.setdefault(name, site)
    return list(sites.values())


def _patterns(module: str) -> dict[str, str]:
    return _FORBIDDEN if module == _SHORTCUT else {**_FORBIDDEN, **_FUSION_WORDS}


def _hits(sites: list[_Site]) -> list[tuple[_Site, str]]:
    return [
        (site, pattern)
        for site in sites
        for pattern in _patterns(site.module)
        if re.search(pattern, site.text)
    ]


def _allowed(site: _Site) -> bool:
    return any(module == site.module and part in site.text for module, part in _ALLOWED)


def _report(hits: list[tuple[_Site, str]]) -> str:
    return "\n".join(
        f"{site.module}:{site.line}: {pattern!r} ({_patterns(site.module)[pattern]}): "
        f"{site.text[:120]!r}"
        for site, pattern in hits
    )


def test_msg1_no_message_names_an_old_api() -> None:
    hits = [(site, pattern) for site, pattern in _hits(_message_sites()) if not _allowed(site)]

    assert not hits, "messages that name an old API:\n" + _report(hits)


def test_msg1_no_public_docstring_names_an_old_api() -> None:
    hits = [(site, pattern) for site, pattern in _hits(_docstring_sites()) if not _allowed(site)]

    assert not hits, "public docstrings that name an old API:\n" + _report(hits)


def test_msg1_the_scan_finds_the_messages_it_must_read() -> None:
    # A control: the scan reads raise texts, error calls, constants and the one import hop.
    sites = _message_sites()
    texts = {(site.module, site.text) for site in sites}

    assert any(module == "_surface/fusion.py" and "sf.Fusion" in text for module, text in texts)
    assert any("cannot rebuild" in text for module, text in texts if module == "reducer.py")
    assert _docstring_sites()


def test_msg1_every_allow_list_entry_still_matches_a_site() -> None:
    # The list is empty since 7g reworded every site; an entry added later must match a site.
    sites = _message_sites() + _docstring_sites()

    stale = [
        (module, part)
        for module, part in _ALLOWED
        if not any(site.module == module and part in site.text for site in sites)
    ]
    assert not stale, stale


# ---------------------------------------------------------------- the runtime names (swap §8)
# MSG-1 cannot see a name a message reads at run time (``type(x).__name__``, ``_step_name()``),
# so each such site has its own row: it names the public step, never an internal node class.

_MEMBERS = ["prov/a", "prov/b", "prov/c"]


def _message(build: Callable[[], object]) -> str:
    with pytest.raises((TypeError, ValueError)) as caught:
        build()
    return str(caught.value)


def test_a_step_where_a_recipe_goes_names_its_step_class() -> None:
    # S/_surface/chain.py refuse_step: type(value).__name__
    assert (
        _message(
            lambda: sf.CorrectiveLoop([sf.ArgMin("cost_usd"), "prov/b"], judge="prov/j")  # type: ignore[list-item]
        )
        == "sf.ArgMin is a step, not a recipe: put it after a sf.Fanout"
    )


def test_a_whole_context_step_after_a_narrow_step_names_its_step_class() -> None:
    # S/_surface/chain.py _check_block (NR-C1): type(terminal).__name__
    assert (
        _message(
            lambda: (
                sf.Fanout(_MEMBERS)
                >> sf.Rank(2, by="cost_usd")
                >> sf.JudgePick("prov/j", rubric="Pick one.")
            )
        )
        == "sf.JudgePick makes its own call over every member, so it cannot follow a narrow step"
    )


def test_a_step_with_no_fanout_before_it_names_its_step_class() -> None:
    # S/_surface/chain.py CH-1: type(step).__name__
    assert _message(lambda: "prov/a" >> sf.Median()) == "sf.Median needs a sf.Fanout before it"


def test_an_argmin_option_names_argmin() -> None:
    # S/_surface/steps.py _ArgBest: f"sf.{type(self).__name__}"
    assert _message(lambda: sf.ArgMin("field:c", output=7)) == "sf.ArgMin output= must be a string"  # type: ignore[arg-type]


def test_a_logprob_source_names_its_class_and_the_fanout() -> None:
    # S/fusion.py _check_logprob_sources: f"sf.{type(needs[0]).__name__}"
    nested = sf.Fanout(["openrouter/a", "openrouter/b"]) >> sf.Vote()
    assert _message(
        lambda: (
            sf.Fanout([nested, "openrouter/x"], signals={"l": sf.Logprob("prob")})
            >> sf.Vote(weights="l")
        )
    ) == (
        "sf.Logprob needs each sf.Fanout member to be one sf.Model call; member 1 ('a+b') is a "
        "nested block or Pipeline"
    )


@pytest.mark.parametrize(
    ("main", "narrow", "expected"),
    [
        (
            lambda: MergeNode({"a": sf.FieldRule.max()}),
            lambda: RankNode(2, by_signal=sf.signal("cost_usd")),
            "sf.Merge cannot follow a narrow step",
        ),
        (
            VoteNode,
            lambda: PickNode(by_signal=sf.signal("cost_usd"), order="min"),
            "sf.ArgMin is not a narrow step",
        ),
        (
            VoteNode,
            lambda: PickNode("a", equals="yes"),
            "sf.First is not a narrow step",
        ),
        (
            VoteNode,
            lambda: JudgeNode("prov/j", returns="label", rubric="Pick one."),
            "sf.JudgePick is not a narrow step",
        ),
        (
            VoteNode,
            lambda: ReduceNode("median", extract=sf.Extract("last_number")),
            "sf.Median is not a narrow step",
        ),
    ],
    ids=["merge", "argmin", "first", "judge-pick", "median-block"],
)
def test_the_narrow_carrier_names_the_step_a_node_lowers_from(
    main: Callable[[], Reducer], narrow: Callable[[], Reducer], expected: str
) -> None:
    # S/reducer.py _narrowed: _step_name(); a hand-edited url4 meets the same rules
    assert _message(lambda: _narrowed(main(), (narrow(),))) == expected


def test_a_selection_node_that_ends_a_candidate_names_its_step() -> None:
    # S/_evaluation/candidate.py: the selection label is _step_name()
    node = fusion_node(_MEMBERS, FilterNode(where=sf.matches("a")))
    assert _message(lambda: compile_candidate(node, operators=flow_operators())) == (
        "a sf.Filter must be followed by sf.Synthesize: 'a+b+c' ends the candidate with a selection"
    )


def test_a_fanout_member_of_a_report_reads_as_fanout() -> None:
    # S/_ui/report_view.py: the wire kind stays "fusion"; the label the user reads is "fanout"
    member = sf.MemberResult(
        operation_id="op_1",
        name="a+b",
        kind="fusion",
        models=("prov/a", "prov/b"),
        failures=None,
        duration_ms=None,
        usage=None,
    )
    html = _members_html(SimpleNamespace(members=[member]))  # type: ignore[arg-type]

    assert "<span class='sf-member__k'>fanout</span>" in html
    assert member.kind == "fusion"
