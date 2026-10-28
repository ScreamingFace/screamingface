# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The importer warns when a dataset bundles other datasets (OME-1757).

INVARIANT: a dataset that looks like a bundle (a per-row ``source`` column on its card, or
many configs of one Hub repo) gets a warning to check each source's licence by hand, and the
licence the importer proposes is decided exactly as before. A plain dataset gets no warning.

WHY it matters: MathVista's card says cc-by-sa-4.0, a cleared licence, but 195 of its 1,000
testmini Cases come from NonCommercial sources. Without the warning the row would say
cc-by-sa-4.0 and nobody would be asked to look.

Every card here is a stand-in for ``HfApi().dataset_info(...)``: no test reaches the Hub.
"""

from __future__ import annotations

import shutil
import types
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect import importer as importer_module  # noqa: E402
from screamingface_engine_inspect.case_sources import CaseSource  # noqa: E402
from screamingface_engine_inspect.import_replay import (  # noqa: E402
    TaskReplayFacts,
    TaskReplayImport,
)
from screamingface_engine_inspect.importer import main  # noqa: E402
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec  # noqa: E402
from screamingface_engine_inspect.task_replay_rows import (  # noqa: E402
    AGGREGATE_DATASET_WARNING,
    CardLicense,
    TaskReplayRows,
    card_license_of,
    render_task_replay_rows,
)

_SRC_DIR: Path = Path(importer_module.__file__).resolve().parent
_MATHVISTA_COMMIT: str = "2b6ad69445fbb5695c9b165475e8decdbeb97747"
_MMMU_COMMIT: str = "171b0ef74cd1704464e6940860968009d8cdd59a"
_CSQA_COMMIT: str = "94630fe30dad47192a8546eb75f094926d47e155"
_TASK: str = "inspect_evals.mathvista.mathvista:mathvista"

#: MathVista's card header, trimmed to what the importer reads: the licence, and the
#: features, where ``metadata`` is a struct whose ``source`` names each row's dataset.
_MATHVISTA_CARD: dict[str, Any] = {
    "license": "cc-by-sa-4.0",
    "dataset_info": {
        "features": [
            {"name": "pid", "dtype": "string"},
            {"name": "question", "dtype": "string"},
            {
                "name": "metadata",
                "struct": [
                    {"name": "category", "dtype": "string"},
                    {"name": "source", "dtype": "string"},
                    {"name": "task", "dtype": "string"},
                ],
            },
        ],
        "splits": [{"name": "testmini", "num_examples": 1000}],
    },
}
#: commonsense_qa's card header, trimmed the same way: one source, no per-row source column.
_PLAIN_CARD: dict[str, Any] = {
    "license": "mit",
    "dataset_info": {
        "features": [
            {"name": "id", "dtype": "string"},
            {"name": "question", "dtype": "string"},
            {"name": "choices", "sequence": [{"name": "label", "dtype": "string"}]},
        ],
        "splits": [{"name": "validation", "num_examples": 1221}],
    },
}
#: MMMU's 30 subject configs, as the eval loads them (one Case Source each).
_MMMU_SUBJECTS: tuple[str, ...] = tuple(f"Subject_{index:02d}" for index in range(30))


def _hub(card: Mapping[str, Any]) -> Any:
    """A stand-in for HfApi().dataset_info that answers every repo with this card."""

    return lambda dataset, revision: types.SimpleNamespace(card_data=dict(card))


def _never(dataset: str, revision: str | None) -> Any:
    """A Hub that must not be asked: no single card speaks for several sources."""

    raise AssertionError("no card to read")


def _mathvista_source() -> CaseSource:
    """MathVista's one Case Source: one repo, one config."""

    return CaseSource("hugging-face", "AI4Math/MathVista", f"revision {_MATHVISTA_COMMIT}")


def _mmmu_sources() -> tuple[CaseSource, ...]:
    """MMMU's Case Sources: one per subject config of the one repo."""

    return tuple(
        CaseSource("hugging-face", f"MMMU/MMMU/{subject}", f"revision {_MMMU_COMMIT}")
        for subject in _MMMU_SUBJECTS
    )


def _imported(sources: tuple[CaseSource, ...]) -> TaskReplayImport:
    """A sealed import as import_by_task_replay returns it (no child runs here)."""

    facts: TaskReplayFacts = TaskReplayFacts(
        task_ref=_TASK,
        task_args=None,
        mcq=True,
        scorer="inspect_ai.scorer:choice",
        scorer_kwargs={},
        custom_metrics=(),
        keep_sample_metadata=False,
    )
    return TaskReplayImport(
        declaration=TaskReplayCasesSpec(
            task=_TASK,
            case_count=1000,
            case_digest="e" * 64,
            source_pins={source.hub_repo_id(): _MATHVISTA_COMMIT for source in sources},
        ),
        case_sources=sources,
        facts=facts,
    )


def _declared_license(rows: TaskReplayRows, key: str) -> str:
    """Evaluate the generated declaration and return its licence value."""

    namespace: dict[str, Any] = {"TaskReplayCasesSpec": TaskReplayCasesSpec}
    exec("declared = {\n" + rows.cases + "}", namespace)  # noqa: S102 — our own rendered row
    return namespace["declared"][key].license


# ── the two signals, read off what the importer already has ──────────────────────


def test_a_per_row_source_column_on_the_card_marks_a_bundle_and_keeps_its_licence() -> None:
    """MathVista: a cleared card licence, but each row names one of 31 source datasets."""

    license_read: CardLicense = card_license_of(
        (_mathvista_source(),), dataset_info=_hub(_MATHVISTA_CARD)
    )

    # The licence is decided exactly as without the signal: cleared, so it is the value.
    assert license_read.value == "cc-by-sa-4.0"
    assert license_read.card_says is None
    assert license_read.aggregate_signal == (
        "the card's rows carry a 'source' column naming each row's dataset"
    )


