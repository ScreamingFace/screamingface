# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The importer saves an eval's pictures inside the Case, as the v2 envelope (OME-1271, PR 2).

FEATURE: Task replay captures what the eval's own solver chain hands the model at its first
``generate``. When that holds a picture (LAB-Bench FigQA: one figure, then the question), the
Case input is the v2 candidate-input envelope with each picture inline as a ``data:`` URI, so
every run serves the picture in place and nothing is ever fetched. INVARIANT: a Case the
importer cannot carry fails the import by name, never dropped and never quoting the picture.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai import Task  # noqa: E402
from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402
from inspect_ai.model import (  # noqa: E402
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    Content,
    ContentAudio,
    ContentImage,
    ContentText,
)
from inspect_ai.solver import Solver, generate, multiple_choice, system_message  # noqa: E402

from screamingface_engine.benchmarks.candidate_input import parse_candidate_input  # noqa: E402
from screamingface_engine_inspect.capture import captured_case_records  # noqa: E402
from screamingface_engine_inspect.conversation_input import conversation_messages  # noqa: E402
from screamingface_engine_inspect.picture_input import (  # noqa: E402
    MAX_CASE_BYTES,
    MAX_PICTURES,
    PictureCaseError,
)
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec, case_digest  # noqa: E402
from screamingface_engine_inspect.task_replay import replay_environment  # noqa: E402

# WHY these bytes: the PNG signature, then padding. The importer reads only the signature to
# name the type; nothing here opens the picture, so a real image would prove nothing more.
_PNG: bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
_PNG_B64: str = base64.b64encode(_PNG).decode("ascii")
# WHY an SVG: it is markup that can carry a script, the type the envelope refuses outright.
_SVG: bytes = b"<svg xmlns='http://www.w3.org/2000/svg'/>"

_QUESTION: str = "How tall is the bar?"
_CHOICES: list[str] = ["1", "2", "3"]

#: What inspect 0.3.263's ``multiple_choice()`` renders for _QUESTION and _CHOICES, written by
#: hand from its SINGLE_ANSWER_TEMPLATE, never computed by our code.
_RENDERED: str = (
    "Answer the following multiple choice question. The entire content of your response "
    "should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is "
    "one of A,B,C.\n\nHow tall is the bar?\n\nA) 1\nB) 2\nC) 3"
)

_UNSEALED: str = "0" * 64


def _data_uri(mime: str, data: bytes) -> str:
    """A picture the way inspect_evals' lab_bench writes one: a label it chose, then base64."""

    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _spec() -> TaskReplayCasesSpec:
    """A declaration whose seal nothing compares; capture reads only its writer options."""

    return TaskReplayCasesSpec(task="stand_in:task", case_count=1, case_digest=_UNSEALED)


def _sample(*messages: ChatMessage) -> Sample:
    """One Sample whose input is these messages, with three choices."""

    return Sample(input=list(messages), choices=_CHOICES, target="A", id=1)


def _figqa_sample(*parts: Content) -> Sample:
    """FigQA's shape (``record_to_sample_figqa``): the parts, then the question."""

    return _sample(ChatMessageUser(content=[*parts, ContentText(text=_QUESTION)]))


def _input(sample: Sample, chain: list[Solver] | None = None) -> str:
    """The one Case input the importer captures for ``sample`` under ``chain``."""

    task: Task = Task(dataset=MemoryDataset([sample]), solver=chain or [multiple_choice()])
    prepared = captured_case_records(task, _spec())
    return prepared[0]["case"]["input"]


def _refusal(sample: Sample, chain: list[Solver] | None = None) -> str:
    """The import's refusal for ``sample``, which must name the Case."""

    with pytest.raises(PictureCaseError) as caught:
        _input(sample, chain)
    message: str = str(caught.value)
    assert message.startswith("case 1: ")
    return message


# ── what the importer writes ─────────────────────────────────────────────────


