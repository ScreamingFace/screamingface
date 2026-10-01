from __future__ import annotations

import json
import random
from collections.abc import Callable, Iterable, Iterator
from typing import cast

import pytest
from _report_fixtures import (
    benchmark,
    candidate,
    large_candidates,
    oracle,
    peak_bytes,
    report,
    track_live_candidate_dicts,
)

import screamingface as sf
from screamingface._report_writer import write_report_json

_TEXT_PIECES = (
    "plain",
    "emoji \U0001f600 \U0001f9d1‍\U0001f4bb",
    "שלום السلام",
    'quote " and backslash \\',
    "control \x00\x01\x1f \t \r \n",
    "line separator ",
    "éè 中文",
)


def emit(
    value: sf.Report,
    *,
    candidates: Iterable[sf.CandidateResult] | None = None,
    candidate_names: tuple[str, ...] | None = None,
    sink: Callable[[str], object] | None = None,
) -> list[str]:
    parts: list[str] = []
    write_report_json(
        sink or parts.append,
        benchmark=value.benchmark,
        case_count=value.case_count,
        started_at=value.started_at,
        completed_at=value.completed_at,
        candidate_names=(
            tuple(c.name for c in value.candidates) if candidate_names is None else candidate_names
        ),
        candidates=value.candidates if candidates is None else candidates,
    )
    return parts


def generated_report(seed: int, count: int) -> sf.Report:
    rng = random.Random(seed)
    candidates = []
    for index in range(count):
        text = " ".join(rng.choice(_TEXT_PIECES) for _ in range(rng.randint(1, 4)))
        usage = sf.Usage(
            input_tokens=rng.randint(0, 9_000),
            output_tokens=rng.randint(0, 9_000),
            cost_usd=rng.choice((None, "0.5", "12.345678")),
        )
        candidates.append(
            candidate(
                f"cand-{seed}-{index}", text=text, usage=usage, start_minute=rng.randint(0, 90)
            )
        )
    return report(*candidates)


@pytest.mark.parametrize("count", [1, 2, 11])
@pytest.mark.parametrize("seed", range(8))
def test_streaming_writer_bytes_equal_to_json(seed: int, count: int) -> None:
    value = generated_report(seed, count)

    parts = emit(value)

    assert "".join(parts) == oracle(value)
    assert "".join(parts).encode("utf-8") == oracle(value).encode("utf-8")


def test_escape_heavy_and_non_ascii_text_stays_identical() -> None:
    value = report(
        candidate("opus", text="".join(_TEXT_PIECES)),
        candidate("gpt", text='\U0001f600 "\\ \x00\x1f שלום'),
    )

    assert "".join(emit(value)) == oracle(value)
    assert "\U0001f600" in "".join(emit(value))


def test_lone_surrogates_stay_text_like_to_json() -> None:
    value = report(candidate("opus", text="lone \ud800 surrogate"))

    assert "".join(emit(value)) == oracle(value)


def test_usage_is_combined_like_report_usage_when_a_field_is_missing() -> None:
    value = report(
        candidate("opus", usage=sf.Usage(input_tokens=10, output_tokens=2, cost_usd="0.10")),
        candidate("gpt", usage=sf.Usage(input_tokens=5, output_tokens=1, cost_usd=None)),
    )

    document = json.loads("".join(emit(value)))

    assert document["usage"] == value.usage.to_dict()
    assert document["usage"]["cost_usd"] is None
    assert document["usage"]["input_tokens"] == 15


def test_writer_builds_no_whole_document_string() -> None:
    candidates = large_candidates(6)
    value = report(*candidates)
    expected_chars = len(oracle(value))
    written = 0

    def sink(fragment: str) -> None:
        nonlocal written
        written += len(fragment)

    def one_candidate() -> str:
        return json.dumps(candidates[0].to_dict(), ensure_ascii=False, separators=(",", ":"))

    reference_peak = peak_bytes(one_candidate)
    writer_peak = peak_bytes(lambda: emit(value, sink=sink))

    assert written == expected_chars
    assert writer_peak < 2.0 * reference_peak


def test_writer_keeps_at_most_one_candidate_dict_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    value = generated_report(3, 11)
    live_before_each_call = track_live_candidate_dicts(monkeypatch)

    emit(value, sink=lambda _fragment: None)

    assert len(live_before_each_call) == 11
    assert live_before_each_call == [0] * 11


