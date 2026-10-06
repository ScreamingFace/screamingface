# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The importer command after OME-1460: one path, Task replay, for every eval.

INVARIANT: every flag the dev passes reaches the import (and through it both replays), and a
refusal is one error line that writes nothing.

The import itself is a stand-in here (import_by_task_replay is injected): these tests prove
the command's wiring; test_import_replay.py proves the replays.
"""

from __future__ import annotations

import shutil
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
from screamingface_engine_inspect.importer import ImporterError, main  # noqa: E402
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec  # noqa: E402

_SRC_DIR: Path = Path(importer_module.__file__).resolve().parent
_TASK: str = "inspect_evals.commonsense_qa.commonsense_qa:commonsense_qa"


@pytest.fixture
def engine_src_copy(tmp_path: Path) -> Path:
    """A working copy of the two files the importer writes into."""

    for name in ("prepare.py", "benchmarks.py"):
        shutil.copy(_SRC_DIR / name, tmp_path / name)
    return tmp_path


def _sealed_import() -> TaskReplayImport:
    """A sealed import, as import_by_task_replay returns it; no child runs."""

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
            case_count=1221,
            case_digest="e" * 64,
            source_pins={"tau/commonsense_qa": "94630fe30dad47192a8546eb75f094926d47e155"},
            shuffle_seed=20260917,
        ),
        case_sources=(
            CaseSource(
                "hugging-face",
                "tau/commonsense_qa",
                "revision 94630fe30dad47192a8546eb75f094926d47e155",
            ),
        ),
        facts=facts,
    )


class _RecordingImport:
    """Stand-in import_by_task_replay that remembers what the command passed it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None, dict[str, Any]]] = []

    def __call__(
        self, task_ref: str, task_args: Mapping[str, Any] | None, **options: Any
    ) -> TaskReplayImport:
        """Record the call; return a sealed import."""

        self.calls.append((task_ref, dict(task_args) if task_args else None, options))
        return _sealed_import()


def test_main_imports_by_task_replay_without_a_flag(engine_src_copy: Path) -> None:
    """R10: no reader decides the route any more; every eval is imported by Task replay."""

    recording: _RecordingImport = _RecordingImport()

    code: int = main(
        [_TASK, "--key", "csqa", "--task-arg", "split=validation"]
        + ["--engine-src", str(engine_src_copy)],
        import_by_task_replay=recording,
        dataset_info=lambda repo_id, revision: type("Info", (), {"card_data": {}})(),
    )

    assert code == 0
    assert recording.calls[0][:2] == (_TASK, {"split": "validation"})
    prepare_text: str = (engine_src_copy / "prepare.py").read_text()
    assert '"csqa": TaskReplayCasesSpec(' in prepare_text
    assert "        shuffle_seed=20260917," in prepare_text


def test_every_option_reaches_the_import_with_its_default(engine_src_copy: Path) -> None:
    recording: _RecordingImport = _RecordingImport()

    main(
        [_TASK, "--key", "csqa", "--engine-src", str(engine_src_copy)],
        import_by_task_replay=recording,
        dataset_info=lambda repo_id, revision: type("Info", (), {"card_data": {}})(),
    )

    assert recording.calls[0][2] == {
        "excluded_sample_ids": None,
        "has_answer_key": True,
        "shuffle_seed": None,
        "choice_shuffle_seed": None,
        "keep_sample_metadata": False,
    }


def test_the_seed_flags_and_the_metadata_flag_reach_the_import(engine_src_copy: Path) -> None:
    """D7: the seed flags keep their names and now mean the seed the enforcer forces."""

    recording: _RecordingImport = _RecordingImport()

    main(
        [_TASK, "--key", "csqa", "--shuffle-seed", "20260917", "--choice-shuffle-seed", "7"]
        + ["--keep-sample-metadata", "--excluded-sample-id", "a", "--no-answer-key"]
        + ["--engine-src", str(engine_src_copy)],
        import_by_task_replay=recording,
        dataset_info=lambda repo_id, revision: type("Info", (), {"card_data": {}})(),
    )

    assert recording.calls[0][2] == {
        "excluded_sample_ids": ("a",),
        "has_answer_key": False,
        "shuffle_seed": 20260917,
        "choice_shuffle_seed": 7,
        "keep_sample_metadata": True,
    }


def test_a_refusal_is_one_error_line_and_writes_nothing(
    engine_src_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def refusing(task_ref: str, task_args: Mapping[str, Any] | None, **_: Any) -> TaskReplayImport:
        """Refuse as an unseeded shuffle does."""

        raise ImporterError(f"{task_ref}: declare shuffle_seed (--shuffle-seed)")

    code: int = main(
        [_TASK, "--key", "csqa", "--engine-src", str(engine_src_copy)],
        import_by_task_replay=refusing,
    )

    assert code == 1
    assert capsys.readouterr().err.startswith(f"ERROR: {_TASK}: declare shuffle_seed")
    assert (engine_src_copy / "prepare.py").read_text() == (_SRC_DIR / "prepare.py").read_text()


def test_the_task_replay_flag_is_gone() -> None:
    """R10: with one path there is nothing to choose; an old command fails loudly."""

    with pytest.raises(SystemExit):
        main([_TASK, "--key", "csqa", "--task-replay"])
