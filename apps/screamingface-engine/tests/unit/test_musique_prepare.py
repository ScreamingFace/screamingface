"""Case Preparation for MuSiQue-Ans: pinned bytes in, public Cases and private Grading Material out.

    <out>/cases.json          [{id, input}]                     — public, the Candidate-facing text
    <out>/answers/<id>.json   {answer, answer_aliases,          — private Grading Material
                               supporting_idx, musique_id, hop_type}

Every test runs on two real dev Cases (`tests/fixtures/musique/dev_two_rows.jsonl`, CC BY 4.0,
copied byte for byte) and makes NO network call: the one download is replaced in each test that
reaches it.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from screamingface_engine.benchmarks.deployment import BenchmarkAssetPreparationError
from screamingface_engine.benchmarks.musique import prepare as module
from screamingface_engine.benchmarks.musique import revision_inputs
from screamingface_engine.benchmarks.musique.prepare import (
    PrepareError,
    case_records,
    emit,
    parse_rows,
    validate_row,
    verify_sha256,
)
from screamingface_engine.benchmarks.musique.prompts import Paragraph, render_case_input

_FIXTURE: Path = Path(__file__).parents[1] / "fixtures/musique/dev_two_rows.jsonl"
_FIXTURE_CASES = 2


def _fixture_bytes() -> bytes:
    """The two real dev Cases, exactly as the dev file holds them."""

    return _FIXTURE.read_bytes()


def _rows() -> list[dict[str, Any]]:
    """The two fixture Cases parsed, as Case Preparation sees them."""

    return parse_rows(_fixture_bytes(), expected_count=_FIXTURE_CASES)


def _first_row() -> dict[str, Any]:
    """A private copy of `2hop__460946_294723` that a test may break."""

    return copy.deepcopy(_rows()[0])


def _use_fixture_as_the_pinned_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the fixture stand in for the 2,417-Case dev file: the download returns its bytes and
    the pins expect its hash and its count. Simulates a successful download only; it proves
    nothing about Hugging Face itself."""

    data: bytes = _fixture_bytes()
    monkeypatch.setattr(module, "download_dev_file", lambda: data)
    monkeypatch.setattr(module, "DATASET_SHA256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(module, "EXPECTED_CASES", _FIXTURE_CASES)


# --- the public Case and the private Grading Material ---------------------------------------


def test_case_ids_are_one_based_positions_in_the_dev_file() -> None:
    """WHY positions (plan, "Ids"): grading joins Cases by position, as ContractEval does; the
    dataset's own id rides in the private record instead."""

    cases, answers = case_records(_rows())

    assert [case["id"] for case in cases] == [1, 2]
    assert sorted(answers) == [1, 2]


def test_the_public_case_is_the_rendered_prompt_and_nothing_else() -> None:
    row: dict[str, Any] = _rows()[0]
    paragraphs: list[Paragraph] = [
        Paragraph(idx=p["idx"], title=p["title"], text=p["paragraph_text"])
        for p in row["paragraphs"]
    ]

    cases, _ = case_records(_rows())

    assert cases[0] == {"id": 1, "input": render_case_input(row["question"], paragraphs)}


def test_the_public_case_never_reveals_the_gold_or_the_hop_count() -> None:
    """INVARIANT: the Candidate gets the question and the paragraphs, never WHICH paragraphs
    support the answer. The dataset's id is private too: its `2hop`/`3hop1` prefix tells a model
    how many paragraphs to cite, which is a hint the paper's models never had."""

    cases, answers = case_records(_rows())

    for case in cases:
        assert set(case) == {"id", "input"}
        record: dict[str, Any] = dict(answers[case["id"]])
        assert record["musique_id"] not in case["input"]
        for leaked in ("is_supporting", "supporting_idx", "answer_aliases", "decomposition"):
            assert leaked not in case["input"]


def test_the_grading_material_holds_the_answer_aliases_and_supporting_numbers() -> None:
    """The private record is everything the official scorer needs, plus the two keys the Report
    groups Cases by. Supporting numbers are sorted so the bytes are stable."""

    _, answers = case_records(_rows())

    assert answers[1] == {
        "answer": "Miquette Giraudy",
        "answer_aliases": [],
        "supporting_idx": [5, 10],
        "musique_id": "2hop__460946_294723",
        "hop_type": "2hop",
    }
    assert answers[2] == {
        "answer": "Denver",
        "answer_aliases": ["Denver, Colorado"],
        "supporting_idx": [0, 7, 9],
        "musique_id": "3hop1__454441_55349_651302",
        "hop_type": "3hop1",
    }


def test_emit_writes_the_public_file_and_one_private_record_per_case(tmp_path: Path) -> None:
    cases, answers = case_records(_rows())

    summary: dict[str, Any] = emit(tmp_path, cases, answers)

    public: list[dict[str, Any]] = json.loads((tmp_path / "cases.json").read_text("utf-8"))
    assert public == cases
    for case_id, record in answers.items():
        written: dict[str, Any] = json.loads(
            (tmp_path / "answers" / f"{case_id}.json").read_text("utf-8")
        )
        assert written == record
    assert summary["cases"] == _FIXTURE_CASES
    assert summary["dataset_revision"] == revision_inputs.DATASET_REVISION


def test_the_audit_summary_counts_cases_per_hop_type(tmp_path: Path) -> None:
    """The per-hop split is what a reader checks against the paper's Table 2 (1,252 / 760 / 405)
    on the real build, so the build reports it."""

    summary: dict[str, Any] = emit(tmp_path, *case_records(_rows()))

    assert summary["hop_types"] == {"2hop": 1, "3hop1": 1}


# --- refusals: a Case is never served from bytes nobody checked -----------------------------


def test_bytes_that_are_not_the_reviewed_file_are_refused() -> None:
    """F1: a re-pushed mirror would serve different Cases under the same Benchmark Revision. The
    refusal names both hashes so the operator can tell drift from a truncated download."""

    with pytest.raises(PrepareError) as raised:
        verify_sha256(_fixture_bytes())

    assert revision_inputs.DATASET_SHA256 in str(raised.value)
    assert hashlib.sha256(_fixture_bytes()).hexdigest() in str(raised.value)


def test_the_pinned_hash_accepts_the_pinned_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "DATASET_SHA256", hashlib.sha256(_fixture_bytes()).hexdigest())

    verify_sha256(_fixture_bytes())


