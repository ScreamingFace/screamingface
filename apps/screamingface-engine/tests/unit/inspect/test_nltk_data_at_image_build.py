# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""A local Task's nltk corpus: fetched at image build, sealed into the revision, read offline.

The grading job has no network, so a scorer that tokenizes with nltk (ifeval's checker reads
``punkt`` and ``punkt_tab``) needs the corpus inside its bundle (OME-1527, R8).

INVARIANT: a row that declares no nltk resources moves no revision and prepares exactly the
bundle it did before; a row that declares them gets them into ``<bundle>/nltk_data/`` before
``cases.json`` lands, refuses files that seal differently, and grades with nltk reading that
folder and nothing else.

THE STAND-IN, named once for every test below: gsm8k's real BenchmarkSpec row over a Case
Preparation row that declares two nltk resources, with a canned one-Case replay and an
``nltk.download`` that writes two small fixture folders. It simulates the image build's
fetch and the grading job's lookup; it does NOT prove the real nltk index serves these
bytes (the next image build does) or that ifeval's checker tokenizes with them (#15 does).
"""

from __future__ import annotations

import socket
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

import nltk  # noqa: E402

from screamingface_engine.benchmarks.deployment import UNCONFIRMED_CASES_KEY  # noqa: E402
from screamingface_engine.benchmarks.nltk_data import NLTK_DATA_DIR  # noqa: E402
from screamingface_engine_inspect import benchmarks, importer, single_shot  # noqa: E402
from screamingface_engine_inspect.import_replay import TaskReplayImport  # noqa: E402
from screamingface_engine_inspect.prepare import (  # noqa: E402
    TASK_REPLAY_CASES,
    PreparedCase,
    TaskReplayCasesSpec,
    case_digest,
)
from screamingface_engine_inspect.task_replay import TaskReplay  # noqa: E402
from url4.peer.server import Url4Node  # noqa: E402

#: The resources ifeval's checker reads; the stand-in row declares the same two.
_RESOURCES: tuple[str, ...] = ("punkt", "punkt_tab")

#: What the stand-in download writes, sealed by the shared digest: the sha256 of the sorted
#: ``<sha256>  <path>`` listing of its two files. A literal, so a change to the sealing
#: scheme (which would move every row that pins a corpus) fails here first.
_STAND_IN_DIGEST: str = "0b65ee029acbcdbf18a85345813c35162f7ac5d3f576c3c63b8e87059ea394bb"

#: One canned Case, as the replay child would hand it back.
_CASES: list[PreparedCase] = [
    {
        "case": {"id": 1, "case_id": "1", "input": "What is 6 times 7?"},
        "grading_material": {"target": "42"},
    }
]


def _stand_in_download(resource: str, *, quiet: bool, download_dir: str) -> bool:
    """nltk.download with no network: one small fixture file where nltk would unzip the
    resource. Simulates the fetch; never the real corpus bytes."""

    folder: Path = Path(download_dir) / "tokenizers" / resource / "english"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "stand_in.txt").write_text(f"{resource} stand-in\n", encoding="utf-8")
    return True


def _cases_row(**nltk_fields: Any) -> TaskReplayCasesSpec:
    """The stand-in Case Preparation row: gsm8k's, sealed to the canned Case, plus nltk."""

    return replace(
        TASK_REPLAY_CASES["gsm8k"],
        case_count=len(_CASES),
        case_digest=case_digest(_CASES),
        **nltk_fields,
    )


