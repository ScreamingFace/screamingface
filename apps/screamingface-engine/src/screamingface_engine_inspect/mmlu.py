"""MMLU (0-shot), imported from inspect_evals — the MCQ proof board.

Multiple choice over 57 subjects: their ``choice()`` scorer reads the answer marks the
shim replays onto the fabricated state (their own ``parse_answers`` machinery). MCQ
boards get NO check surface — pass/fail feedback over four options is an elimination
attack, and the client preflight's refusal of a loop recipe here is correct behavior
(OME-796 rule, spec §4 exception).

STORY: as a researcher, I evaluate a fusion against the most-cited knowledge benchmark
without anyone porting it by hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from screamingface_engine_inspect.pins import (
    MMLU_CASE_COUNT,
    MMLU_CONFIG,
    MMLU_DATASET,
    MMLU_DATASET_REVISION,
    MMLU_SHUFFLE_SEED,
    MMLU_SPLIT,
)
from screamingface_engine_inspect.prepare import prepare_mmlu
from screamingface_engine_inspect.single_shot import (
    ImportedBoard,
    install_imported_board,
    single_shot_board,
)
from url4.peer.server import Url4Node

#: The asset directory this board's installer reads under the assets root —
#: exported beside the installer per the deployment conformance rule.
ASSET_BUNDLE_ID = "inspect-mmlu"


def install_mmlu(node: Url4Node, assets: Path) -> None:
    """Install the MMLU booklet, check/record route, and aggregate (no check surface)."""

    install_imported_board(node, assets, ASSET_BUNDLE_ID)


def _scorer() -> Any:
    """Their scorer, bound directly from the pinned package — provenance:
    inspect_evals.mmlu.mmlu's ``mmlu_0_shot`` Task declares ``scorer=choice()``."""

    from inspect_ai.scorer import choice

    return choice()


MMLU_BOARD: ImportedBoard = single_shot_board(
    board_key="mmlu",
    title="MMLU",
    description=(
        "14,042 multiple-choice questions across 57 subjects (the MMLU test split, "
        "0-shot), imported from inspect_evals. The model answers with one lettered "
        "choice; grading is inspect's own choice scorer against the published key, so "
        "no judge tokens are spent. Cases are served in a fixed seeded shuffle so a "
        "limited run spans subjects. Benchmark score = plain accuracy over the cases "
        "run. No mid-run check surface: pass/fail feedback over four options would "
        "let a loop eliminate choices rather than improve answers."
    ),
    focus="Broad multi-subject knowledge (multiple choice)",
    dataset_url="https://huggingface.co/datasets/cais/mmlu",
    case_count=MMLU_CASE_COUNT,
    revision_pins=(
        MMLU_DATASET,
        MMLU_CONFIG,
        MMLU_SPLIT,
        MMLU_DATASET_REVISION,
        f"shuffle_seed={MMLU_SHUFFLE_SEED}",
    ),
    scorer_factory=_scorer,
    prepare=prepare_mmlu,
    install=install_mmlu,
    # OME-796: MCQ boards are refused a check surface by design.
    with_check_surface=False,
)

__all__ = ["ASSET_BUNDLE_ID", "MMLU_BOARD", "install_mmlu"]
