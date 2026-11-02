"""A run parks each Case's pictures and files in the result store, named by their sha256 (OME-1271).

FEATURE (OME-1271, PR 5): a Case Result shows each picture as a placeholder (type, size, sha256).
The client-facing engine can't read the Benchmark files, but it serves the result store at
``GET /artifacts/{id}``, and that store names every item by the sha256 of its bytes. So the run
parks each picture there, and the placeholder's sha256 is the claim ticket.
STORY: as a researcher reading why Case 17 was marked wrong, I open its figure from the result
and know it is the one the model saw.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from screamingface_engine import job_env
from screamingface_engine.artifacts import FilesystemArtifactStore, LocalFile, S3StorageError
from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    finalize_candidate_result,
)
from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_V2_SCHEMA
from screamingface_engine.benchmarks.media_parking import (
    MediaParking,
    park_case_media,
    park_cases_media,
    parking_media,
)
from screamingface_engine.runner.main import build_executor
from screamingface_engine.runner.operation_capture import OperationCapturingExecutor
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from url4.streaming.interfaces import Completed, ExecStep, Executor, TraceContext
from url4.streaming.protocol import LogData
from url4.streaming.protocol.signals import ResultArtifact

# The 8-byte PNG signature and the 8 bytes b"%PDF-1.4", with their sha256 (the same stand-ins
# and digests test_echoed_input.py pins).
_PNG = "data:image/png;base64,iVBORw0KGgo="
_PNG_BYTES = b"\x89PNG\r\n\x1a\n"
_PNG_SHA256 = "4c4b6a3be1314ab86138bef4314dde022e600960d8689a2c8f8631802d20dab6"
_PDF = "data:application/pdf;base64,JVBERi0xLjQ="
_PDF_SHA256 = "e16fa5d9b51928755db85b917f0297babaf22c7a47e97d9212adab56e61ba04e"
_QUESTION = {"type": "text", "text": "What is the height of the tallest bar?"}


def _v2(*parts: object) -> str:
    """One user message of ``parts``, sealed in a v2 envelope as the importer writes it."""

    return json.dumps(
        {
            "schema": CANDIDATE_INPUT_V2_SCHEMA,
            "messages": [{"role": "user", "content": list(parts)}],
        },
        separators=(",", ":"),
    )


def _picture(uri: str = _PNG) -> dict[str, Any]:
    """One picture part carrying ``uri``."""

    return {"type": "image_url", "image_url": {"url": uri}}


class _RecordingWriter:
    """A result store stand-in that keeps every write, so a test can count them."""

    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write_bytes(self, encoded: bytes) -> ResultArtifact:
        """Keep the bytes; answer the ticket a content-addressed store would."""

        self.written.append(encoded)
        digest: str = hashlib.sha256(encoded).hexdigest()
        return ResultArtifact(id=digest, size_bytes=len(encoded), sha256=digest)

    def write_text(self, body: str) -> ResultArtifact:
        """Park text as UTF-8, as the port says."""

        return self.write_bytes(body.encode("utf-8"))


class _UnreachableWriter(_RecordingWriter):
    """A result store whose object storage can't be reached; it counts each attempt."""

    def __init__(self) -> None:
        super().__init__()
        self.attempts: int = 0

    def write_bytes(self, encoded: bytes) -> ResultArtifact:
        """Fail the way the S3 adapter does when the bucket is unreachable."""

        self.attempts += 1
        raise S3StorageError("PUT 4c4b… could not reach object storage: timed out")


def test_a_picture_is_parked_as_its_decoded_bytes_under_the_placeholders_sha256(
    tmp_path: Path,
) -> None:
    # INVARIANT: the store's name for the picture IS the placeholder's sha256, so the SDK can
    # fetch it with nothing but the placeholder. The real filesystem store, not a stand-in.
    store = FilesystemArtifactStore(tmp_path)

    MediaParking(store).park(_v2(_QUESTION, _picture()))

    content = store.content(_PNG_SHA256)
    assert isinstance(content, LocalFile)
    assert content.path.read_bytes() == _PNG_BYTES


def test_a_file_part_is_parked_too() -> None:
    writer = _RecordingWriter()

    MediaParking(writer).park(
        _v2(_QUESTION, {"type": "file", "file": {"file_data": _PDF, "filename": "methods.pdf"}})
    )

    assert [hashlib.sha256(data).hexdigest() for data in writer.written] == [_PDF_SHA256]


def test_a_picture_seen_again_in_the_same_run_is_written_once() -> None:
    # WHY: every Candidate of a run finishes over the same Cases, so a lineup of four would
    # otherwise upload FigQA's pictures four times; two Cases sharing a figure count too.
    writer = _RecordingWriter()
    parking = MediaParking(writer)
    case_input: str = _v2(_QUESTION, _picture(), _picture())

    parking.park(case_input)
    parking.park(case_input)

    assert writer.written == [_PNG_BYTES]


