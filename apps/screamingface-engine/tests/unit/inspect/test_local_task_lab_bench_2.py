# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai, absent in the extra-less typecheck install.
"""LABBench2 FigQA2 image and TableQA2 image as a LOCAL inspect Task (OME-1733).

What these tests pin, and why:

- the Candidate's message: the authors' file-mode question text ("Attached files" lines), then
  the picture, in one user message, sealed into the Case as the picture envelope when the
  figure sits in the replay cache;
- the figure fetch: lands under ``INSPECT_EVALS_CACHE_DIR``, is checked against the bucket's
  md5, keeps a verified copy, refuses a listed name that would leave the question's folder,
  and never leaks a raw urllib or JSON error;
- the rows the build refuses: a missing question, ideal answer or files prefix, a row not
  served in file mode, a non-picture file, a dataset of the wrong size;
- the judge: the vendored prompt is the authors' text byte for byte; the verdict reader takes
  the last ``result`` line; only correct scores 1; no answer scores 0 without a judge call; a
  reply with no verdict is redrawn, and three fail the Case by name.

No network: the bucket is a fake opener, the judge is inspect's mockllm with scripted replies,
the dataset loader is replaced. Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import http.client
import io
import json
import urllib.error
import urllib.parse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.model import (  # noqa: E402
    ChatMessageUser,
    ContentImage,
    ContentText,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.scorer import Score, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine_inspect.judge_redraw import JudgeReplyUnparseable  # noqa: E402
from screamingface_engine_inspect.local_tasks.lab_bench_2 import (  # noqa: E402
    figures,
    lab_bench_2,
)
from screamingface_engine_inspect.local_tasks.lab_bench_2.figures import (  # noqa: E402
    FigureFetchError,
    fetch_question_files,
)
from screamingface_engine_inspect.local_tasks.lab_bench_2.lab_bench_2 import (  # noqa: E402
    DATASET,
    DATASET_REVISION,
    LabBench2RowError,
    lab_bench_2_exact_match,
    load_rows,
    parse_verdict,
    record_to_sample,
)
from screamingface_engine_inspect.local_tasks.lab_bench_2.vendor.labbench2 import (  # noqa: E402
    STRUCTURED_EVALUATION_PROMPT_EXACT_MATCH,
    file_mode_question,
)
from screamingface_engine_inspect.picture_input import picture_case_text  # noqa: E402

#: The sha256 of ``STRUCTURED_EVALUATION_PROMPT_EXACT_MATCH`` in the authors' ``evals/prompts.py``
#: at 0cabab27, computed from the raw file on 2026-11-04. A drift here means the vendored judge
#: prompt is no longer the authors'.
_AUTHORS_PROMPT_SHA256: str = "7c39aa1deed29fab916e69cd716739e2435d66dabf47d3b49b83f5b060c33764"

#: A real FigQA2 image row's prefix and question at the pinned revision (row 1).
_PREFIX: str = "/figs/imgs/b60fdf79-25b2-4bf2-a5bb-cb553d83770f/"
_QUESTION: str = (
    "For L1 Layer M1 neurons, which contrast resulted in the highest calcium peak in the dark "
    "condition?"
)
#: Stand-in picture bytes: a PNG signature and a few bytes, enough for the type sniff.
_PNG: bytes = b"\x89PNG\r\n\x1a\n" + b"stand-in figure"


def _md5(data: bytes) -> str:
    """The base64 md5 the bucket's listing gives for ``data``."""

    return base64.b64encode(hashlib.md5(data, usedforsecurity=False).digest()).decode("ascii")


