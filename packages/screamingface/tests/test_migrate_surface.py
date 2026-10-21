"""MG-1: the unit 7 codemod (``scripts/migrate_surface.py``) rewrites each old form (swap §4).

FEATURE: one input → output row per rewrite rule R1–R13, the hand-case report, and the audit that
proves no test lost an assertion. The codemod and this file are deleted together in step 7f.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_surface.py"
_SF = "import screamingface as sf\n"
_SX = "from screamingface import _surface as sx\n"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migrate_surface", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # WHY: dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


migrate = _load()


def _sx(body: str) -> str:
    """The rewritten body of a module that imports ``sf``; the ``sx`` import comes with a ``sx.``
    name (R12 alone needs none)."""

    result = migrate.migrate_source(_SF + body, to="sx")
    assert result.report == []
    assert result.text.startswith(_SF + _SX if "sx." in result.text else _SF)
    return result.text.removeprefix(_SF).removeprefix(_SX)


_J = 'sf.Judge("j", returns="scores", rubric=R)'
_ROWS = [
    # R1: a reducer synthesizer becomes Fanout >> reducer; signals, quorum and name go to Fanout
    (
        "R1",
        'x = sf.Fusion(M, synthesizer=sf.Vote(), signals=G, name="n", quorum=2)\n',
        'x = sx.Fanout(M, signals=G, quorum=2, name="n") >> sx.Vote()\n',
    ),
    (
        "R1o",
        "x = sf.Fusion(M, synthesizer=sf.Median(), optional=True)\n",
        "x = sx.Pipeline([sx.Fanout(M), sx.Median()], optional=True)\n",
    ),
    (
        "R1w",
        'x = sf.Fusion(M, synthesizer=sf.Model("prov/w", prompt=P))\n',
        'x = sx.Fanout(M) >> sx.Synthesize(sf.Model("prov/w", prompt=P))\n',
    ),
    (
        "R1w-name",
        'w = "prov/w"\nx = sf.Fusion(M, synthesizer=w)\n',
        'w = "prov/w"\nx = sx.Fanout(M) >> sx.Synthesize(w)\n',
    ),
    (
        "R2",
        f'x = sf.Pipeline([sf.Fusion(M, synthesizer=sf.Rank(2, by={_J})), "prov/w", "prov/x"])\n',
        'x = sx.Fanout(M) >> sx.Judge("j", rubric=R) >> sx.Rank(2, by="score:judge") >> '
        'sx.Synthesize("prov/w") >> "prov/x"\n',
    ),
    (
        "R2-name",
        'x = sf.Pipeline([sf.Fusion(M, synthesizer=sf.Concat()), "prov/w"], name="p")\n',
        'x = sx.Pipeline([sx.Fanout(M), sx.Concat(), sx.Synthesize("prov/w")], name="p")\n',
    ),
    (
        "R3",
        'v = sf.Vote(extract="last_number", normalize="numeric")\n'
        'f = sf.Filter(where=sf.matches("x"), extract=E)\n',
        'v = sx.Vote(over="last_number", normalize="numeric")\n'
        'f = sx.Filter(where=sf.matches("x"), over=E)\n',
    ),
    (
        "R4",
        'p = sf.Pick(by_signal=sf.signal("cost_usd"), order="min", output="answer")\n',
        'p = sx.ArgMin("cost_usd", output="answer")\n',
    ),
    (
        "R5",
        'p = sf.Pick("confidence", order="max", output="answer")\n',
        'p = sx.ArgMax("field:confidence", output="answer")\n',
    ),
    (
        "R6",
        'p = sf.Pick("answer", equals="yes", normalize="text", output="x")\n',
        'p = sx.First(where=sx.field("answer", normalize="text") == "yes", output="x")\n',
    ),
    (
        "R7",
        'x = sf.Fusion(M, synthesizer=sf.Judge("j", returns="scores", rubric=R, params=P, '
        'order="min"))\n',
        'x = sx.Fanout(M) >> sx.Judge("j", rubric=R, params=P) >> sx.ArgMin("score:judge")\n',
    ),
    (
        "R7l",
        'x = sf.Fusion(M, synthesizer=sf.Judge("j", returns="label", rubric=R))\n',
        'x = sx.Fanout(M) >> sx.JudgePick("j", rubric=R)\n',
    ),
    (
        "R7h",
        f'x = sf.Fusion(M, synthesizer=sf.Vote(weights=sf.signal("score:judge"), judge={_J}))\n',
        'x = sx.Fanout(M) >> sx.Judge("j", rubric=R) >> '
        'sx.Vote(weights=sf.signal("score:judge"))\n',
    ),
    (
        "R7h-name",
        f"j = {_J}\n"
        'x = sf.Pipeline([sf.Fusion(M, synthesizer=sf.Filter(where=W, judge=j)), "w"])\n',
        'j = sx.Judge("j", rubric=R)\nx = sx.Fanout(M) >> j >> sx.Filter(where=W) >> '
        'sx.Synthesize("w")\n',
    ),
    (
        "R8",
        'r = sf.Rank(2, by_field="confidence")\n'
        's = sf.Rank(3, by_signal=sf.signal("cost_usd"), order="min")\n',
        'r = sx.Rank(2, by="field:confidence")\ns = sx.Rank(3, by="cost_usd", order="min")\n',
    ),
    (
        "R9",
        'v = sf.Vote(gate=sf.Gate("mean:risk", "<=", 3.0, otherwise=sf.Model("prov/big"), '
        "abstain_band=(2.5, 3.5)))\n",
        'v = sx.Gate(when=sx.signal("risk").mean() <= 3.0, then=sx.Vote(), '
        'otherwise=sx.Synthesize(sf.Model("prov/big")), '
        'abstain_if=sx.signal("risk").mean().between(2.5, 3.5))\n',
    ),
    (
        "R9-label",
        'v = sf.Vote(extract=E, gate=sf.Gate("agreement", ">=", 0.5, '
        'otherwise=sf.Judge("j", returns="label", rubric=R)))\n',
        "v = sx.Gate(when=sx.agreement() >= 0.5, then=sx.Vote(over=E), "
        'otherwise=sx.JudgePick("j", rubric=R))\n',
    ),
    (
        "R10",
        'v = sf.Reduce("weighted", extract=sf.Extract("field", path="answer"), '
        'weights=sf.signal("p"))\n'
        'r = sf.Reduce("top_k", k=2, by_field="c")\n'
        'p = sf.Reduce("pick_field", field="a", equals=1)\n',
        'v = sx.Vote(over="field:answer", normalize=None, weights=sf.signal("p"))\n'
        'r = sx.Rank(2, by="field:c")\n'
        'p = sx.First(where=sx.field("a") == 1)\n',
    ),
    (
        "R11",
        'x = sf.Pipeline([sf.Fusion(M, synthesizer=sf.Reduce("context")), "prov/w", W])\n',
        'x = sx.Fanout(M) >> sx.Synthesize("prov/w") >> W\n',
    ),
    ("R12", "x = a.then(b)\n", "x = a >> b\n"),
    # R12 keeps the precedence of the receiver and the argument
    ("R12-parens", "x = (a or b).then(c | d)\n", "x = (a or b) >> (c | d)\n"),
    # R10 with a mode: the Median/Mean select= of that mode; a mode that is the op's only one goes
    (
        "R10-mode",
        'm = sf.Reduce("median", "compute", extract=sf.Extract("field", path="a"))\n'
        'n = sf.Reduce("mean", "select", extract=sf.Extract("last_number"))\n'
        'v = sf.Reduce("plurality", "select", extract=E)\n',
        'm = sx.Median(over="field:a", select="value")\n'
        'n = sx.Mean(over=sf.Extract("last_number"), select="nearest")\n'
        "v = sx.Vote(over=E)\n",
    ),
    # R10 judge: a judge held in a name keeps the name
    (
        "R10-judge-name",
        f'j = {_J}\nx = sf.Fusion(M, synthesizer=sf.Reduce("judge", judge=j, order="min"))\n',
        'j = sx.Judge("j", rubric=R)\nx = sx.Fanout(M) >> j >> sx.ArgMin("score:judge")\n',
    ),
    # a name resolves in its own scope: a local with one assignment
    (
        "scope-local",
        "def f():\n    s = sf.Vote()\n    return sf.Fusion(M, synthesizer=s)\n",
        "def f():\n    s = sx.Vote()\n    return sx.Fanout(M) >> s\n",
    ),
    # an annotation that names an old class is no hand case
    (
        "annotation",
        "def g(x: sf.Fusion) -> sf.Fusion:\n    return x\n",
        "def g(x: sf.Fusion) -> sf.Fusion:\n    return x\n",
    ),
    (
        "prefix",
        "c = sf.Concat(label=False)\nm = sf.Merge({'a': rule})\n",
        "c = sx.Concat(label=False)\nm = sx.Merge({'a': rule})\n",
    ),
    (
        "nested",
        "x = sf.Fusion([sf.Fusion(M, synthesizer=sf.Mean()), 'p/b'], synthesizer=sf.Vote())\n",
        "x = sx.Fanout([sx.Fanout(M) >> sx.Mean(), 'p/b']) >> sx.Vote()\n",
    ),
    (
        "parens",
        'n = sf.Fusion(M, synthesizer=sf.Vote()).then("p/w")\n',
        'n = (sx.Fanout(M) >> sx.Vote()) >> "p/w"\n',
    ),
]


@pytest.mark.parametrize(("old", "new"), [row[1:] for row in _ROWS], ids=[row[0] for row in _ROWS])
def test_mg1_each_rule_rewrites_its_old_form(old: str, new: str) -> None:
    assert _sx(old) == new


def test_mg1_r13_moves_sx_to_sf_and_drops_the_sx_import() -> None:
    source = _SF + _SX + "x = sx.Fanout(M) >> sx.Vote()\n"

    result = migrate.migrate_source(source, to="sf")

    assert result.text == _SF + "x = sf.Fanout(M) >> sf.Vote()\n"
    assert result.report == []


def test_mg1_the_sx_import_is_added_once() -> None:
    source = _SF + _SX + "v = sf.Vote()\nm = sf.Median()\n"

    assert (
        migrate.migrate_source(source, to="sx").text
        == _SF + _SX + "v = sx.Vote()\nm = sx.Median()\n"
    )
    unchanged = _SF + "m = sf.Model('p/a')\n"
    assert migrate.migrate_source(unchanged, to="sx").text == unchanged


def test_mg1_a_site_it_cannot_rewrite_is_left_and_reported() -> None:
    source = (
        _SF
        + "def f(s):\n    return sf.Fusion(M, synthesizer=s)\n"
        + "ok = isinstance(x, sf.Fusion)\n"
        + "r = sf.Fusion(M, synthesizer=sf.Rank(2, by_field='c'))\n"
    )

    result = migrate.migrate_source(source, to="sx", path="t.py")

    assert result.text == source
    assert result.report == [
        "t.py:3: R1: cannot resolve the kind of the synthesizer",
        "t.py:4: value: sf.Fusion is read as a value (isinstance, attribute)",
        "t.py:5: R2: a selection needs its writer stage: sf.Pipeline([sf.Fusion(...), writer])",
    ]


_HAND = [
    # a parameter that shares its name with an unrelated module value is not that value
    (
        "scope-parameter",
        "def _fusion(synthesizer):\n    return sf.Fusion(M, synthesizer=synthesizer)\n"
        "synthesizer = sf.Vote()\n",
        ["2: R1: cannot resolve the kind of the synthesizer"],
        "def _fusion(synthesizer):\n    return sf.Fusion(M, synthesizer=synthesizer)\n"
        "synthesizer = sx.Vote()\n",
    ),
    # a min-order scores judge alone would lose its order
    (
        "judge-min",
        'j = sf.Judge("j", returns="scores", rubric=R, order="min")\n',
        ["1: R7: a scores judge with order='min' is only a synthesizer: write sx.ArgMin by hand"],
        None,
    ),
    (
        "reduce-judge-option",
        f'x = sf.Fusion(M, synthesizer=sf.Reduce("judge", judge={_J}, rubric=R2))\n',
        ["1: R10: a Reduce('judge') option with no new form: ['rubric']"],
        None,
    ),
    (
        "pick-option",
        'p = sf.Pick(by_signal=sf.signal("c"), normalize="text")\n',
        ["1: R4: a signal pick takes no other option: ['normalize']"],
        None,
    ),
    # a comment between the arguments would be lost
    (
        "comment",
        "v = sf.Vote(\n    extract=E,  # why\n    normalize=N,\n)\n",
        ["1: comment: a comment inside the call would be lost: rewrite it by hand"],
        None,
    ),
    # a field of a rewritten value is read
    (
        "attribute",
        "f = sf.Fusion(M, synthesizer=sf.Vote())\nm = f.members\n",
        ["2: attr: f.members reads a field of a rewritten value"],
        "f = sx.Fanout(M) >> sx.Vote()\nm = f.members\n",
    ),
    (
        "attribute-call",
        "n = sf.Fusion(M, synthesizer=sf.Vote()).synthesizer\n",
        ["1: attr: .synthesizer reads a field of a rewritten value"],
        "n = (sx.Fanout(M) >> sx.Vote()).synthesizer\n",
    ),
    # a file that builds internal nodes (tests/_nodes.py) keeps its reducer values as nodes
    (
        "nodes",
        "from _nodes import fusion_node\nr = sf.Vote()\nx = sf.Fusion(M, synthesizer=sf.Vote())\n",
        ["2: nodes: a reducer value in a file that builds internal nodes: keep it a node"],
        "from _nodes import fusion_node\nr = sf.Vote()\nx = sx.Fanout(M) >> sx.Vote()\n",
    ),
]


@pytest.mark.parametrize(
    ("body", "lines", "new"), [row[1:] for row in _HAND], ids=[row[0] for row in _HAND]
)
def test_mg1_a_hand_case_is_reported(body: str, lines: list[str], new: str | None) -> None:
    result = migrate.migrate_source(_SF + body, to="sx", path="t.py")

    assert result.report == [
        f"t.py:{int(line.split(':')[0]) + 1}:{line.split(':', 1)[1]}" for line in lines
    ]
    expected = body if new is None else new
    assert result.text.removeprefix(_SF).removeprefix(_SX) == expected


# ---------------------------------------------------------------------- bytes of the rewrite


@pytest.mark.parametrize(
    "old",
    [
        'sf.Reduce("plurality", extract=sf.Extract("field", path="answer"))',
        'sf.Reduce("weighted", extract=sf.Extract("field", path="answer"), '
        'weights=sf.signal("cost_usd"))',
        'sf.Reduce("plurality", extract=sf.Extract("last_number", normalize="numeric"))',
        'sf.Reduce("median", "compute", extract=sf.Extract("field", path="answer"))',
        'sf.Vote(extract="last_number", normalize="numeric")',
    ],
    ids=["plurality", "weighted", "plurality-extract", "median-mode", "vote"],
)
def test_mg1_the_rewritten_vote_compiles_to_the_same_bytes(old: str) -> None:
    from types import SimpleNamespace

    from _combine_flow_fixtures import flow_operators
    from _nodes import FusionNode, ReduceNode, VoteNode

    import screamingface as sf
    from screamingface._evaluation.candidate import compile_candidate

    source = f"{_SF}x = sf.Fusion(['p/a', 'p/b', 'p/c'], synthesizer={old})\n"
    new = migrate.migrate_source(source, to="sx")
    assert new.report == []
    # WHY no import lines: since the swap (7e) the old names are the internal nodes, and the sx
    # names are sf.*; each text runs with the names it was written for.
    today = SimpleNamespace(
        Fusion=FusionNode, Reduce=ReduceNode, Vote=VoteNode, Extract=sf.Extract, signal=sf.signal
    )
    values = []
    for text, namespace in ((source, {"sf": today}), (new.text, {"sf": sf, "sx": sf})):
        exec(text.replace(_SF, "").replace(_SX, ""), namespace)  # noqa: S102 - the codemod's rows
        values.append(compile_candidate(namespace["x"], operators=flow_operators()).url4)  # type: ignore[arg-type]
    assert values[0] == values[1]


def test_mg1_check_prints_the_diff_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "test_x.py"
    path.write_text(_SF + "v = sf.Vote()\n")

    assert migrate.main(["--to", "sx", "--check", str(path)]) == 0

    out = capsys.readouterr().out
    assert "+v = sx.Vote()" in out
    assert "1 would change, 0 hand cases" in out
    assert path.read_text() == _SF + "v = sf.Vote()\n"


# ---------------------------------------------------------------------------------- the audit

_OLD = """
import pytest