def test_a_file_with_the_wrong_number_of_cases_is_refused() -> None:
    """F3: `case_count` is declared from EXPECTED_CASES; a file of another size would make every
    Coverage percentage divide by a number nobody verified."""

    with pytest.raises(PrepareError, match="2 Cases"):
        parse_rows(_fixture_bytes())


def test_a_line_that_is_not_json_is_refused_by_line_number() -> None:
    data: bytes = _fixture_bytes() + b"{not json\n"

    with pytest.raises(PrepareError, match="line 3"):
        parse_rows(data, expected_count=3)


def test_the_real_dev_file_size_is_the_declared_count() -> None:
    assert revision_inputs.EXPECTED_CASES == 2417


def test_a_paragraph_number_that_is_not_its_position_is_refused() -> None:
    """F3 and spec D4: the prompt shows `idx` and support F1 compares cited numbers with gold
    `idx`. On the pinned file they equal the position; if that ever stops holding, the build
    must stop rather than serve numbers that mean something different."""

    row: dict[str, Any] = _first_row()
    row["paragraphs"][3]["idx"] = 4

    with pytest.raises(PrepareError, match="2hop__460946_294723.*idx"):
        validate_row(row)


@pytest.mark.parametrize("field", ["id", "paragraphs", "question", "answer", "answer_aliases"])
def test_a_missing_field_is_refused(field: str) -> None:
    row: dict[str, Any] = _first_row()
    del row[field]

    with pytest.raises(PrepareError, match=field):
        validate_row(row)


def test_an_unanswerable_case_is_refused() -> None:
    """MuSiQue-Ans is the all-answerable setting; an unanswerable Case means the wrong file."""

    row: dict[str, Any] = _first_row()
    row["answerable"] = False

    with pytest.raises(PrepareError, match="answerable"):
        validate_row(row)


def test_a_supporting_count_that_disagrees_with_the_hop_count_is_refused() -> None:
    """A 2-hop question rests on exactly 2 supporting paragraphs in every pinned Case."""

    row: dict[str, Any] = _first_row()
    row["paragraphs"][0]["is_supporting"] = True

    with pytest.raises(PrepareError, match="supporting"):
        validate_row(row)


