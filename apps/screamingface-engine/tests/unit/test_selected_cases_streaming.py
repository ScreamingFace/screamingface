"""The aggregate's roll-call reader streams ``cases.json`` instead of parsing all of it (OME-1789).

FEATURE: capacity for concurrent users (OME-1314). A picture board's ``cases.json`` is hundreds of
MB of base64; a 2-Case run used to re-read and decode the whole file at aggregation just to find
its two rows. These tests pin that the streaming reader returns exactly what the full parse did,
keeps the same error wording, and never needs the whole file in memory.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks.shared_grading import case_rows
from screamingface_engine.benchmarks.shared_grading.case_grades import read_selected_cases
from screamingface_engine.benchmarks.shared_grading.case_rows import iter_array_rows


class BoardError(ValueError):
    """Stands in for a benchmark's own ``AggregateError``."""


def _full_parse(text: str, case_ids: tuple[int, ...]) -> list[tuple[object, str]]:
    """The pre-OME-1789 reader's selection rule, kept here as the oracle."""

    decoded: Any = json.loads(text)
    by_id: dict[int, Mapping[str, Any]] = {
        row["id"]: row
        for row in decoded
        if isinstance(row, Mapping)
        and isinstance(row.get("id"), int)
        and not isinstance(row.get("id"), bool)
    }
    return [(case_id, by_id[case_id]["input"]) for case_id in case_ids]


def _read(tmp_path: Path, text: str, case_ids: tuple[int, ...]) -> list[tuple[object, str]]:
    (tmp_path / "cases.json").write_text(text, encoding="utf-8")
    selected = read_selected_cases(
        tmp_path, case_ids, benchmark_label="Board", error_type=BoardError
    )
    return [(case.case_id, case.input) for case in selected]


EQUIVALENT_BOARDS: list[tuple[str, str, tuple[int, ...]]] = [
    ("compact", json.dumps([{"id": i, "input": f"q{i}"} for i in range(1, 6)]), (4, 2)),
    (
        "pretty-printed with odd whitespace",
        "\n\t [\r\n"
        + ",\n  ".join(json.dumps({"id": i, "input": f"q{i}"}) for i in (1, 2))
        + "\n] \n",
        (2, 1),
    ),
    (
        # INVARIANT: the last row carrying an id wins, as the dict comprehension did.
        "duplicate ids, last wins",
        json.dumps([{"id": 1, "input": "first"}, {"id": 1, "input": "second"}]),
        (1,),
    ),
    (
        "non-object rows and non-int ids are skipped",
        json.dumps(
            [
                3,
                "x",
                None,
                [1],
                {"id": True, "input": "bool"},
                {"id": "1", "input": "str"},
                {"id": 1.0, "input": "float"},
                {"input": "no id"},
                {"id": 1, "input": "real"},
            ]
        ),
        (1,),
    ),
    (
        "numbers and literals at chunk edges",
        json.dumps([123456789, True, False, None, -1.5e3, {"id": 7, "input": "seven"}, 98765]),
        (7,),
    ),
    (
        "non-ascii and escapes",
        json.dumps([{"id": 1, "input": 'Ünïcødé "quoted" \\ ] , ['}], ensure_ascii=False),
        (1,),
    ),
]


@pytest.mark.parametrize("chunk", [1, 2, 3, 7, 64, 1 << 20])
@pytest.mark.parametrize(("label", "text", "case_ids"), EQUIVALENT_BOARDS)
def test_streamed_selection_matches_the_full_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chunk: int,
    label: str,
    text: str,
    case_ids: tuple[int, ...],
) -> None:
    monkeypatch.setattr(case_rows, "CHUNK_CHARS", chunk)
    assert _read(tmp_path, text, case_ids) == _full_parse(text, case_ids), label


def test_a_row_larger_than_the_chunk_is_read_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(case_rows, "CHUNK_CHARS", 16)
    big = "x" * 10_000
    text = json.dumps([{"id": 1, "input": big}, {"id": 2, "input": "small"}])
    assert _read(tmp_path, text, (1, 2)) == [(1, big), (2, "small")]