def test_a():
    assert 1
    assert 2
    with pytest.raises(ValueError, match="x"):
        f()

@pytest.mark.parametrize("x", [1, 2])
def test_b(x):
    _assert_thing(x)

class TestC:
    def test_d(self):
        assert 3

def _check(value):
    assert value
"""


def _counts(**found: int) -> dict[str, int]:
    return {kind: found.get(kind, 0) for kind in ("assert", "raises", "match", "params", "helper")}


def test_mg1_the_audit_counts_asserts_raises_matches_params_and_helpers() -> None:
    # every function counts, so a helper (``_check``, or one in a ``tests/_*.py`` module) is
    # audited too; ``params`` is the length of each parametrize list
    assert migrate.assertion_counts(_OLD) == {
        "test_a": _counts(**{"assert": 2, "raises": 1, "match": 1}),
        "test_b": _counts(params=2, helper=1),
        "TestC::test_d": _counts(**{"assert": 1}),
        "_check": _counts(**{"assert": 1}),
    }


@pytest.mark.parametrize(
    ("edit", "problem"),
    [
        (
            (
                '    with pytest.raises(ValueError, match="x"):',
                "    with pytest.raises(ValueError):",
            ),
            "t.py::test_a: match 1 -> 0",
        ),
        (('"x", [1, 2]', '"x", [1]'), "t.py::test_b: params 2 -> 1"),
        (("    assert value\n", "    pass\n"), "t.py::_check: assert 1 -> 0"),
    ],
    ids=["match", "params", "helper"],
)
def test_mg1_the_audit_flags_a_lost_match_param_or_helper_assert(
    edit: tuple[str, str], problem: str
) -> None:
    assert migrate.audit_source("t.py", _OLD, _OLD.replace(*edit), frozenset()) == [problem]


def test_mg1_the_audit_flags_a_lost_assertion_or_test_unless_allowed() -> None:
    new = _OLD.replace("    assert 2\n", "").replace("class TestC:", "class TestE:")

    assert migrate.audit_source("t.py", _OLD, new, frozenset()) == [
        "t.py::test_a: assert 2 -> 1",
        "t.py::TestC::test_d: missing",
    ]
    allowed = frozenset({"t.py::test_a", "t.py::TestC::test_d"})
    assert migrate.audit_source("t.py", _OLD, new, allowed) == []
    assert (
        migrate.audit_source("t.py", _OLD, _OLD + "\ndef test_new():\n    pass\n", frozenset())
        == []
    )


def test_mg1_the_audit_command_reads_the_base_from_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "test_x.py").write_text(_OLD)
    git("add", "test_x.py")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    (tmp_path / "test_x.py").write_text(_OLD.replace("    assert 2\n", ""))
    monkeypatch.chdir(tmp_path)

    assert migrate.main(["--audit", "HEAD", "test_x.py"]) == 1
    assert "test_x.py::test_a: assert 2 -> 1" in capsys.readouterr().out
    (tmp_path / "allow.txt").write_text("test_x.py::test_a\n")
    assert migrate.main(["--audit", "HEAD", "--allow", "allow.txt", "test_x.py"]) == 0
