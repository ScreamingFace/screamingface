"""GSM8K, imported from inspect_evals — the §4 dual-registration proof board.

Free-form grade-school math: their ``match(numeric=True)`` scorer compares the
committed final answer to the pinned target. Free-form answers make mid-run feedback
legitimate, so this board declares the check surface — the same scorer serving the
corrective loop (spec §4; owner decision on `OME-1115`, 2026-09-15).

STORY: as a researcher, I run a fusion (or a corrective_loop) against a benchmark we
never hand-built, from the same notebook as any home-grown board.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from screamingface_engine_inspect.pins import (
    GSM8K_CASE_COUNT,
    GSM8K_DATA_DIR,
    GSM8K_DATASET,
    GSM8K_DATASET_REVISION,
    GSM8K_SPLIT,
)
from screamingface_engine_inspect.prepare import prepare_gsm8k
from screamingface_engine_inspect.single_shot import (
    ImportedBoard,
    install_imported_board,
    single_shot_board,
)
from url4.peer.server import Url4Node

#: The asset directory this board's installer reads under the assets root —
#: exported beside the installer per the deployment conformance rule.
ASSET_BUNDLE_ID = "inspect-gsm8k"


def install_gsm8k(node: Url4Node, assets: Path) -> None:
    """Install the GSM8K booklet, check/record route, aggregate, and check surface."""

    install_imported_board(node, assets, ASSET_BUNDLE_ID)


def _scorer() -> Any:
    """Their scorer, bound directly from the pinned package — provenance:
    inspect_evals.gsm8k.gsm8k's Task declares ``scorer=match(numeric=True)``."""

    from inspect_ai.scorer import match

    return match(numeric=True)


GSM8K_BOARD: ImportedBoard = single_shot_board(
    board_key="gsm8k",
    title="GSM8K",
    description=(
        "1,319 grade-school math word problems (the GSM8K test split), imported from "
        "inspect_evals. The model reasons step by step and commits a final numeric "
        "answer; grading is inspect's own numeric match against the published "
        "solution, so no judge tokens are spent. Benchmark score = plain accuracy "
        "over the cases run."
    ),
    focus="Grade-school math word problems",
    dataset_url="https://huggingface.co/datasets/openai/gsm8k",
    case_count=GSM8K_CASE_COUNT,
    revision_pins=(GSM8K_DATASET, GSM8K_DATA_DIR, GSM8K_SPLIT, GSM8K_DATASET_REVISION),
    scorer_factory=_scorer,
    prepare=prepare_gsm8k,
    install=install_gsm8k,
    # The dual registration: their scorer is also the corrective loop's check surface.
    with_check_surface=True,
)

__all__ = ["ASSET_BUNDLE_ID", "GSM8K_BOARD", "install_gsm8k"]