@pytest.mark.parametrize(
    "case_input",
    [
        "What is 6 times 7?",
        json.dumps(
            {
                "schema": "screamingface.candidate-input.v1",
                "messages": [{"role": "user", "content": "What is 6 times 7?"}],
            }
        ),
        # A picture by URL: the reader refuses the Case, so there are no bytes to park.
        _v2(_QUESTION, _picture("https://cdn.example/fig.png")),
    ],
    ids=["plain prompt", "v1 conversation", "refused Case"],
)
def test_a_case_with_no_readable_picture_parks_nothing(case_input: str) -> None:
    writer = _RecordingWriter()

    MediaParking(writer).park(case_input)

    assert writer.written == []


def test_a_store_that_cannot_be_reached_is_logged_and_never_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # INVARIANT: parking is for looking at the picture later; a run that graded every Case
    # must not lose its result because the store was down. The log names the picture.
    with caplog.at_level(logging.WARNING):
        MediaParking(_UnreachableWriter()).park(_v2(_QUESTION, _picture()))

    assert _PNG_SHA256 in caplog.text


def test_a_store_that_fails_once_is_not_tried_again_in_the_same_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # WHY: a store that is down answers each write only at its timeout (30 s for S3), so
    # trying FigQA's 181 pictures would hold the run's finish for 90 minutes, once per
    # Candidate. Two pictures here, parked for two Candidates: one attempt, one warning.
    writer = _UnreachableWriter()
    parking = MediaParking(writer)
    case_input: str = _v2(_QUESTION, _picture(), {"type": "file", "file": {"file_data": _PDF}})

    with caplog.at_level(logging.WARNING):
        parking.park(case_input)
        parking.park(case_input)

    assert writer.attempts == 1
    assert len(caplog.records) == 1


def test_park_case_media_writes_only_inside_a_bound_run() -> None:
    writer = _RecordingWriter()
    case_input: str = _v2(_QUESTION, _picture())

    park_case_media(case_input)
    with parking_media(MediaParking(writer)):
        park_case_media(case_input)
    park_case_media(case_input)

    assert writer.written == [_PNG_BYTES]


# --- where a run parks: beside the finalizer, inside the run's binding -----------------------


def test_a_parked_picture_is_named_by_the_sha256_its_echoed_placeholder_shows() -> None:
    # INVARIANT: the claim ticket the published placeholder carries opens the parked bytes;
    # a mismatch would hand the researcher nothing, or worse, another picture.
    writer = _RecordingWriter()
    selected = SelectedCase(case_id=1, input=_v2(_QUESTION, _picture()), metadata={})

    with parking_media(MediaParking(writer)):
        park_cases_media([selected.input])
    result = finalize_candidate_result(
        failure_policy="withhold",
        benchmark_id="benchmark",
        benchmark_revision="revision",
        selected_cases=[selected],
        cases=[],
        scorer=lambda cases: CandidateScore(score=0.0, metrics={}),
    )

    echoed: dict[str, Any] = json.loads(result.as_payload()["cases"][0]["input"])
    placeholder: dict[str, Any] = echoed["messages"][0]["content"][1]["image_url"]["url"]
    assert [hashlib.sha256(data).hexdigest() for data in writer.written] == [placeholder["sha256"]]


class _ParkingProbe(Executor):
    """An inner executor whose every step parks the same picture Case."""

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        """Park once per step, over two steps, the way two Candidates finish in one run."""

        del url4, trace
        for _ in range(2):
            park_case_media(_v2(_QUESTION, _picture()))
            yield LogData.at("INFO", "finished a Candidate")


@pytest.mark.asyncio
async def test_the_run_wrapper_parks_into_its_store_once_per_run() -> None:
    writer = _RecordingWriter()

    steps = [
        step
        async for step in OperationCapturingExecutor(_ParkingProbe(), media_writer=writer).execute(
            "'run'"
        )
    ]

    assert len(steps) == 2
    assert writer.written == [_PNG_BYTES]


@pytest.mark.asyncio
async def test_a_composed_run_parks_into_the_result_store_from_inside_a_node_call(
    tmp_path: Path,
) -> None:
    # INVARIANT: the binding reaches a call the url4 interpreter makes inside the run, which
    # is where a Benchmark's aggregate finishes. WHY the model call as the probe: its mocked
    # gateway answers from inside that call, so parking there proves the reach without a
    # whole picture Benchmark.
    def respond(request: httpx.Request) -> httpx.Response:
        """Park the picture Case from inside the node call, then answer as the gateway."""

        park_case_media(_v2(_QUESTION, _picture()))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "a bar chart"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
            },
        )

    config = WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://gateway", default_model="model", models=(ModelSpec(id="model"),)
        )
    )
    async with httpx.AsyncClient(
        base_url="http://gateway", transport=httpx.MockTransport(respond)
    ) as client:
        executor = build_executor({job_env.ARTIFACTS_DIR: str(tmp_path)}, config, client=client)
        frames = [frame async for frame in executor.execute("/model('question')!go")]

    assert isinstance(frames[-1], Completed)
    content = FilesystemArtifactStore(tmp_path).content(_PNG_SHA256)
    assert isinstance(content, LocalFile)
    assert content.path.read_bytes() == _PNG_BYTES