def test_duplicate_names_raise_before_any_fragment_is_written() -> None:
    with pytest.raises(ValueError) as expected:
        report(candidate("a"), candidate("a"))
    value = report(candidate("a"), candidate("b"))
    parts: list[str] = []

    with pytest.raises(ValueError) as raised:
        emit(value, candidate_names=("a", "a"), sink=parts.append)

    assert str(raised.value) == str(expected.value)
    assert parts == []


def test_empty_candidate_names_raise_before_any_fragment_is_written() -> None:
    parts: list[str] = []

    with pytest.raises(ValueError, match="a Report requires at least one Candidate"):
        emit(report(candidate("a")), candidate_names=(), candidates=(), sink=parts.append)

    assert parts == []


def test_a_non_benchmark_value_is_refused_like_report_init() -> None:
    with pytest.raises(TypeError, match="Report benchmark must be an sf.BenchmarkInfo"):
        write_report_json(
            lambda _fragment: None,
            benchmark=cast(sf.BenchmarkInfo, "draco"),
            case_count=2,
            started_at=candidate("a").started_at,
            completed_at=candidate("a").completed_at,
            candidate_names=("a",),
            candidates=(candidate("a"),),
        )


def test_a_wrong_benchmark_candidate_is_refused_before_its_fragment() -> None:
    other = sf.BenchmarkInfo(id="other", revision="fixture-revision", case_count=100)
    bad = candidate("bad", benchmark_info=other)
    with pytest.raises(ValueError) as expected:
        sf.Report(benchmark=benchmark(), case_count=2, candidates=(candidate("ok"), bad))
    value = report(candidate("ok"), candidate("bad"))
    parts: list[str] = []

    with pytest.raises(ValueError) as raised:
        emit(value, candidates=(candidate("ok"), bad), sink=parts.append)

    assert str(raised.value) == str(expected.value)
    assert "run_ok" in "".join(parts)
    assert "bad" not in "".join(parts)


def test_a_wrong_case_count_candidate_is_refused_before_its_fragment() -> None:
    bad = candidate("bad", case_count=3)
    with pytest.raises(ValueError) as expected:
        report(candidate("ok"), bad)
    value = report(candidate("ok"), candidate("bad"))
    parts: list[str] = []

    with pytest.raises(ValueError) as raised:
        emit(value, candidates=(candidate("ok"), bad), sink=parts.append)

    assert str(raised.value) == str(expected.value)
    assert "bad" not in "".join(parts)


@pytest.mark.parametrize(
    "yielded",
    [("a", "x"), ("a",), ("a", "b", "c")],
    ids=["wrong-name", "too-few", "too-many"],
)
def test_yielded_candidates_must_match_candidate_names_in_order(yielded: tuple[str, ...]) -> None:
    value = report(candidate("a"), candidate("b"))

    with pytest.raises(ValueError, match="Report candidates must match candidate_names in order"):
        emit(value, candidates=tuple(candidate(name) for name in yielded))


def test_an_iterator_error_propagates_without_closing_the_document() -> None:
    value = generated_report(1, 11)
    failure = RuntimeError("source failed")
    parts: list[str] = []

    def failing() -> Iterator[sf.CandidateResult]:
        yield value.candidates[0]
        yield value.candidates[1]
        raise failure

    with pytest.raises(RuntimeError) as raised:
        emit(value, candidates=failing(), sink=parts.append)

    assert raised.value is failure
    written = "".join(parts)
    assert written.startswith('{"schema":"screamingface.report.v1"')
    assert not written.endswith("]")
    assert '],"usage"' not in written
    assert written.count('"run_id"') == 2


def test_a_non_candidate_item_is_refused_like_report_init() -> None:
    with pytest.raises(TypeError) as expected:
        sf.Report(
            benchmark=benchmark(),
            case_count=2,
            candidates=cast(tuple[sf.CandidateResult, ...], ("not a candidate",)),
        )
    parts: list[str] = []

    with pytest.raises(TypeError) as raised:
        emit(
            report(candidate("a")),
            candidates=cast(tuple[sf.CandidateResult, ...], ("not a candidate",)),
            sink=parts.append,
        )

    assert (
        str(raised.value)
        == str(expected.value)
        == "Report candidates must be sf.CandidateResult values"
    )