class _FakeBucket:
    """A stand-in for the public bucket: answers listing and download URLs from memory.

    ``objects`` maps an object name to its bytes; ``listed_md5`` overrides one object's listed
    md5 (to fake a corrupted transfer); ``fail`` maps a URL substring to the exception raised
    for it, every time. ``calls`` records every URL opened, so a test can see what was fetched.
    """

    def __init__(
        self,
        objects: dict[str, bytes],
        *,
        listed_md5: dict[str, str] | None = None,
        fail: dict[str, Exception] | None = None,
    ) -> None:
        self.objects: dict[str, bytes] = objects
        self.listed_md5: dict[str, str] = listed_md5 or {}
        self.fail: dict[str, Exception] = fail or {}
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float) -> Any:
        """Open ``url``: the listing for an ``/o?prefix=`` URL, else the object's bytes."""

        self.calls.append(url)
        for marker, exc in self.fail.items():
            if marker in url:
                raise exc
        if "/storage/v1/b/" in url:
            prefix: str = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["prefix"][0]
            items: list[dict[str, str]] = [
                {"name": name, "md5Hash": self.listed_md5.get(name, _md5(data))}
                for name, data in sorted(self.objects.items())
                if name.startswith(prefix)
            ]
            return _response(json.dumps({"items": items}).encode())
        name: str = urllib.parse.unquote(url.split(f"/{figures.BUCKET}/", 1)[1])
        return _response(self.objects[name])


@contextmanager
def _response(body: bytes) -> Iterator[io.BytesIO]:
    """A urlopen-like context manager over ``body``."""

    yield io.BytesIO(body)


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retries in these tests must not wait out the real backoff."""

    monkeypatch.setattr(figures.time, "sleep", lambda _seconds: None)


def _row(**overrides: Any) -> dict[str, Any]:
    """A FigQA2 image row shaped like the pinned dataset's, with ``overrides`` applied."""

    row: dict[str, Any] = {
        "id": "b60fdf79-25b2-4bf2-a5bb-cb553d83770f-img",
        "tag": "figqa2-img",
        "question": _QUESTION,
        "ideal": "+/- 0.5",
        "files": _PREFIX,
        "sources": "['http://doi.org/10.1016/j.cell.2016.05.031']",
        "prompt_suffix": "",
        "mode": "{'file': True, 'retrieve': False, 'inject': False}",
    }
    row.update(overrides)
    return row


def _fetch_into(
    directory: Path, names: tuple[str, ...] = ("figure.png",)
) -> Callable[[str], list[Path]]:
    """A stand-in fetch that writes ``names`` under ``directory`` and returns them."""

    def fetch(prefix: str) -> list[Path]:
        directory.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for name in names:
            path = directory / name
            path.write_bytes(_PNG)
            paths.append(path)
        return paths

    return fetch


# ── the Candidate's message ─────────────────────────────────────────────────────────────────
def test_a_row_becomes_the_authors_file_mode_question_then_its_picture(tmp_path: Path) -> None:
    # INVARIANT: the Candidate sees what the authors' loader sends in file mode: the question,
    # the attached file's base name, the citing instruction, then the picture.
    sample = record_to_sample(_row(), case_id=1, fetch=_fetch_into(tmp_path))

    assert sample.id == 1
    assert sample.target == "+/- 0.5"
    assert sample.metadata == {
        "id": "b60fdf79-25b2-4bf2-a5bb-cb553d83770f-img",
        "tag": "figqa2-img",
        "sources": "['http://doi.org/10.1016/j.cell.2016.05.031']",
    }
    assert isinstance(sample.input, list) and len(sample.input) == 1
    message = sample.input[0]
    assert isinstance(message, ChatMessageUser) and isinstance(message.content, list)
    text, picture = message.content
    assert isinstance(text, ContentText) and isinstance(picture, ContentImage)
    assert text.text == (
        f"{_QUESTION}\n\nAttached files:\n- figure.png\n\n"
        "Use only the exact base filenames above. Copy them exactly, including case and "
        "extension. Do not rename them or use full paths."
    )
    assert picture.image == str(tmp_path / "figure.png")


def test_a_prompt_suffix_follows_after_a_blank_line() -> None:
    # The authors append a row's prompt_suffix after a blank line; every pinned row has none,
    # so this pins the rule for a future row rather than a present one.
    assert file_mode_question("Q?", ["table.png"], "Answer in mM.").endswith(
        "Do not rename them or use full paths.\n\nAnswer in mM."
    )


