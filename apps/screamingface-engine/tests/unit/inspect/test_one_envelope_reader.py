# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Every inspect reader opens the candidate-input envelope through the one shared parser
(OME-1271).

INVARIANT the suite defends: the inspect plugin reads a Case input by the connector's own rules
(``benchmarks/candidate_input.py``, OME-1678). A v2 envelope, a Case whose user message carries
a picture inline, is an envelope here too: the wrapping step serves it as written, the scorer
rebuilds it as inspect's own picture parts, and any other version of the schema is refused by
name. Before, the inspect reader knew v1 only, so a v2 Case was sealed as plain text inside a
v1 envelope and its base64 reached the Candidate and the judge as tokens, with no error.

No importer writes a v2 Case yet, so these tests build the envelopes directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.model import ContentDocument, ContentImage, ContentText  # noqa: E402
from inspect_ai.scorer import Score, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_V2_SCHEMA  # noqa: E402
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect.conversation_input import conversation_messages  # noqa: E402
from screamingface_engine_inspect.scorer_adapter import inspect_grade_case  # noqa: E402
from screamingface_engine_inspect.single_shot import _cases  # noqa: E402

# WHY short stand-in payloads: nothing on this path decodes a picture (the shared parser checks
# only the data: prefix), so any non-empty base64 stands in for real bytes. The base64 text is
# what must never show up in a message's text.
_PNG_BASE64: str = "iVBORw0KGgo="
_PNG: str = f"data:image/png;base64,{_PNG_BASE64}"
_PDF_BASE64: str = "JVBERi0xLjQ="
_PDF: str = f"data:application/pdf;base64,{_PDF_BASE64}"
_QUESTION: str = "What is the height of the tallest bar?"

#: A v2 Case as the importer will write it: one user message, its question then its chart.
#: Compact separators, so a re-serialisation by the wrapping step would show as a byte change.
V2_CASE: str = json.dumps(
    {
        "schema": CANDIDATE_INPUT_V2_SCHEMA,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _QUESTION},
                    {"type": "image_url", "image_url": {"url": _PNG, "detail": "low"}},
                ],
            }
        ],
    },
    separators=(",", ":"),
)


def _served(tmp_path: Path, inputs: list[str]) -> list[str]:
    """What the wrapping step serves the Candidate for Cases with these inputs."""

    rows: list[dict[str, Any]] = [
        {"id": index, "case_id": str(index), "input": text}
        for index, text in enumerate(inputs, start=1)
    ]
    (tmp_path / "cases.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    served: list[dict[str, Any]] = json.loads(_cases(tmp_path, envelope=True)())
    return [row["input"] for row in served]


# ── the wrapping step ──────────────────────────────────────────────────────────


def test_a_v2_case_passes_through_the_wrapping_step_unchanged(tmp_path: Path) -> None:
    """The headline guarantee: a v2 Case is already an envelope, so it is served byte for byte
    and never sealed as text inside a v1 envelope (which would send its base64 as tokens). Its
    plain neighbour is still wrapped exactly as on main, so text-only Benchmarks do not move."""

    served: list[str] = _served(tmp_path, ["Dos días.", V2_CASE])

    # The hand-built preparer's bytes for a one-message chat, pasted, never computed here.
    assert served[0] == (
        '{"schema":"screamingface.candidate-input.v1","messages":['
        '{"role":"user","content":"Dos días."}]}'
    )
    assert served[1] == V2_CASE


@pytest.mark.parametrize("schema", ["v0", "v3", "v2-beta"])
def test_an_unknown_schema_is_refused_by_the_wrapping_step(tmp_path: Path, schema: str) -> None:
    """A Case naming a candidate-input version this Engine cannot read is refused by name. The
    old reader treated it as a plain prompt and wrapped it, so the Candidate would have been
    paid to answer an envelope it was never meant to see."""

    unknown: str = json.dumps(
        {
            "schema": f"screamingface.candidate-input.{schema}",
            "messages": [{"role": "user", "content": "x"}],
        }
    )

    with pytest.raises(ValueError, match="unsupported schema"):
        _served(tmp_path, [unknown])


# ── the inspect reader ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("schema", ["v0", "v3", "v2-beta"])
def test_the_inspect_reader_refuses_an_unknown_schema(schema: str) -> None:
    """The scorer's reader follows the same rule: an unknown version is a damaged Case, never a
    prompt graded as written."""

    unknown: str = json.dumps(
        {
            "schema": f"screamingface.candidate-input.{schema}",
            "messages": [{"role": "user", "content": "x"}],
        }
    )

    with pytest.raises(ValueError, match="conversation.*unsupported schema"):
        conversation_messages(unknown)


def test_the_inspect_reader_keeps_refusing_a_developer_turn_in_v2() -> None:
    """The shared parser admits a ``developer`` turn (the connector can send one), but inspect
    has no such message, so the scorer could not rebuild it: the inspect-only role rule still
    applies on top of the shared one, in v2 as in v1."""

    with_developer: str = json.dumps(
        {
            "schema": CANDIDATE_INPUT_V2_SCHEMA,
            "messages": [
                {"role": "developer", "content": "Be brief."},
                json.loads(V2_CASE)["messages"][0],
            ],
        }
    )

    with pytest.raises(ValueError, match="conversation message 0"):
        conversation_messages(with_developer)


# ── the scorer ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_scorer_gets_a_v2_picture_as_inspect_content_never_base64_text() -> None:
    """The scorer reads the chat the Candidate was shown, in inspect's own types: the picture is
    a ``ContentImage`` (detail kept), the PDF a ``ContentDocument``, in the order the Case wrote
    them. inspect's ``input_text``, what a judge prompt quotes, is the question alone: no raw
    JSON, no base64."""

    seen: dict[str, Any] = {}

    async def scorer(state: TaskState, target: Target) -> Score:
        seen["messages"] = state.messages
        seen["input"] = state.input
        seen["input_text"] = state.input_text
        return Score(value=1.0)

    case: dict[str, Any] = json.loads(V2_CASE)
    case["messages"][0]["content"].append(
        {"type": "file", "file": {"file_data": _PDF, "filename": "chart.pdf"}}
    )
    request: GradeRequest = GradeRequest(
        case_id=1,
        input=TextPayload(text=json.dumps(case, separators=(",", ":"))),
        answer=TextPayload(text="42"),
        row={"case": {"status": "answered"}},
        material={"target": "42"},
    )

    outcome = await inspect_grade_case(scorer)(request)

    assert outcome.score == 1.0
    for chat in (seen["messages"], seen["input"]):
        assert [message.role for message in chat] == ["user"]
        parts: Any = chat[0].content
        assert isinstance(parts[0], ContentText) and parts[0].text == _QUESTION
        assert isinstance(parts[1], ContentImage)
        assert (parts[1].image, parts[1].detail) == (_PNG, "low")
        assert isinstance(parts[2], ContentDocument)
        assert (parts[2].document, parts[2].filename) == (_PDF, "chart.pdf")
        assert len(parts) == 3
        assert chat[0].text == _QUESTION
    assert seen["input_text"] == _QUESTION