def test_figqas_shape_is_saved_as_a_v2_envelope_with_the_picture_first() -> None:
    # INVARIANT: the Case is what inspect hands the model: multiple_choice rewrites the user
    # text and inspect keeps the picture ahead of it, so the picture comes first.
    case_input: str = _input(_figqa_sample(ContentImage(image=_data_uri("image/png", _PNG))))

    assert case_input == (
        '{"schema":"screamingface.candidate-input.v2","messages":[{"role":"user","content":['
        '{"type":"image_url","image_url":{"url":"data:image/png;base64,' + _PNG_B64 + '"}},'
        '{"type":"text","text":' + json.dumps(_RENDERED) + "}]}]}"
    )


def test_the_connector_and_the_scorer_read_the_saved_case_back() -> None:
    case_input: str = _input(_figqa_sample(ContentImage(image=_data_uri("image/png", _PNG))))

    expected = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG_B64}"}},
                {"type": "text", "text": _RENDERED},
            ],
        }
    ]
    assert parse_candidate_input(case_input) == expected
    assert conversation_messages(case_input) == expected


def test_a_text_only_case_keeps_its_plain_prompt() -> None:
    # INVARIANT: text Benchmarks do not change; only a Case with a picture is written as v2.
    assert _input(_sample(ChatMessageUser(content=[ContentText(text=_QUESTION)]))) == _RENDERED


def test_leading_system_text_becomes_the_first_text_part() -> None:
    # WHY: a Benchmark cannot address the Candidate's system role, so a text Case folds the
    # system text ahead of the prompt; a picture Case folds it the same way, as its own part.
    case_input: str = _input(
        _figqa_sample(ContentImage(image=_data_uri("image/png", _PNG))),
        [system_message("You read charts."), multiple_choice()],
    )

    messages = parse_candidate_input(case_input)
    assert messages is not None and len(messages) == 1
    content = messages[0]["content"]
    assert not isinstance(content, str)
    assert content[0] == {"type": "text", "text": "You read charts."}
    assert [part["type"] for part in content] == ["text", "image_url", "text"]


def test_the_case_digest_of_a_picture_case_is_the_same_on_a_second_capture() -> None:
    # INVARIANT: import seals the Cases from one run and refuses a second run that differs,
    # so the bytes written for a picture must be the same every time.
    sample: Sample = _figqa_sample(ContentImage(image=_data_uri("image/png", _PNG)))
    task: Task = Task(dataset=MemoryDataset([sample]), solver=[multiple_choice()])

    assert case_digest(captured_case_records(task, _spec())) == case_digest(
        captured_case_records(task, _spec())
    )


# ── the picture's type comes from its bytes ──────────────────────────────────


def test_a_picture_labelled_jpeg_is_written_with_the_type_its_bytes_carry() -> None:
    # WHY: inspect_evals labels every FigQA figure image/jpeg without looking, and a provider
    # can reject a picture whose label does not match its bytes.
    case_input: str = _input(_figqa_sample(ContentImage(image=_data_uri("image/jpeg", _PNG))))

    assert f'"url":"data:image/png;base64,{_PNG_B64}"' in case_input


@pytest.mark.parametrize(
    ("signature", "media_type"),
    [
        (b"\xff\xd8\xff\xe0", "image/jpeg"),
        (b"GIF89a", "image/gif"),
        (b"GIF87a", "image/gif"),
        (b"RIFF\x00\x00\x00\x00WEBP", "image/webp"),
    ],
)
def test_each_allowed_picture_type_is_named_from_its_signature(
    signature: bytes, media_type: str
) -> None:
    data: bytes = signature + b"\x00" * 8

    case_input: str = _input(_figqa_sample(ContentImage(image=_data_uri("image/png", data))))

    assert f'"url":"{_data_uri(media_type, data)}"' in case_input


def test_bytes_that_are_no_allowed_picture_are_refused() -> None:
    message: str = _refusal(_figqa_sample(ContentImage(image=_data_uri("image/png", _SVG))))

    assert "PNG, JPEG, GIF or WebP" in message
    assert base64.b64encode(_SVG).decode("ascii") not in message