def test_an_empty_array_selects_nothing_and_still_names_the_missing_case(tmp_path: Path) -> None:
    assert _read(tmp_path, " [ ] ", ()) == []
    with pytest.raises(BoardError, match="Board Case 1 has no public input"):
        _read(tmp_path, "[]", (1,))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "[",
        '[{"id": 1, "input": "a"}',
        '[{"id": 1, "input": "a"},',
        '[{"id": 1, "input": "a"},]',
        '[{"id": 1, "input": "a"} {"id": 2}]',
        '[{"id": 1, "input": "a"}] trailing',
        '[{"id": 1, "input": "a"}][]',
        "[1,,2]",
        "[,]",
        "{bad",
        "﻿[]",
    ],
)
@pytest.mark.parametrize("chunk", [1, 4, 1 << 20])
def test_malformed_json_is_unavailable_like_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, chunk: int
) -> None:
    with pytest.raises(ValueError):
        json.loads(text)  # the oracle agrees the document is not JSON
    monkeypatch.setattr(case_rows, "CHUNK_CHARS", chunk)
    with pytest.raises(BoardError, match="^Board cases are unavailable: "):
        _read(tmp_path, text, (1,))


@pytest.mark.parametrize("text", ['{"id": 1, "input": "a"}', "1", '"rows"', "null", "  {} "])
def test_a_json_document_that_is_not_an_array_keeps_its_wording(tmp_path: Path, text: str) -> None:
    with pytest.raises(BoardError, match="^Board cases must be a JSON array$"):
        _read(tmp_path, text, (1,))


def test_undecodable_bytes_are_unavailable(tmp_path: Path) -> None:
    (tmp_path / "cases.json").write_bytes(b'[{"id": 1, "input": "\xff\xfe"}]')
    with pytest.raises(BoardError, match="^Board cases are unavailable: "):
        read_selected_cases(tmp_path, (1,), benchmark_label="Board", error_type=BoardError)


class _CountingReader(io.StringIO):
    """A text stream that records how many characters have been handed out."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.served = 0

    def read(self, size: int | None = -1, /) -> str:
        piece = super().read(size)
        self.served += len(piece)
        return piece


def test_rows_are_yielded_before_the_rest_of_the_file_is_read() -> None:
    """INVARIANT (OME-1789): memory scales with one row, not the board.

    The first row must come out after reading roughly one row's worth of text — never after
    the whole file. A regression to ``read_text`` + ``json.loads`` fails this at once.
    """

    row = json.dumps({"id": 0, "input": "y" * 1_000})
    text = "[" + ",".join(row for _ in range(200)) + "]"
    stream = _CountingReader(text)
    rows = iter_array_rows(stream, chunk_chars=256)

    first = next(rows)
    assert first == json.loads(row)
    assert stream.served < 3 * len(row)
    assert stream.served < len(text) // 50

    assert sum(1 for _ in rows) == 199
    assert stream.served == len(text)


def test_the_reader_reports_a_non_array_document_distinctly() -> None:
    with pytest.raises(case_rows.NotAnArrayError):
        list(iter_array_rows(io.StringIO('{"id": 1}')))


NUMBERS = "[0, -0, 12345, -1500.0, 1.5e3, -2.25E-7, 6e+2, 1e400, NaN, -Infinity, true, null]"


@pytest.mark.parametrize("chunk", range(1, len(NUMBERS) + 2))
def test_a_number_cut_by_any_chunk_edge_decodes_whole(chunk: int) -> None:
    """A number split at the buffer edge ("-15" | "00.0") must not decode as its prefix."""

    got = list(iter_array_rows(io.StringIO(NUMBERS), chunk_chars=chunk))
    assert repr(got) == repr(json.loads(NUMBERS))


def _random_value(rng: Any, depth: int = 0) -> object:
    makers: list[Callable[[], object]] = [
        lambda: rng.randrange(-(10**6), 10**6),
        lambda: rng.uniform(-1e6, 1e6) * 10 ** rng.randrange(-30, 30),
        lambda: "".join(rng.choice('ab"\\ ,[]{}é\n\u2028') for _ in range(rng.randrange(8))),
        lambda: rng.choice([True, False, None]),
        lambda: {"id": rng.randrange(5), "input": "x"},
        lambda: [_random_value(rng, depth + 1) for _ in range(rng.randrange(4))],
        lambda: {str(k): _random_value(rng, depth + 1) for k in range(rng.randrange(4))},
    ]
    return makers[rng.randrange(7 if depth < 3 else 5)]()


@pytest.mark.parametrize("seed", range(40))
def test_random_arrays_stream_exactly_as_json_loads_parses_them(seed: int) -> None:
    import random

    rng = random.Random(seed)
    rows = [_random_value(rng) for _ in range(rng.randrange(12))]
    separators = rng.choice([(",", ":"), (", ", ": "), (" ,\n", " :\t")])
    text = json.dumps(rows, separators=separators, ensure_ascii=rng.random() < 0.5)
    for chunk in (1, 2, 5, 13, 1 << 20):
        streamed = list(iter_array_rows(io.StringIO(text), chunk_chars=chunk))
        assert repr(streamed) == repr(json.loads(text)), (seed, chunk)