def test_a_figure_in_the_replay_cache_seals_into_the_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT: the fetch writes where the importer accepts a picture file, the replay's
    # INSPECT_EVALS_CACHE_DIR; the Case then carries the picture inline and needs no file.
    evals_cache = tmp_path / "cache" / "inspect_evals"
    monkeypatch.setenv("INSPECT_EVALS_CACHE_DIR", str(evals_cache))
    bucket = _FakeBucket({_PREFIX.strip("/") + "/figure.png": _PNG})

    sample = record_to_sample(
        _row(), case_id=1, fetch=lambda prefix: fetch_question_files(prefix, opener=bucket)
    )

    assert isinstance(sample.input, list)
    sealed = picture_case_text(sample.input, case_id=1)
    assert sealed is not None
    envelope: dict[str, Any] = json.loads(sealed)
    parts: list[dict[str, Any]] = envelope["messages"][0]["content"]
    assert [part["type"] for part in parts] == ["text", "image_url"]
    assert parts[0]["text"].startswith(_QUESTION + "\n\nAttached files:\n- figure.png")
    assert parts[1]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(_PNG).decode("ascii")
    )


# ── the figure fetch ────────────────────────────────────────────────────────────────────────
def test_the_fetch_writes_under_the_inspect_evals_cache_in_the_authors_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSPECT_EVALS_CACHE_DIR", str(tmp_path / "evals"))
    bucket = _FakeBucket({_PREFIX.strip("/") + "/figure.png": _PNG})

    paths = fetch_question_files(_PREFIX, opener=bucket)

    assert paths == [
        tmp_path
        / "evals"
        / "lab_bench_2"
        / "labbench2-data-public"
        / _PREFIX.strip("/")
        / "figure.png"
    ]
    assert paths[0].read_bytes() == _PNG
    assert not list(paths[0].parent.glob("*.part"))


def test_a_verified_copy_is_not_fetched_again(tmp_path: Path) -> None:
    bucket = _FakeBucket({_PREFIX.strip("/") + "/figure.png": _PNG})
    fetch_question_files(_PREFIX, tmp_path, opener=bucket)
    downloads_before = [url for url in bucket.calls if "/storage/v1/" not in url]

    fetch_question_files(_PREFIX, tmp_path, opener=bucket)

    downloads_after = [url for url in bucket.calls if "/storage/v1/" not in url]
    assert len(downloads_before) == len(downloads_after) == 1


def test_a_download_that_does_not_match_the_listed_md5_fails_and_leaves_nothing(
    tmp_path: Path,
) -> None:
    # INVARIANT: a corrupted transfer never becomes a Case picture, and no half file remains.
    name = _PREFIX.strip("/") + "/figure.png"
    bucket = _FakeBucket({name: _PNG}, listed_md5={name: _md5(b"other bytes")})

    with pytest.raises(FigureFetchError, match="does not match the bucket's md5"):
        fetch_question_files(_PREFIX, tmp_path, opener=bucket)

    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_a_prefix_the_bucket_lists_nothing_under_fails(tmp_path: Path) -> None:
    with pytest.raises(FigureFetchError, match="lists no file"):
        fetch_question_files(_PREFIX, tmp_path, opener=_FakeBucket({}))


def test_a_listed_name_that_leaves_the_question_folder_is_refused(tmp_path: Path) -> None:
    # The listing is the bucket's word: a name with `..` must not write outside the cache.
    escaping = _PREFIX.strip("/") + "/../../../../escape.png"
    with pytest.raises(FigureFetchError, match="is not a file inside the prefix"):
        fetch_question_files(_PREFIX, tmp_path, opener=_FakeBucket({escaping: _PNG}))
    # Four `..` from the question's folder would land at <cache>/lab_bench_2/escape.png; nothing
    # may be written anywhere under the cache.
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_a_missing_object_fails_by_name_without_retrying(tmp_path: Path) -> None:
    name = _PREFIX.strip("/") + "/figure.png"
    missing = urllib.error.HTTPError("u", 404, "Not Found", None, None)  # type: ignore[arg-type]
    bucket = _FakeBucket({name: _PNG}, fail={"/labbench2-data-public/figs": missing})

    with pytest.raises(FigureFetchError, match="HTTP 404") as raised:
        fetch_question_files(_PREFIX, tmp_path, opener=bucket)

    assert raised.value.__cause__ is None
    assert len([url for url in bucket.calls if "/storage/v1/" not in url]) == 1


def test_a_connection_that_keeps_failing_is_retried_then_named(tmp_path: Path) -> None:
    bucket = _FakeBucket({}, fail={"/storage/v1/": ConnectionResetError("reset by peer")})

    with pytest.raises(FigureFetchError, match="failed after 3 attempts"):
        fetch_question_files(_PREFIX, tmp_path, opener=bucket)

    assert len(bucket.calls) == 3