def test_a_picture_that_is_not_valid_base64_is_refused() -> None:
    message: str = _refusal(_figqa_sample(ContentImage(image="data:image/png;base64,not base64!")))

    assert "base64" in message


# ── where a picture may come from ────────────────────────────────────────────


def test_a_picture_from_a_file_in_the_replay_cache_is_saved_inline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # STORY: MMMU and MathVista write their pictures into inspect_evals' cache and hand
    # inspect the file's path; the Case carries the bytes, so a run never reads the file.
    cache: Path = tmp_path / "cache"
    evals_cache: str = replay_environment(cache, {})["INSPECT_EVALS_CACHE_DIR"]
    monkeypatch.setenv("INSPECT_EVALS_CACHE_DIR", evals_cache)
    picture: Path = cache / "inspect_evals" / "mmmu" / "validation_1.png"
    picture.parent.mkdir(parents=True)
    picture.write_bytes(_PNG)

    case_input: str = _input(_figqa_sample(ContentImage(image=str(picture))))

    assert f'"url":"data:image/png;base64,{_PNG_B64}"' in case_input


def test_a_file_outside_the_replay_cache_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT: a picture file is read only from the import's own fresh cache, so a Case
    # never carries a file from the builder's disk.
    monkeypatch.setenv("INSPECT_EVALS_CACHE_DIR", str(tmp_path / "cache" / "inspect_evals"))
    elsewhere: Path = tmp_path / "home" / "secret.png"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_bytes(_PNG)

    message: str = _refusal(_figqa_sample(ContentImage(image=str(elsewhere))))

    assert "outside the import's cache" in message
    assert str(elsewhere) not in message


def test_a_picture_file_with_no_replay_cache_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INSPECT_EVALS_CACHE_DIR", raising=False)
    picture: Path = tmp_path / "a.png"
    picture.write_bytes(_PNG)

    assert "outside the import's cache" in _refusal(_figqa_sample(ContentImage(image=str(picture))))


@pytest.mark.parametrize(
    "url",
    [
        "https://insecure-website.com/a.png",
        "http://insecure-website.com/a.png",
        "s3://bucket/a.png",
    ],
)
def test_a_picture_by_url_is_refused_and_never_fetched(url: str) -> None:
    # INVARIANT: building a Case never fetches, so two imports of one revision agree.
    message: str = _refusal(_figqa_sample(ContentImage(image=url)))

    assert "by URL" in message
    assert "insecure-website.com" not in message and "bucket" not in message


def test_the_replay_cache_root_is_the_parent_of_inspect_evals_cache(tmp_path: Path) -> None:
    # WHY pinned: the file rule reads the import's cache root from INSPECT_EVALS_CACHE_DIR, so
    # it relies on the replay putting that cache directly under its root.
    env: dict[str, str] = replay_environment(tmp_path / "cache", {})

    assert Path(env["INSPECT_EVALS_CACHE_DIR"]).parent == tmp_path / "cache"


# ── detail ───────────────────────────────────────────────────────────────────


def test_inspects_default_detail_is_left_out() -> None:
    # WHY: inspect's auto is the provider's default too, so writing it only adds bytes.
    case_input: str = _input(
        _figqa_sample(ContentImage(image=_data_uri("image/png", _PNG), detail="auto"))
    )

    assert "detail" not in case_input


@pytest.mark.parametrize("detail", ["low", "high"])
def test_a_chosen_detail_is_kept(detail: str) -> None:
    case_input: str = _input(
        _figqa_sample(ContentImage(image=_data_uri("image/png", _PNG), detail=detail))  # type: ignore[arg-type]
    )

    messages = parse_candidate_input(case_input)
    assert messages is not None
    assert messages[0]["content"][0] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{_PNG_B64}", "detail": detail},
    }


def test_detail_original_is_refused() -> None:
    message: str = _refusal(
        _figqa_sample(ContentImage(image=_data_uri("image/png", _PNG), detail="original"))
    )

    assert "detail original" in message


# ── the per-Case limits ──────────────────────────────────────────────────────