def _assembled(cases_row: TaskReplayCasesSpec, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Assemble gsm8k's real row over ``cases_row`` through the real catalogue path, on
    fresh caches, with the replay answering the canned Case instead of a child process."""

    row: benchmarks.BenchmarkSpec = next(r for r in benchmarks.BENCHMARKS if r.key == "gsm8k")
    monkeypatch.setitem(TASK_REPLAY_CASES, "gsm8k", cases_row)
    monkeypatch.setattr(benchmarks, "BENCHMARKS", (row,))
    monkeypatch.setattr(benchmarks, "_ASSEMBLED", {})
    monkeypatch.setattr(single_shot, "_BENCHMARKS_BY_ID", {})
    monkeypatch.setattr(
        "screamingface_engine_inspect.task_replay.replay_with_provenance",
        lambda spec: TaskReplay(cases=list(_CASES), provenance={}),
    )
    # WHY a fresh path list: nltk's search path is process-wide, and a developer machine's
    # ~/nltk_data must not answer a lookup this suite says the bundle answers.
    monkeypatch.setattr(nltk.data, "path", [])
    monkeypatch.setattr(nltk, "download", _stand_in_download)
    return benchmarks.imported_benchmark("gsm8k")


# ── identity: the corpus moves the revision only when a row declares one ─────────────


def test_a_row_without_nltk_resources_adds_no_revision_pin() -> None:
    """No published revision moves: the pins of an undeclared row carry no nltk entry."""

    pins: tuple[str, ...] = benchmarks._task_replay_pins(_cases_row())

    assert not any(pin.startswith("nltk_") for pin in pins)


def test_the_resource_names_and_their_seal_are_revision_pins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same Task grading against another corpus is another Benchmark, so both the names
    (sorted, so row order never matters) and the files' seal join the revision."""

    plain: str = _assembled(_cases_row(), monkeypatch).benchmark.revision
    declared: TaskReplayCasesSpec = _cases_row(
        nltk_resources=("punkt_tab", "punkt"), nltk_data_digest=_STAND_IN_DIGEST
    )
    with_corpus: str = _assembled(declared, monkeypatch).benchmark.revision
    other_bytes: str = _assembled(
        replace(declared, nltk_data_digest="0" * 64), monkeypatch
    ).benchmark.revision

    # gsm8k is an inspect_evals import, so no local-Task source pin follows these two.
    assert benchmarks._task_replay_pins(declared)[-2:] == (
        "nltk_resources=punkt,punkt_tab",
        f"nltk_data_digest={_STAND_IN_DIGEST}",
    )
    assert len({plain, with_corpus, other_bytes}) == 3


@pytest.mark.parametrize(
    "fields",
    [{"nltk_resources": _RESOURCES}, {"nltk_data_digest": _STAND_IN_DIGEST}],
    ids=["names-without-seal", "seal-without-names"],
)
def test_half_a_corpus_declaration_is_refused_at_assembly(fields: dict[str, Any]) -> None:
    """A list with no seal would pin nothing checkable; a seal with no list seals nothing."""

    with pytest.raises(ValueError, match="nltk_resources and nltk_data_digest"):
        benchmarks._task_replay_pins(_cases_row(**fields))


# ── image build: the corpus lands in the bundle before cases.json, or the board skips ──


def test_prepare_writes_the_corpus_into_the_bundle_before_the_cases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """cases.json is the bundle's completion marker, so the corpus must already be there."""

    out: Path = tmp_path / "inspect-gsm8k"
    seen_cases_file_during_download: list[bool] = []

    def watching_download(resource: str, *, quiet: bool, download_dir: str) -> bool:
        """The stand-in download, also noting whether cases.json existed yet."""

        seen_cases_file_during_download.append((out / "cases.json").exists())
        return _stand_in_download(resource, quiet=quiet, download_dir=download_dir)

    imported: Any = _assembled(
        _cases_row(nltk_resources=_RESOURCES, nltk_data_digest=_STAND_IN_DIGEST), monkeypatch
    )
    monkeypatch.setattr(nltk, "download", watching_download)

    summary: dict[str, Any] = imported.registration.asset_bundle.prepare(out)

    assert summary["cases"] == 1 and UNCONFIRMED_CASES_KEY not in summary
    assert seen_cases_file_during_download == [False, False]
    for resource in _RESOURCES:
        assert (out / NLTK_DATA_DIR / "tokenizers" / resource / "english").is_dir()
    assert (out / "cases.json").is_file()


def test_a_row_without_nltk_resources_prepares_no_corpus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every existing row's bundle is unchanged: no folder, no download attempted."""

    imported: Any = _assembled(_cases_row(), monkeypatch)
    monkeypatch.setattr(nltk, "download", pytest.fail)

    imported.registration.asset_bundle.prepare(tmp_path / "out")

    assert not (tmp_path / "out" / NLTK_DATA_DIR).exists()


def test_a_corpus_that_seals_differently_skips_the_board_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The nltk index is not pinned by commit, so the seal is what notices it moved; the
    board goes SKIPPED like a broken Case Digest, never serving a corpus nobody reviewed."""

    imported: Any = _assembled(
        _cases_row(nltk_resources=_RESOURCES, nltk_data_digest="0" * 64), monkeypatch
    )

    summary: dict[str, Any] = imported.registration.asset_bundle.prepare(tmp_path / "out")

    reason: str = summary[UNCONFIRMED_CASES_KEY]
    assert reason.startswith("gsm8k: ") and f"seals to {_STAND_IN_DIGEST}" in reason
    assert not (tmp_path / "out" / "cases.json").exists()


def test_a_failed_download_skips_the_board_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    imported: Any = _assembled(
        _cases_row(nltk_resources=_RESOURCES, nltk_data_digest=_STAND_IN_DIGEST), monkeypatch
    )
    monkeypatch.setattr(nltk, "download", lambda resource, **_: False)

    summary: dict[str, Any] = imported.registration.asset_bundle.prepare(tmp_path / "out")

    assert "could not download the nltk resource 'punkt'" in summary[UNCONFIRMED_CASES_KEY]


# ── grading job: nltk reads the bundle, with no network to fall back on ────────────────


def test_grading_resolves_the_corpus_from_the_bundle_with_the_network_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The installer points nltk at <bundle>/nltk_data, so a lookup succeeds offline.

    Stand-in limit: this proves nltk FINDS the resource in the bundle; the fixture files are
    not a real tokenizer, so it does not prove a sentence splits (ifeval's #15 does).
    """

    imported: Any = _assembled(
        _cases_row(nltk_resources=_RESOURCES, nltk_data_digest=_STAND_IN_DIGEST), monkeypatch
    )
    assets: Path = tmp_path / "assets"
    imported.registration.asset_bundle.prepare(assets / imported.benchmark.id)

    def no_network(*_: Any, **__: Any) -> None:
        """The grading job's egress: none."""

        raise OSError("network disabled in this test")

    # WHY a fresh path list again: the image build and the grading job are two processes,
    # and the build's download registered the folder in this one's nltk path.
    monkeypatch.setattr(nltk.data, "path", [])
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(nltk, "download", no_network)
    imported.benchmark.install(Url4Node("test"), assets)

    found: Path = Path(str(nltk.data.find("tokenizers/punkt_tab/english/")))
    assert found.is_relative_to(assets / imported.benchmark.id / NLTK_DATA_DIR)


# ── import: the importer seals the corpus onto the row it writes ──────────────────────


def _sealed_import() -> TaskReplayImport:
    """A sealed import as the two replays return it. Stand-in: no Case Sources and no facts,
    which the nltk step never reads; it proves the seal step only, not the replays."""

    return TaskReplayImport(
        declaration=_cases_row(),
        case_sources=(),
        facts=None,  # type: ignore[arg-type]
    )


def test_the_importer_seals_the_named_resources_onto_the_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--nltk-resource downloads once at import and writes the seal every build checks, as
    the replays seal the Cases; a repeated name is kept once."""

    monkeypatch.setattr(nltk.data, "path", [])
    monkeypatch.setattr(nltk, "download", _stand_in_download)
    sealed_import: TaskReplayImport = _sealed_import()

    declaration: TaskReplayCasesSpec = importer._with_nltk_data(
        sealed_import, ["punkt", "punkt_tab", "punkt"]
    ).declaration

    assert declaration.nltk_resources == _RESOURCES
    assert declaration.nltk_data_digest == _STAND_IN_DIGEST


def test_an_import_without_nltk_resources_is_untouched() -> None:
    sealed_import: TaskReplayImport = _sealed_import()

    assert importer._with_nltk_data(sealed_import, []) is sealed_import
