# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages and Pillow (the
# `benchmarks` extra), absent in the default (extra-less) install the typecheck gate runs against.
"""HLE's one oversized picture is shrunk to 8000 px on its long side, and nothing else moves.

FEATURE: OME-1970 PR 1 of 9. Hub row ``66f1b940f8bb4425f74e4299`` (``hle`` Case 250,
``hle_diamond`` Case 35) carries a 14950×2780 px PNG. On the 6 Nov prod HLE runs every Claude
Candidate refused it (Claude takes at most 8000 px per side) and so did gpt-6-astra-pro and
gpt-6.1-terra-pro ("requires 40716 patches after processing, exceeding the limit of 30000").
Both rows declare it in ``shrunk_picture_sample_ids``, a Named Deviation: Case Preparation
shrinks that picture to 8000×1488 before capture.

INVARIANT pinned here: only a listed Sample's over-limit pictures change, and the deviation
refuses to run when it no longer describes the data (the id is gone, or its pictures already
fit), so it can never go stale quietly.

Stand-ins: pictures are drawn with Pillow at a small height (9000×30), so a test never holds
the real 166 MB of pixels; the real row's size is checked through ``shrunk_size`` alone.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")
pytest.importorskip("PIL")

from inspect_ai.dataset import Sample  # noqa: E402
from inspect_ai.model import (  # noqa: E402
    ChatMessageSystem,
    ChatMessageUser,
    ContentImage,
    ContentText,
)
from inspect_evals.utils import create_stable_id  # noqa: E402
from PIL import Image  # noqa: E402
from replayed_cases_helpers import replay_in_process_over_rows  # noqa: E402

from screamingface_engine_inspect.benchmarks import _task_replay_pins  # noqa: E402
from screamingface_engine_inspect.prepare import (  # noqa: E402
    HLE_OVERSIZED_PICTURE_SAMPLE_IDS,
    TASK_REPLAY_CASES,
    PreparedCase,
    PrepareError,
)
from screamingface_engine_inspect.shrunk_pictures import (  # noqa: E402
    MAX_PICTURE_SIDE_PX,
    shrunk_size,
    with_shrunk_pictures,
)

#: The cais/hle row whose picture no Claude or GPT-pro model accepts (also in cais/hle-diamond).
OVERSIZED_ROW_ID: str = "66f1b940f8bb4425f74e4299"

#: The stand-in oversized picture: wider than the limit, short enough to stay cheap.
WIDE: tuple[int, int] = (9000, 30)


def _png(size: tuple[int, int], mode: str = "RGBA") -> bytes:
    """A stand-in picture's PNG bytes, half red and half blue so a resize has edges to keep."""

    picture: Image.Image = Image.new(mode, size, "red")
    picture.paste("blue", (0, 0, size[0] // 2, size[1]))
    buffer: io.BytesIO = io.BytesIO()
    picture.save(buffer, format="PNG")
    return buffer.getvalue()


def _data_uri(data: bytes, media_type: str = "image/png") -> str:
    """The picture as inspect_evals' hle hands it over: a base64 data URI."""

    return f"data:{media_type};base64," + base64.b64encode(data).decode("ascii")


def _picture_sample(sample_id: str, data_uri: str) -> Sample:
    """One Sample shaped as inspect_evals' hle builds it: system prompt, question, picture."""

    return Sample(
        id=sample_id,
        input=[
            ChatMessageSystem(content="Stand-in system prompt."),
            ChatMessageUser(
                content=[ContentText(text="Stand-in question?"), ContentImage(image=data_uri)]
            ),
        ],
        target="42",
    )


def _picture_of(sample: Sample) -> Image.Image:
    """Open the one picture a Sample carries."""

    assert not isinstance(sample.input, str)
    content: Any = sample.input[1].content
    image: str = content[1].image
    return Image.open(io.BytesIO(base64.b64decode(image.partition(",")[2])))


def test_the_real_row_shrinks_to_8000_by_1488() -> None:
    """14950×2780 keeps its aspect: 2780 × 8000 / 14950 = 1487.6 → 1488. WHY pin it: 8000×1488
    is under Claude's 8000 px per side and is 250 × 47 = 11,750 of GPT's 32 px patches, under its
    30,000 (the original needed 40,716)."""

    assert MAX_PICTURE_SIDE_PX == 8000
    assert shrunk_size(14950, 2780) == (8000, 1488)
    assert shrunk_size(2780, 14950) == (1488, 8000)
    assert shrunk_size(8000, 8000) == (8000, 8000)


def test_a_listed_sample_s_picture_is_shrunk_and_every_other_sample_is_untouched() -> None:
    """The listed Sample's 9000×30 RGBA PNG becomes 8000×27, still an RGBA PNG under the same
    data URI label; an unlisted Sample with the same oversized picture is the same object."""

    listed: Sample = _picture_sample("listed", _data_uri(_png(WIDE)))
    other: Sample = _picture_sample("other", _data_uri(_png(WIDE)))

    kept: list[Sample] = with_shrunk_pictures(("listed",), [listed, other])

    assert kept[1] is other
    shrunk: Image.Image = _picture_of(kept[0])
    assert (shrunk.size, shrunk.mode, shrunk.format) == ((8000, 27), "RGBA", "PNG")
    assert kept[0].id == "listed"
    assert kept[0].target == "42"
    # WHY: the deviation changes only the picture; the question and system prompt stay.
    before: Any = listed.input
    after: Any = kept[0].input
    assert after[0] == before[0]
    assert after[1].content[0] == before[1].content[0]


def test_the_shrink_writes_the_same_bytes_every_time() -> None:
    """WHY: the Case Digest seals the picture's bytes, so two builds must re-encode alike."""

    first: list[Sample] = with_shrunk_pictures(
        ("listed",), [_picture_sample("listed", _data_uri(_png(WIDE)))]
    )
    second: list[Sample] = with_shrunk_pictures(
        ("listed",), [_picture_sample("listed", _data_uri(_png(WIDE)))]
    )

    first_input: Any = first[0].input
    second_input: Any = second[0].input
    assert first_input[1].content[1].image == second_input[1].content[1].image


def test_a_listed_sample_whose_pictures_already_fit_is_refused() -> None:
    """WHY refuse: a deviation that changes nothing no longer describes the data (a new Hub
    revision fixed the picture, or the id names another row), so it must be removed by hand."""

    fitting: Sample = _picture_sample("listed", _data_uri(_png((8000, 30))))

    with pytest.raises(PrepareError, match="listed.*no picture over 8000 px"):
        with_shrunk_pictures(("listed",), [fitting])


def test_a_listed_id_missing_from_the_dataset_is_refused() -> None:
    """As ``excluded_sample_ids``: an id that matches no Sample describes nothing we can check."""

    with pytest.raises(PrepareError, match="gone.*not in the dataset"):
        with_shrunk_pictures(("gone",), [_picture_sample("other", _data_uri(_png(WIDE)))])


def test_an_oversized_picture_that_is_not_a_png_is_refused() -> None:
    """WHY: a PNG re-encode is lossless; a JPEG or WebP one would also choose a quality, a
    decision no row has made yet. Refuse, naming the format, rather than pick one quietly."""

    picture: Image.Image = Image.new("RGB", WIDE, "red")
    buffer: io.BytesIO = io.BytesIO()
    picture.save(buffer, format="JPEG")
    sample: Sample = _picture_sample("listed", _data_uri(buffer.getvalue(), "image/jpeg"))

    with pytest.raises(PrepareError, match="listed.*JPEG"):
        with_shrunk_pictures(("listed",), [sample])


def test_both_hle_rows_name_the_one_oversized_hub_row() -> None:
    """The declared id is inspect_evals' Sample id for Hub row 66f1b940…, the same row in both
    datasets; WHY pin the derivation: the Sample id is a hash, so only this ties it to the row."""

    assert HLE_OVERSIZED_PICTURE_SAMPLE_IDS == (create_stable_id(OVERSIZED_ROW_ID, prefix="hle"),)
    for key in ("hle", "hle_diamond"):
        assert TASK_REPLAY_CASES[key].shrunk_picture_sample_ids == HLE_OVERSIZED_PICTURE_SAMPLE_IDS
    for key, spec in TASK_REPLAY_CASES.items():
        if key not in ("hle", "hle_diamond"):
            assert spec.shrunk_picture_sample_ids is None, key


def test_the_deviation_rides_benchmark_identity() -> None:
    """A Named Deviation is written on the Benchmark and included in its revision, as the
    excluded Sample ids are (CONTEXT.md)."""

    assert "shrunk_picture_sample_ids=hle_350ce3fb" in _task_replay_pins(TASK_REPLAY_CASES["hle"])


def _hub_row(uid: str, image: str, key: str) -> dict[str, Any]:
    """One stand-in cais/hle (or cais/hle-diamond) row in the Hub's shape."""

    row: dict[str, Any] = {
        "id": uid,
        "question": f"Stand-in question {uid}?",
        "image": image,
        "image_preview": None,
        "answer": "42",
        "answer_type": "exactMatch",
        "author_name": "Stand-in author",
        "rationale": "",
        "rationale_image": None,
        "raw_subject": "Mathematics",
        "category": "Math",
        "canary": "",
    }
    if key == "hle_diamond":
        row["partition"] = "reasoning"
    return row


def _case_picture(case: PreparedCase) -> Image.Image:
    """Open the picture a prepared picture Case carries in its input envelope."""

    [message] = json.loads(case["case"]["input"])["messages"]
    url: str = message["content"][-1]["image_url"]["url"]
    return Image.open(io.BytesIO(base64.b64decode(url.partition(",")[2])))


@pytest.mark.parametrize("key", ["hle", "hle_diamond"])
def test_the_real_task_serves_the_named_row_shrunk_and_the_next_row_as_it_was(
    key: str, tmp_path: Path
) -> None:
    """Through the row's real Task and capture: the Hub row named by the deviation reaches the
    Candidate at 8000 px wide, and a second oversized row the deviation does not name keeps its
    9000 px (a later seal check, not this deviation, is what refuses such a row)."""

    original: str = _data_uri(_png(WIDE))
    rows: list[dict[str, Any]] = [
        _hub_row(OVERSIZED_ROW_ID, original, key),
        _hub_row("stand-in-unlisted", original, key),
    ]

    prepared: list[PreparedCase] = replay_in_process_over_rows(
        key, rows, tmp_path, shrink_named_pictures=True
    )

    assert _case_picture(prepared[0]).size == (8000, 27)
    assert _case_picture(prepared[1]).size == WIDE


@pytest.mark.parametrize("key", ["hle", "hle_diamond"])
def test_the_real_task_refuses_when_the_named_row_s_picture_already_fits(
    key: str, tmp_path: Path
) -> None:
    """The stale-deviation refusal fires on the real path too, so an image build stops."""

    rows: list[dict[str, Any]] = [_hub_row(OVERSIZED_ROW_ID, _data_uri(_png((100, 30))), key)]

    with pytest.raises(PrepareError, match="no picture over 8000 px"):
        replay_in_process_over_rows(key, rows, tmp_path, shrink_named_pictures=True)