def _picture_up_to(limit: int, *, over: bool = False) -> ContentImage:
    """The largest PNG whose data: URI fits in ``limit`` characters, or the smallest past it.

    e.g. limit 30 → the header (22 characters) plus 8 of base64 (6 bytes) is exactly 30; one
    byte more takes 4 more characters, 34. WHY not any exact size: base64 grows 4 at a time.
    """

    header: int = len("data:image/png;base64,")
    size: int = (limit - header) // 4 * 3 + (1 if over else 0)
    image: str = _data_uri("image/png", _PNG + b"\x00" * (size - len(_PNG)))
    assert (len(image) > limit) if over else (limit - 4 < len(image) <= limit)
    return ContentImage(image=image)


def test_one_big_picture_inside_the_case_limit_is_saved() -> None:
    # STORY: TableQA's Case 186 holds one 5.21 MB picture (measured 2026-10-26); there is no
    # limit per picture, only the Case's, so it imports (owner decision, 2026-10-26).
    case_input: str = _input(_figqa_sample(_picture_up_to(5_300_000)))

    assert len(case_input) > 5_300_000 - 4


def test_a_case_at_its_limit_is_saved_and_one_over_it_is_refused() -> None:
    # WHY the margin: the Case is the picture plus the envelope and the rendered question.
    _input(_figqa_sample(_picture_up_to(MAX_CASE_BYTES - 1_000)))

    message: str = _refusal(_figqa_sample(_picture_up_to(MAX_CASE_BYTES, over=True)))

    assert f"{MAX_CASE_BYTES:,}" in message


def test_a_case_over_its_limit_is_refused() -> None:
    # WHY two pictures: each is within its own limit, but together they pass the Case's.
    picture: ContentImage = _picture_up_to(MAX_CASE_BYTES // 2)

    message: str = _refusal(_figqa_sample(picture, picture))

    assert f"{MAX_CASE_BYTES:,}" in message


def test_more_pictures_than_the_limit_are_refused() -> None:
    picture: ContentImage = ContentImage(image=_data_uri("image/png", _PNG))
    _input(_figqa_sample(*[picture] * MAX_PICTURES))

    message: str = _refusal(_figqa_sample(*[picture] * (MAX_PICTURES + 1)))

    assert f"{MAX_PICTURES + 1} pictures" in message


def test_too_many_pictures_are_refused_before_any_is_read() -> None:
    # INVARIANT: the count comes first, so a Case with a hundred pictures is refused without
    # decoding a hundred pictures in the import child.
    # WHY a URL as every picture: reading one would refuse it as a URL; the count refusal proves
    # none was read.
    picture: ContentImage = ContentImage(image="https://insecure-website.com/a.png")

    message: str = _refusal(_figqa_sample(*[picture] * (MAX_PICTURES + 1)))

    assert f"{MAX_PICTURES + 1} pictures" in message


# ── shapes the importer refuses ──────────────────────────────────────────────


def test_a_picture_in_a_system_message_is_refused() -> None:
    # WHY: Anthropic's OAuth route drops non-text parts from system messages, so the envelope
    # takes pictures in user messages only.
    picture: ContentImage = ContentImage(image=_data_uri("image/png", _PNG))
    sample: Sample = _sample(
        ChatMessageSystem(content=[picture]), ChatMessageUser(content=_QUESTION)
    )

    assert "system message" in _refusal(sample)


def test_a_picture_inside_a_conversation_is_refused() -> None:
    picture: ContentImage = ContentImage(image=_data_uri("image/png", _PNG))
    sample: Sample = _sample(
        ChatMessageUser(content="What is 2 plus 2?"),
        ChatMessageAssistant(content="4"),
        ChatMessageUser(content=[picture, ContentText(text=_QUESTION)]),
    )

    assert "conversation" in _refusal(sample, [generate()])


def test_an_audio_part_is_refused() -> None:
    audio: ContentAudio = ContentAudio(audio="data:audio/wav;base64,UklGRg==", format="wav")

    message: str = _refusal(_figqa_sample(audio))

    assert "audio" in message and "UklGRg" not in message
