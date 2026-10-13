# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The combine reads a numeric answer the way Inspect's own grader does (OME-1289, E4a, unit 2).

FEATURE: two members whose answers Inspect would grade equal land in one tally row.
STORY: as an author of a GSM8K or AIME Candidate, the combine and the grader agree on what counts
as the same number. GP#1 to GP#6 of the E4a gap-closure; the oracle is the real
``inspect_ai.scorer.match(numeric=True)`` (and ``aime_scorer``), run on a ``TaskState`` the way
``screamingface_engine_inspect/scorer_adapter.py`` builds one.

Runs only with the `inspect` extra installed (`uv run --extra inspect pytest ...`).
"""

from __future__ import annotations

import asyncio
import importlib
import json
import random
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.model import ChatMessageUser, ModelOutput  # noqa: E402
from inspect_ai.scorer import CORRECT, Score, Target, match  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS  # noqa: E402
from screamingface_engine.combine.ports import OpArgs, Stage, StageResult  # noqa: E402


def _stage(op_id: str, stage_name: Stage, text: str, args: OpArgs | None = None) -> StageResult:
    """Run one built-in extract or normalize operator (the Inspect lane has no shared test
    support: ``tests/unit`` is not on its import path)."""
    run = BUILTIN_OPERATORS.resolve(op_id, stage_name).run
    return run(text, {} if args is None else args)  # type: ignore[call-arg, return-value]


@pytest.fixture(scope="module")
def runner() -> Iterator[asyncio.Runner]:
    """One event loop for every row (a loop per row would dominate the corpus runs)."""
    with asyncio.Runner() as loop_runner:
        yield loop_runner


def _state(text: str) -> TaskState:
    return TaskState(
        model="m",  # type: ignore[arg-type]  # ModelName is a str alias at runtime
        sample_id=1,
        epoch=1,
        input="q",
        messages=[ChatMessageUser(content="q")],
        output=ModelOutput.from_content(model="m", content=text),
    )


def _inspect_score(
    runner: asyncio.Runner, scorer: Callable[..., Any], text: str, target: str
) -> Score:
    score = runner.run(scorer(_state(text), Target(target)))
    assert isinstance(score, Score)
    return score


# --- GP#3 to GP#6: parity corpora and generated rows ------------------------------------------

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "combine"
# GP-D3: texts a model writes for a GSM8K-style answer, with the target the board holds.
_GSM8K_CORPUS = [
    ("The answer is 42.", "42"),
    ("#### 42", "42"),
    ("$1,200.", "1200"),
    ("1200", "1200"),
    ("It costs \\$20", "20"),
    ("1,23", "123"),
    ("x=42", "42"),
    ("(42)", "42"),
    ("42%", "42"),
    ("~42", "42"),
    ("-5 degrees", "-5"),
    ("−5", "-5"),
    ("½", "0.5"),
    ("2½", "2.5"),
    ("3²", "9"),
    ("１２", "12"),
    ("十二", "12"),
    ("一点五", "1.5"),
    ("3.5e10", "35000000000"),
    ("123457", "123456"),
    ("9.0", "9"),
    ("9.", "9"),
    (".5", "0.5"),
    ("**42**", "42"),
    ("4_2", "42"),
    ("€1.000,50", "1000.5"),
    ("-0", "0"),
    ("1e999", "1"),
    ("nan", "0"),
    ("", "0"),
    ("no number here", "7"),
    ("12 apples, then 7 more", "7"),
    ("I think 18. Final answer: 26", "26"),
]
_AIME_CORPUS = [
    ("Reasoning\nANSWER: 70", "70"),
    ("$$\n\\boxed{70}\n$$", "70"),
    ("\\boxed{\\boxed{5}}", "5"),
    ("ANSWER: 70\nThis follows from 3 cases.", "70"),
    ("ANSWER: 070", "70"),
    ("", "0"),
    ("\n\n", "0"),
    ("ANSWER: \\boxed{204}", "204"),
    ("The answer is $\\boxed{12}$.", "12"),
    ("***\nANSWER: 33\n---", "33"),
    ("ANSWER: 1,000", "1000"),
    ("\\boxed{3} and \\boxed{4}", "4"),
    ("ANSWER: x=5", "5"),
    ("line ANSWER: 9", "9"),
]


def _aime_scorer() -> Callable[..., Any]:
    return importlib.import_module("inspect_evals.utils.aime_common").aime_scorer()


def _ours(op_id: str, text: str, target: str) -> tuple[bool, str | None]:
    """(equal, the member's number) by the engine's Inspect-rule operators."""
    word = _stage(op_id, "extract", text).value
    member = None if word is None else _stage("inspect_numeric@1", "normalize", word).value
    wanted = _stage("inspect_numeric@1", "normalize", target).value
    return member is not None and member == wanted, member


def _assert_parity(
    runner: asyncio.Runner, scorer: Callable[..., Any], op_id: str, text: str, target: str
) -> None:
    score = _inspect_score(runner, scorer, text, target)
    equal, member = _ours(op_id, text, target)
    assert (score.value == CORRECT) == equal, (text, target, score.answer, member)
    if member is not None:
        assert score.answer == member, (text, target)


@pytest.mark.parametrize(("text", "target"), _GSM8K_CORPUS)
def test_gsm8k_parity_corpus_matches_inspect_match_numeric(
    runner: asyncio.Runner, text: str, target: str
) -> None:
    _assert_parity(runner, match(numeric=True), "inspect_number@1", text, target)


@pytest.mark.parametrize(("text", "target"), _AIME_CORPUS)
def test_aime_parity_corpus_matches_aime_scorer(
    runner: asyncio.Runner, text: str, target: str
) -> None:
    _assert_parity(runner, _aime_scorer(), "inspect_aime@1", text, target)


def _voted_cases(op_id: str) -> list[tuple[str, str]]:
    """(input, value) of every voted golden case of one operator."""
    fixture = json.loads((_FIXTURE_DIR / f"{op_id}.json").read_text("utf-8"))
    return [
        (case["input"], case["expect"]["value"])
        for case in fixture["cases"]
        if case["expect"]["status"] == "voted"
    ]


@pytest.mark.parametrize("op_id", ["inspect_number@1", "inspect_aime@1", "inspect_numeric@1"])
def test_every_voted_golden_case_is_what_the_inspect_grader_reads(
    runner: asyncio.Runner, op_id: str
) -> None:
    cases = _voted_cases(op_id)
    assert cases
    scorer = _aime_scorer() if op_id == "inspect_aime@1" else match(numeric=True)
    for text, value in cases:
        # a number operator's value is the word Inspect read; a normalizer's value is the answer
        target = text if op_id == "inspect_numeric@1" else value
        score = _inspect_score(runner, scorer, text, target)
        assert score.value == CORRECT, (op_id, text)
        expected = value if op_id == "inspect_numeric@1" else _normalized(value)
        assert score.answer == expected, (op_id, text)


def _normalized(word: str) -> str | None:
    return _stage("inspect_numeric@1", "normalize", word).value


# --- GP#5: generated numbers in many written forms ---------------------------------------------

_CJK_DIGITS = "零一二三四五六七八九"


def _cjk(number: int) -> str:
    tens, ones = divmod(number, 10)
    prefix = "" if tens == 0 else ("" if tens == 1 else _CJK_DIGITS[tens]) + "十"
    return prefix + (_CJK_DIGITS[ones] if ones or tens == 0 else "")


def _grouped(text: str) -> str:
    sign = "-" if text.startswith("-") else ""
    whole, point, fraction = text.lstrip("-").partition(".")
    return f"{sign}{int(whole):,}{point}{fraction}"


_FORMS: tuple[Callable[[str], str], ...] = (
    lambda s: s,
    _grouped,
    lambda s: "$" + s,
    lambda s: s + ".",
    lambda s: s if "." in s else s + ".0",
    lambda s: f"{float(s):.3e}",
    lambda s: s.replace("-", "−"),
    lambda s: s.translate({ord(d): ord(d) + 0xFEE0 for d in "0123456789"}),
    lambda s: s + "²",
    lambda s: s + "½",
    lambda s: "\\$" + s,
)
_SENTENCES = (
    "{w}",
    "The answer is {w}.",
    "So we get {w} apples",
    "x={w}",
    "({w})",
    "{w}%",
    "~{w}",
    "{w} then 7 more",
)
_AIME_WRAPPERS = (
    "Work\nANSWER: {w}",
    "\\boxed{{{w}}}",
    "$$\n\\boxed{{{w}}}\n$$",
    "ANSWER: {w}\nbecause 3",
)
_GENERATED_ROWS = 2000


def _word(rng: random.Random) -> tuple[str, str]:
    """(the written number word, the target) of one generated row."""
    if rng.random() < 0.08:
        base: int | str = rng.randint(0, 99)
        word = _cjk(int(base))
    else:
        base = (
            str(rng.randint(-(10**7), 10**7))
            if rng.random() < 0.5
            else f"{rng.uniform(-10000, 10000):.{rng.randint(1, 3)}f}"
        )
        word = rng.choice(_FORMS)(base)
    target = str(base) if rng.random() < 0.5 else str(rng.randint(-(10**7), 10**7))
    return word, target


def _generated(rule: str) -> list[tuple[str, str]]:
    rng = random.Random(1289)
    templates = _SENTENCES if rule == "number" else _AIME_WRAPPERS
    rows: list[tuple[str, str]] = []
    for _ in range(_GENERATED_ROWS):
        word, target = _word(rng)
        rows.append((rng.choice(templates).format(w=word), target))
    return rows


def test_parity_holds_for_generated_numbers(runner: asyncio.Runner) -> None:
    for text, target in _generated("number"):
        _assert_parity(runner, match(numeric=True), "inspect_number@1", text, target)
    aime = _aime_scorer()
    for text, target in _generated("aime"):
        _assert_parity(runner, aime, "inspect_aime@1", text, target)