class _Truncated:
    """A response whose body is cut short mid-transfer, as a dropped connection leaves it."""

    def __enter__(self) -> _Truncated:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        raise http.client.IncompleteRead(b"\x89PNG", 1_000)


def test_a_body_cut_short_is_retried_then_named(tmp_path: Path) -> None:
    # IncompleteRead is not an OSError; it must still be retried, and fail as FigureFetchError
    # naming the prefix, never escape raw.
    name = _PREFIX.strip("/") + "/figure.png"
    bucket = _FakeBucket({name: _PNG})
    downloads: list[str] = []

    def opener(url: str, timeout: float) -> Any:
        if "/storage/v1/" in url:
            return bucket(url, timeout)
        downloads.append(url)
        return _Truncated()

    with pytest.raises(
        FigureFetchError, match=f"'{name}': failed after 3 attempts: IncompleteRead"
    ):
        fetch_question_files(_PREFIX, tmp_path, opener=opener)

    assert len(downloads) == 3
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_a_rate_limited_download_is_retried(tmp_path: Path) -> None:
    # 429 is temporary, as the connector counts it beside 5xx; only other 4xx refuse at once.
    name = _PREFIX.strip("/") + "/figure.png"
    bucket = _FakeBucket({name: _PNG})
    limited: list[str] = []

    def opener(url: str, timeout: float) -> Any:
        if "/storage/v1/" not in url and not limited:
            limited.append(url)
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)  # type: ignore[arg-type]
        return bucket(url, timeout)

    paths = fetch_question_files(_PREFIX, tmp_path, opener=opener)

    assert len(limited) == 1
    assert paths[0].read_bytes() == _PNG


