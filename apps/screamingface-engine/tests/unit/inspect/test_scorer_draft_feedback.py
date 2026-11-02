# pyright: reportMissingImports=false
# WHY file-level: the stand-in scorer imports inspect_ai, absent in the extra-less typecheck.
"""Draft Feedback that carries the scorer's own words, for a Benchmark the owner allowed.

FEATURE (OME-1527, R9): the Corrective Loop's mid-run check on the plugin lane sends the Case
score (0 or 1 for IFEval's strict headline) and one fixed sentence. A row that sets
``scorer_draft_feedback`` sends what its scorer wrote for the Candidate under
``Score.metadata["draft_feedback"]`` instead: a partial score and the checker's own words, as
the hand-built IFEval route does.

The trust line these tests pin: those words enter the Candidate's context, so the lane reads
that one key and nothing else of the Score. The stand-in scorer below would leak the answer
key ("42") through every other channel it has (its explanation, an extra metadata key, an
extra field inside the envelope), so each test fails loudly if a guard goes missing.

Runs only with the `inspect` extra installed; the plain gate run skips it.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.scorer import Score, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from replayed_cases_helpers import prepare_with_stand_in_hub  # noqa: E402

from screamingface_engine.benchmarks.contract import encode_candidate_invocation  # noqa: E402
from screamingface_engine.benchmarks.ensemble.policy import DRAFT_FEEDBACK_SCHEMA  # noqa: E402
from screamingface_engine_inspect import benchmarks, single_shot  # noqa: E402
from screamingface_engine_inspect.benchmarks import BENCHMARKS, imported_benchmark  # noqa: E402
from screamingface_engine_inspect.single_shot import (  # noqa: E402
    DRAFT_FEEDBACK_METADATA_KEY,
    ImportedBenchmark,
)
from url4 import RelExpr, Text, expr, render, src, text  # noqa: E402
from url4.peer.server import Url4Node  # noqa: E402

#: The stand-in Cases: gsm8k's row shape, so the answer key of Case 1 is "42".
_ROWS: list[dict[str, Any]] = [
    {"question": "What is 6 times 7?", "answer": "6 * 7 = 42\n#### 42"},
    {"question": "A train travels 30 km twice. Total?", "answer": "30 + 30 = 60\n#### 60"},
]
_GOLD: str = "42"

#: The words the stand-in scorer writes for the Candidate: about the form, never the answer.
_SAFE_WORDS: str = "Put the final number on its own line as 'ANSWER: <n>'."

#: What the scorer writes under the Draft Feedback key, given whether the draft passed.
type EnvelopeFor = Callable[[bool], object]


def _honest(passed: bool) -> object:
    """A well-formed envelope: fully satisfied on a pass, half on a fail, with safe words."""

    return {"satisfaction": 1.0 if passed else 0.5, "feedback": _SAFE_WORDS}


def _leaky_scorer(envelope_for: EnvelopeFor) -> Callable[[TaskState, Target], Any]:
    """A scorer that marks the reply right or wrong and leaks the key everywhere it can.

    Its explanation quotes the target and an extra metadata key holds it, so only a lane
    that reads the Draft Feedback key alone keeps "42" out of the Candidate's context.
    """

    async def score(state: TaskState, target: Target) -> Score:
        """Mark the reply against the key, writing the key into every other channel."""

        passed: bool = state.output.completion.strip().endswith(target.text)
        return Score(
            value=1.0 if passed else 0.0,
            answer=state.output.completion,
            explanation=f"expected {target.text}",
            metadata={"gold": target.text, DRAFT_FEEDBACK_METADATA_KEY: envelope_for(passed)},
        )

    return score


def _stand_in(
    monkeypatch: pytest.MonkeyPatch, *, scorer_draft_feedback: bool, envelope_for: EnvelopeFor
) -> ImportedBenchmark:
    """gsm8k's row WITH the Draft Feedback offer, its scorer swapped for the leaky stand-in.

    WHY a stand-in (OME-1513): the offer is a per-Benchmark owner decision and no imported row
    carries it today, so these tests prove the lane's CODE on gsm8k's row with the flags
    flipped, not any catalogue entry.
    """

    spec = replace(
        next(row for row in BENCHMARKS if row.key == "gsm8k"),
        with_check_surface=True,
        scorer_draft_feedback=scorer_draft_feedback,
    )
    monkeypatch.setattr(benchmarks, "BENCHMARKS", (spec,))
    monkeypatch.setattr(benchmarks, "_ASSEMBLED", {})
    monkeypatch.setattr(single_shot, "_BENCHMARKS_BY_ID", {})
    probe: ImportedBenchmark = imported_benchmark("gsm8k")
    stand_in: ImportedBenchmark = replace(probe, scorer_factory=lambda: _leaky_scorer(envelope_for))
    # The installer resolves its Benchmark by id at install time, so it serves the stand-in.
    single_shot._BENCHMARKS_BY_ID[probe.benchmark.id] = stand_in
    return stand_in


def _node(stand_in: ImportedBenchmark, root: Path) -> Url4Node:
    """A node serving the stand-in over the two prepared Cases."""

    prepare_with_stand_in_hub("gsm8k", _ROWS, root / stand_in.benchmark.id)
    node: Url4Node = Url4Node("test")
    stand_in.benchmark.install(node, root)
    return node


async def _call(node: Url4Node, route: str, payload: str, intent: str) -> str:
    """Send one request to a route, as a client-compiled expression would."""

    result = await node.evaluate(
        render(
            expr(
                src(text(payload), name="payload", weight=0.0),
                RelExpr(path=route, context="$payload", intent=Text(intent)),
                intent=Text(""),
            )
        )
    )
    return result.text


async def _check(
    node: Url4Node, stand_in: ImportedBenchmark, root: Path, answer: str
) -> dict[str, Any]:
    """Ask the mid-run check about Case 1 with ``answer`` as the draft."""

    booklet: Path = root / stand_in.benchmark.id / "cases.json"
    prompt: str = json.loads(booklet.read_text(encoding="utf-8"))[0]["input"]
    payload: str = json.dumps(
        {"input": prompt, "invocation": encode_candidate_invocation(answer, "stop", None)}
    )
    reply: str = await _call(node, stand_in.check_surface_route, payload, "check")
    return json.loads(reply)


@pytest.mark.asyncio
async def test_an_allowed_row_sends_the_scorers_partial_score_and_words_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guarantee: a failing draft gets the scorer's partial score and its words for the
    Candidate, in the hand-built IFEval record's exact shape, and not one byte of what the
    scorer kept for the marking room (its explanation and its "gold" note both say "42")."""

    stand_in = _stand_in(monkeypatch, scorer_draft_feedback=True, envelope_for=_honest)
    node = _node(stand_in, tmp_path)

    record = await _check(node, stand_in, tmp_path, "ANSWER: 59")

    assert list(record) == ["schema", "passed", "satisfaction", "feedback", "answer", "invocation"]
    assert record["schema"] == DRAFT_FEEDBACK_SCHEMA
    assert record["passed"] is False
    assert record["satisfaction"] == 0.5
    assert record["feedback"] == _SAFE_WORDS
    assert record["answer"] == "ANSWER: 59"
    assert _GOLD not in json.dumps(record)
    # The feedback intent is what reaches the Candidate: exactly the scorer's words.
    reply: str = await _call(node, stand_in.check_surface_route, json.dumps(record), "feedback")
    assert reply == _SAFE_WORDS