def test_an_unknown_hop_type_is_refused() -> None:
    row: dict[str, Any] = _first_row()
    row["id"] = "5hop1__1_2_3_4_5"

    with pytest.raises(PrepareError, match="hop type"):
        validate_row(row)


def test_an_empty_paragraph_text_is_refused() -> None:
    row: dict[str, Any] = _first_row()
    row["paragraphs"][2]["paragraph_text"] = "  "

    with pytest.raises(PrepareError, match="paragraph_text"):
        validate_row(row)


def test_every_refusal_is_an_operator_readable_preparation_error() -> None:
    """The orchestrator CLI reports `BenchmarkAssetPreparationError` without a traceback."""

    assert issubclass(PrepareError, BenchmarkAssetPreparationError)


# --- the one network step, replaced ---------------------------------------------------------


def test_the_download_asks_for_the_pinned_file_at_the_pinned_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fake `huggingface_hub` records the request and serves the fixture, so this proves the
    pins reach the call; it does not prove Hugging Face serves those bytes (that is ②'s job)."""

    requested: dict[str, object] = {}

    def fake_download(**kwargs: object) -> str:
        """Stand-in for `hf_hub_download`: record the request, hand back the fixture path."""

        requested.update(kwargs)
        return str(_FIXTURE)

    fake_hub = SimpleNamespace(hf_hub_download=fake_download)
    monkeypatch.setattr(module.importlib, "import_module", lambda _name: fake_hub)

    data: bytes = module.download_dev_file()

    assert data == _fixture_bytes()
    assert requested == {
        "repo_id": "dgslibisey/MuSiQue",
        "filename": "musique_ans_v1.0_dev.jsonl",
        "revision": "c8f4f8c9465fb69d31a8eae894c3fd509c4ca321",
        "repo_type": "dataset",
    }


def test_an_unreachable_hub_fails_the_build_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """F2: the image build stops with a readable reason; the previous image keeps serving."""

    def unreachable(**_kwargs: object) -> str:
        """Stand-in for a download that cannot reach the Hub (no cached copy either)."""

        raise OSError("connection refused")

    fake_hub = SimpleNamespace(hf_hub_download=unreachable)
    monkeypatch.setattr(module.importlib, "import_module", lambda _name: fake_hub)

    with pytest.raises(PrepareError, match="dgslibisey/MuSiQue"):
        module.download_dev_file()


def test_a_build_without_huggingface_hub_names_the_missing_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> object:
        """Stand-in for a build environment without the `benchmarks` extra installed."""

        raise ModuleNotFoundError(name)

    monkeypatch.setattr(module.importlib, "import_module", missing)

    with pytest.raises(PrepareError, match="huggingface_hub"):
        module.download_dev_file()


# --- the whole step, end to end --------------------------------------------------------------


def test_prepare_downloads_verifies_and_writes_the_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_fixture_as_the_pinned_file(monkeypatch)

    summary: dict[str, Any] = module.prepare(tmp_path)

    assert summary["cases"] == _FIXTURE_CASES
    assert (tmp_path / "cases.json").exists()
    assert sorted(p.name for p in (tmp_path / "answers").iterdir()) == ["1.json", "2.json"]


def test_prepare_writes_nothing_when_the_bytes_are_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F1: refused bytes leave no half-written bundle behind for a later step to serve."""

    _use_fixture_as_the_pinned_file(monkeypatch)
    monkeypatch.setattr(module, "DATASET_SHA256", "0" * 64)

    with pytest.raises(PrepareError):
        module.prepare(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_the_entry_point_exits_0_and_prints_the_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The SDK spawns `python -m screamingface_engine.benchmarks.musique.prepare --out <dir>`."""

    _use_fixture_as_the_pinned_file(monkeypatch)

    assert module.main(["--out", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["cases"] == _FIXTURE_CASES


def test_the_entry_point_reports_a_refusal_as_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_fixture_as_the_pinned_file(monkeypatch)
    monkeypatch.setattr(module, "DATASET_SHA256", "0" * 64)

    assert module.main(["--out", str(tmp_path)]) == 1


def test_the_prepare_module_exposes_the_dataset_revision_the_sdk_fingerprints() -> None:
    """The SDK's prepare cache keys on `prepare.DATASET_REVISION`; without it the SDK refuses
    to prepare this Benchmark at all."""

    assert module.DATASET_REVISION == "c8f4f8c9465fb69d31a8eae894c3fd509c4ca321"
