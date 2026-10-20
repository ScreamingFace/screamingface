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
        'v = sx.Vote(over="field:answer", weights=sf.signal("p"))\n'
        'r = sx.Rank(2, by="field:c")\n'
        'p = sx.First(where=sx.field("a") == 1)\n',
    ),
    (
        "R11",
        'x = sf.Pipeline([sf.Fusion(M, synthesizer=sf.Reduce("context")), "prov/w", W])\n',
        'x = sx.Fanout(M) >> sx.Synthesize("prov/w") >> W\n',
    ),
    ("R12", "x = a.then(b)\n", "x = a >> b\n"),
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
        "n = sf.Fusion(M, synthesizer=sf.Vote()).name\n",
        "n = (sx.Fanout(M) >> sx.Vote()).name\n",
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


# ---------------------------------------------------------------------------------- the audit

_OLD = """
import pytest

def test_a():
    assert 1
    assert 2
    with pytest.raises(ValueError):
        f()

@pytest.mark.parametrize("x", [1, 2])
def test_b(x):
    _assert_thing(x)

class TestC:
    def test_d(self):
        assert 3
"""


def test_mg1_the_audit_counts_asserts_raises_and_assert_helpers_per_test() -> None:
    assert migrate.assertion_counts(_OLD) == {
        "test_a": {"assert": 2, "raises": 1, "helper": 0},
        "test_b": {"assert": 0, "raises": 0, "helper": 1},
        "TestC::test_d": {"assert": 1, "raises": 0, "helper": 0},
    }


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
