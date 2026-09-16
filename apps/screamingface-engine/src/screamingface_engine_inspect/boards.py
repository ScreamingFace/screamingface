"""The plugin's board table — every imported benchmark is a ROW here, never a file.

A board is two data rows: its :class:`~screamingface_engine_inspect.prepare.SnapshotSpec`
(dataset pins, in ``prepare.SNAPSHOTS``) and its :class:`BoardSpec` below (catalogue
metadata + a dotted reference to the eval's own scorer). One generic assembler turns
the pair into a registered board, so importing benchmark #13 adds two rows and zero
functions (owner decision 2026-09-16; OME-1115's per-file boards #955/#956 were closed
unmerged in favor of this).

Imported ONLY behind :func:`screamingface_engine_inspect.deployment.inspect_available`,
and every inspect import below is lazy, so the module itself stays extra-free.

STORY: as a researcher, I run a fusion (or a corrective_loop) against a benchmark we
never hand-built, from the same notebook as any home-grown board.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from importlib import import_module
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.deployment import BenchmarkRegistration
from screamingface_engine_inspect.prepare import (
    SNAPSHOTS,
    SnapshotSpec,
    prepare_snapshot,
)
from screamingface_engine_inspect.single_shot import (
    ImportedBoard,
    install_imported_board,
    single_shot_board,
)
from url4.peer.server import Url4Node


@dataclass(frozen=True)
class BoardSpec:
    """One imported board's catalogue row — pure data, paired with its SnapshotSpec.

    ``scorer`` is a dotted ``"module:attr"`` reference to the eval's own scorer
    constructor (the same convention SnapshotSpec uses for ``record_to_sample``),
    called with ``scorer_kwargs`` — provenance lives in the row, resolution is lazy.
    """

    key: str
    title: str
    description: str
    focus: str
    dataset_url: str
    scorer: str
    scorer_kwargs: Mapping[str, Any] = field(default_factory=dict)
    #: §4 dual registration; False for MCQ boards — pass/fail feedback over a
    #: handful of options is an elimination attack (OME-796).
    with_check_surface: bool = False
    multiple_correct: bool = False


#: Every imported board, in catalogue order. Importing another eval = one row here
#: plus its SnapshotSpec row — never a new module. The mmlu row lands in this
#: ticket's next PR.
BOARDS: tuple[BoardSpec, ...] = (
    BoardSpec(
        key="gsm8k",
        title="GSM8K",
        description=(
            "1,319 grade-school math word problems (the GSM8K test split), imported "
            "from inspect_evals. The model reasons step by step and commits a final "
            "numeric answer; grading is inspect's own numeric match against the "
            "published solution, so no judge tokens are spent. Benchmark score = "
            "plain accuracy over the cases run."
        ),
        focus="Grade-school math word problems",
        dataset_url="https://huggingface.co/datasets/openai/gsm8k",
        # Provenance: inspect_evals.gsm8k.gsm8k's Task declares scorer=match(numeric=True).
        scorer="inspect_ai.scorer:match",
        scorer_kwargs={"numeric": True},
        # Free-form answers make mid-run feedback legitimate: the same scorer serves
        # the corrective loop (spec §4; owner decision on OME-1115, 2026-09-15).
        with_check_surface=True,
    ),
)


def imported_board(key: str) -> ImportedBoard:
    """The assembled board for one table row — assembled once, then cached."""

    if key not in _ASSEMBLED:
        specs: dict[str, BoardSpec] = {spec.key: spec for spec in BOARDS}
        if key not in specs:
            raise KeyError(f"no imported board row with key {key!r}")
        _ASSEMBLED[key] = _assemble(specs[key])
    return _ASSEMBLED[key]


def board_registrations() -> tuple[BenchmarkRegistration, ...]:
    """Every imported board, in catalogue order — the plugin's entry-point payload."""

    return tuple(imported_board(spec.key).registration for spec in BOARDS)


def _assemble(spec: BoardSpec) -> ImportedBoard:
    """Row pair in, registered board out — the whole per-board 'code' path."""

    snapshot: SnapshotSpec = SNAPSHOTS[spec.key]
    return single_shot_board(
        board_key=spec.key,
        title=spec.title,
        description=spec.description,
        focus=spec.focus,
        dataset_url=spec.dataset_url,
        case_count=snapshot.case_count,
        revision_pins=_revision_pins(snapshot),
        scorer_factory=_scorer_factory(spec),
        prepare=partial(prepare_snapshot, snapshot),
        install=_installer(f"inspect-{spec.key}"),
        with_check_surface=spec.with_check_surface,
        multiple_correct=spec.multiple_correct,
    )


def _revision_pins(snapshot: SnapshotSpec) -> tuple[str, ...]:
    """Exam-identity pins derived from the board's snapshot row — never duplicated."""

    pins: list[str] = [
        snapshot.dataset,
        snapshot.config,
        snapshot.split,
        snapshot.dataset_revision,
    ]
    if snapshot.shuffle_seed is not None:
        pins.append(f"shuffle_seed={snapshot.shuffle_seed}")
    return tuple(pins)


def _scorer_factory(spec: BoardSpec) -> Callable[[], Any]:
    """Resolve the eval's own scorer from the row's dotted reference, lazily."""

    def factory() -> Any:
        module_name, _, attribute = spec.scorer.partition(":")
        constructor: Any = getattr(import_module(module_name), attribute)
        return constructor(**dict(spec.scorer_kwargs))

    return factory


def _installer(benchmark_id: str) -> Callable[[Url4Node, Path], None]:
    """One installer per board, carrying the bundle id ON the function.

    WHY the attribute: the deployment conformance check reads the asset directory a
    board's installer actually opens from the installer itself; with boards as rows
    in ONE module, a per-module ``ASSET_BUNDLE_ID`` constant cannot work, so the
    installer function carries it (owner-approved conformance-rule amendment,
    2026-09-16).
    """

    def install(node: Url4Node, assets: Path) -> None:
        install_imported_board(node, assets, benchmark_id)

    install.ASSET_BUNDLE_ID = benchmark_id  # type: ignore[attr-defined]
    return install


_ASSEMBLED: dict[str, ImportedBoard] = {}


__all__ = ["BOARDS", "BoardSpec", "board_registrations", "imported_board"]