def test_a_source_column_in_any_config_of_a_multi_config_card_marks_a_bundle() -> None:
    """A card with several configs lists dataset_info per config; any one may carry it."""

    card: dict[str, Any] = {
        "license": "cc-by-4.0",
        "dataset_info": [
            {"config_name": "a", "features": [{"name": "question", "dtype": "string"}]},
            {"config_name": "b", "features": [{"name": "source", "dtype": "string"}]},
        ],
    }

    license_read: CardLicense = card_license_of((_mathvista_source(),), dataset_info=_hub(card))

    assert license_read.aggregate_signal is not None


def test_many_configs_of_one_repo_mark_a_bundle_without_reading_a_card() -> None:
    """MMMU: 30 subject configs, so no card is read (spec R7) and the licence stays TODO."""

    license_read: CardLicense = card_license_of(_mmmu_sources(), dataset_info=_never)

    assert license_read == CardLicense(
        value="TODO",
        card_says=None,
        aggregate_signal="the eval reads 30 configs of MMMU/MMMU",
    )


def test_two_configs_of_one_repo_are_not_a_bundle() -> None:
    """air_bench reads its Cases config plus judge_prompts: a helper, not a second source."""

    sources: tuple[CaseSource, ...] = (
        CaseSource("hugging-face", "stanford-crfm/air-bench-2024", "unpinned"),
        CaseSource("hugging-face", "stanford-crfm/air-bench-2024/judge_prompts", "unpinned"),
    )

    assert card_license_of(sources, dataset_info=_never).aggregate_signal is None


def test_a_plain_single_source_dataset_gets_no_warning() -> None:
    """commonsense_qa: one config, no per-row source column, so nothing to warn about."""

    source: CaseSource = CaseSource(
        "hugging-face", "tau/commonsense_qa", f"revision {_CSQA_COMMIT}"
    )

    license_read: CardLicense = card_license_of((source,), dataset_info=_hub(_PLAIN_CARD))

    assert license_read == CardLicense(value="mit", card_says=None, aggregate_signal=None)


def test_a_split_named_source_is_not_a_source_column() -> None:
    """Only the features name row columns; a split or config called source says nothing."""

    card: dict[str, Any] = {
        "license": "mit",
        "dataset_info": {
            "config_name": "source",
            "features": [{"name": "question", "dtype": "string"}],
            "splits": [{"name": "source", "num_examples": 10}],
        },
    }

    assert card_license_of((_mathvista_source(),), dataset_info=_hub(card)).aggregate_signal is None


# ── where the warning lands: the licence's review note, and the command's output ─


def test_the_warning_lands_above_the_licence_line_and_leaves_its_value_alone() -> None:
    signal: str = "the card's rows carry a 'source' column naming each row's dataset"

    rows: TaskReplayRows = render_task_replay_rows(
        "mathvista", _imported((_mathvista_source(),)), "cc-by-sa-4.0", aggregate_signal=signal
    )

    assert (
        "        # TODO(review): aggregate dataset — check each source's licence by hand\n"
        "        # before writing the licence line.\n"
        f"        #   Why it looks like one: {signal}.\n"
        '        license="cc-by-sa-4.0",\n'
    ) in rows.cases
    assert _declared_license(rows, "mathvista") == "cc-by-sa-4.0"


def test_a_row_without_a_signal_carries_no_warning() -> None:
    rows: TaskReplayRows = render_task_replay_rows(
        "mathvista", _imported((_mathvista_source(),)), "cc-by-sa-4.0"
    )

    assert "aggregate dataset" not in rows.cases
    assert "aggregate dataset" not in rows.benchmark


def test_a_signal_with_a_line_break_is_refused() -> None:
    """The signal lands in a comment; a line break would end it and start code."""

    with pytest.raises(importer_module.ImporterError, match="injection guard"):
        render_task_replay_rows(
            "mathvista",
            _imported((_mathvista_source(),)),
            "TODO",
            aggregate_signal="x\nimport os",
        )


@pytest.fixture
def engine_src_copy(tmp_path: Path) -> Path:
    """A working copy of the two files the importer writes into."""

    for name in ("prepare.py", "benchmarks.py"):
        shutil.copy(_SRC_DIR / name, tmp_path / name)
    return tmp_path


def _command(engine_src: Path, imported: TaskReplayImport, card: Mapping[str, Any]) -> int:
    """Run the importer command with a stand-in import and a stand-in Hub."""

    return main(
        [_TASK, "--key", "mathvista", "--engine-src", str(engine_src)],
        import_by_task_replay=lambda task_ref, task_args, **options: imported,
        dataset_info=_hub(card),
    )


def test_the_command_prints_the_warning_for_a_bundle(
    engine_src_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code: int = _command(engine_src_copy, _imported((_mathvista_source(),)), _MATHVISTA_CARD)

    assert code == 0
    err: str = capsys.readouterr().err
    assert f"WARNING: {AGGREGATE_DATASET_WARNING} (the card's rows carry a 'source'" in err
    prepare_text: str = (engine_src_copy / "prepare.py").read_text()
    assert "# TODO(review): aggregate dataset" in prepare_text


def test_the_command_prints_no_warning_for_a_plain_dataset(
    engine_src_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code: int = _command(engine_src_copy, _imported((_mathvista_source(),)), _PLAIN_CARD)

    assert code == 0
    assert "WARNING" not in capsys.readouterr().err
    assert "aggregate dataset" not in (engine_src_copy / "prepare.py").read_text()