@pytest.mark.asyncio
async def test_a_passing_draft_is_fully_satisfied_and_gets_no_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As the hand-built route does: a draft that passes is told nothing more."""

    stand_in = _stand_in(monkeypatch, scorer_draft_feedback=True, envelope_for=_honest)
    node = _node(stand_in, tmp_path)

    record = await _check(node, stand_in, tmp_path, "ANSWER: 42")

    assert (record["passed"], record["satisfaction"], record["feedback"]) == (True, 1.0, "")


@pytest.mark.asyncio
async def test_a_row_that_did_not_opt_in_keeps_the_fixed_sentence_whatever_its_scorer_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scorer alone can't open the channel: without the row flag the same scorer's words
    are ignored and the Candidate gets the fixed sentence and the Case score, byte-identical
    to every offer before this change."""

    stand_in = _stand_in(monkeypatch, scorer_draft_feedback=False, envelope_for=_honest)
    node = _node(stand_in, tmp_path)

    record = await _check(node, stand_in, tmp_path, "ANSWER: 59")

    assert record["satisfaction"] == 0.0
    assert record["feedback"] == single_shot._CHECK_FEEDBACK


#: Words a scorer must never get through, marked so a refusal that quoted them would show.
_MARKED: str = "MARKED-WORDS "


@pytest.mark.parametrize(
    ("envelope_for", "refusal"),
    [
        pytest.param(lambda passed: None, "exactly satisfaction and feedback", id="missing"),
        pytest.param(
            lambda passed: {"satisfaction": 0.5, "feedback": _SAFE_WORDS, "gold": _GOLD},
            "exactly satisfaction and feedback",
            id="an-extra-field",
        ),
        pytest.param(
            lambda passed: {"satisfaction": True, "feedback": _SAFE_WORDS},
            r"number in \[0, 1\]",
            id="a-bool",
        ),
        pytest.param(
            lambda passed: {"satisfaction": 1.5, "feedback": _SAFE_WORDS},
            r"number in \[0, 1\]",
            id="above-one",
        ),
        pytest.param(
            lambda passed: {"satisfaction": math.nan, "feedback": _SAFE_WORDS},
            r"number in \[0, 1\]",
            id="nan",
        ),
        pytest.param(
            lambda passed: {"satisfaction": 1.0, "feedback": _SAFE_WORDS},
            "disagrees with its verdict",
            id="fully-satisfied-but-failed",
        ),
        pytest.param(
            lambda passed: {"satisfaction": 0.5, "feedback": 42},
            "must be text of at most 2000 characters",
            id="not-text",
        ),
        pytest.param(
            lambda passed: {"satisfaction": 0.5, "feedback": _MARKED * 154},
            "must be text of at most 2000 characters",
            id="too-long",
        ),
        pytest.param(
            lambda passed: {"satisfaction": 0.5, "feedback": "  "},
            "no draft-feedback words for a failing draft",
            id="no-words",
        ),
    ],
)
@pytest.mark.asyncio
async def test_an_envelope_the_lane_cannot_vouch_for_is_refused_without_quoting_it(
    envelope_for: EnvelopeFor, refusal: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every malformed envelope stops the check by name; none is trimmed, defaulted or sent.

    WHY refuse, not trim: a cut sentence or a guessed score would still reach the Candidate
    as if the scorer had said it. The refusal names the problem and never quotes the
    scorer's text, so the error can't become the leak."""

    stand_in = _stand_in(monkeypatch, scorer_draft_feedback=True, envelope_for=envelope_for)
    node = _node(stand_in, tmp_path)

    with pytest.raises(Exception, match=refusal) as refused:
        await _check(node, stand_in, tmp_path, "ANSWER: 59")

    assert _MARKED.strip() not in str(refused.value)
    assert _SAFE_WORDS not in str(refused.value)


def test_the_scorers_words_are_benchmark_identity_and_need_the_offer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turning the words on is a different exam, so the revision moves; turning them on
    without the owner-allowed offer is refused at assembly, never quietly ignored."""

    offer_only: str = _stand_in(
        monkeypatch, scorer_draft_feedback=False, envelope_for=_honest
    ).fingerprint
    with_words: str = _stand_in(
        monkeypatch, scorer_draft_feedback=True, envelope_for=_honest
    ).fingerprint
    assert with_words != offer_only

    spec = replace(
        next(row for row in BENCHMARKS if row.key == "gsm8k"),
        with_check_surface=False,
        scorer_draft_feedback=True,
    )
    monkeypatch.setattr(benchmarks, "BENCHMARKS", (spec,))
    monkeypatch.setattr(benchmarks, "_ASSEMBLED", {})
    monkeypatch.setattr(single_shot, "_BENCHMARKS_BY_ID", {})
    with pytest.raises(ValueError, match="needs a Draft Feedback offer"):
        imported_benchmark("gsm8k")