# ── rows the build refuses ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"question": "  "}, "question must be non-empty"),
        ({"ideal": ""}, "ideal must be non-empty"),
        ({"files": None}, "files must be non-empty"),
        (
            {"mode": "{'file': False, 'retrieve': True, 'inject': False}"},
            "the row is not served in file mode",
        ),
        ({"mode": "file please"}, "mode is not a readable dict"),
    ],
)
def test_a_damaged_row_fails_the_build_by_case(
    tmp_path: Path, overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(LabBench2RowError, match=f"case 7: {message}"):
        record_to_sample(_row(**overrides), case_id=7, fetch=_fetch_into(tmp_path))


def test_a_non_picture_file_fails_the_build(tmp_path: Path) -> None:
    # The authors would attach a PDF as a document; the picture envelope cannot carry one.
    with pytest.raises(LabBench2RowError, match="pictures only"):
        record_to_sample(
            _row(), case_id=3, fetch=_fetch_into(tmp_path, ("figure.png", "paper.pdf"))
        )


def test_the_loader_pins_the_revision_and_refuses_a_wrong_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import datasets

    asked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_load(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        asked.append((args, kwargs))
        return [_row()] * 100

    monkeypatch.setattr(datasets, "load_dataset", fake_load)

    assert len(load_rows("tableqa2-img")) == 100
    with pytest.raises(LabBench2RowError, match="holds 100 rows, but the Benchmark declares 101"):
        load_rows("figqa2-img")
    assert asked[0] == (
        (DATASET, "tableqa2-img"),
        {"split": "train", "revision": DATASET_REVISION},
    )


# ── the judge ───────────────────────────────────────────────────────────────────────────────
def test_the_vendored_judge_prompt_is_the_authors_text() -> None:
    digest = hashlib.sha256(STRUCTURED_EVALUATION_PROMPT_EXACT_MATCH.encode()).hexdigest()
    assert digest == _AUTHORS_PROMPT_SHA256


@pytest.mark.parametrize(
    ("reply", "verdict"),
    [
        ("rationale: same number.\nresult: correct", "correct"),
        ('{"rationale": "differs", "result": "incorrect"}', "incorrect"),
        ("Result: UNSURE", "unsure"),
        # The last verdict wins: the rubric words echoed first do not decide it.
        ('The result must be "correct", "incorrect", or "unsure".\nresult: incorrect', "incorrect"),
    ],
)
def test_the_last_result_line_is_the_verdict(reply: str, verdict: str) -> None:
    assert parse_verdict(reply) == (verdict, reply)


@pytest.mark.parametrize("reply", ['result = "correct"', "Looks right to me.", ""])
def test_a_reply_without_a_result_line_is_no_verdict(reply: str) -> None:
    assert parse_verdict(reply) is None


def _judge(replies: list[str]) -> Model:
    """inspect's mock model, answering ``replies`` in order."""

    return get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", reply) for reply in replies],
    )


def _grade(
    monkeypatch: pytest.MonkeyPatch, answer: str, replies: list[str], ideal: str = "1.67"
) -> tuple[Score, list[str]]:
    """Grade ``answer`` with a scripted judge; return the Score and every prompt it was sent."""

    judge = _judge(replies)
    prompts: list[str] = []
    original_generate = judge.generate

    async def recording_generate(prompt: Any, *args: Any, **kwargs: Any) -> ModelOutput:
        prompts.append(prompt)
        return await original_generate(prompt, *args, **kwargs)

    monkeypatch.setattr(judge, "generate", recording_generate)
    asked: list[str] = []

    def fake_get_model(name: str) -> Model:
        asked.append(name)
        return judge

    monkeypatch.setattr(lab_bench_2, "get_model", fake_get_model)
    state = TaskState(
        model="mockllm/model",  # type: ignore[arg-type]
        sample_id=1,
        epoch=1,
        input=[ChatMessageUser(content=[ContentText(text="What is the odds ratio?")])],
        messages=[],
        output=ModelOutput.from_content("mockllm/model", answer),
    )
    score = asyncio.run(lab_bench_2_exact_match()(state, Target(ideal)))
    assert all(name == lab_bench_2.JUDGE_MODEL for name in asked)
    return score, prompts


@pytest.mark.parametrize(
    ("reply", "value"),
    [
        ("rationale: 1.670 equals 1.67.\nresult: correct", 1.0),
        ("rationale: 1.76 is not 1.67.\nresult: incorrect", 0.0),
        # The authors' rule: unsure earns nothing.
        ("rationale: the units are unclear.\nresult: unsure", 0.0),
    ],
)
def test_only_correct_earns_the_mark(
    monkeypatch: pytest.MonkeyPatch, reply: str, value: float
) -> None:
    score, _prompts = _grade(monkeypatch, "The odds ratio is 1.670.", [reply])

    assert score.value == value
    assert score.explanation == reply
    assert score.metadata == {"verdict": reply.rsplit(": ", 1)[1], "judge_redraws": 0}


def test_the_judge_reads_the_question_the_ideal_and_the_answer_unstripped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The authors format their prompt with the answer as given, surrounding blanks included.
    _score, prompts = _grade(monkeypatch, "  1.67\n", ["result: correct"])

    assert prompts == [
        STRUCTURED_EVALUATION_PROMPT_EXACT_MATCH.format(
            question="What is the odds ratio?", correct_answer="1.67", answer="  1.67\n"
        )
    ]
    assert prompts[0].endswith(
        "## QUESTION ##\nWhat is the odds ratio?\n\n## GROUND TRUTH ANSWER ##\n1.67\n\n"
        "## SUBMITTED ANSWER ##\n  1.67\n\n\n## EVALUATION ##\n"
    )


def test_no_answer_scores_zero_without_asking_the_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    score, prompts = _grade(monkeypatch, " \n", [])

    assert (score.value, score.explanation, prompts) == (0.0, "No output provided", [])


def test_a_reply_without_a_verdict_is_redrawn(monkeypatch: pytest.MonkeyPatch) -> None:
    score, prompts = _grade(
        monkeypatch, "1.67", ["I think it matches.", "rationale: same.\nresult: correct"]
    )

    assert score.value == 1.0
    assert score.metadata == {"verdict": "correct", "judge_redraws": 1}
    assert len(prompts) == 2 and prompts[0] == prompts[1]


def test_three_replies_without_a_verdict_fail_the_case_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # INVARIANT: no verdict is never read as "incorrect" here; the Case fails by name and the
    # row's failure policy counts it 0, the authors' "evaluation failed" score.
    with pytest.raises(JudgeReplyUnparseable, match="for the answer after 2 redraws"):
        _grade(monkeypatch, "1.67", ["no idea", "still thinking", 'result = "correct"'])
