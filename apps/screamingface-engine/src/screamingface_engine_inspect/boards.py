"""The plugin's board list — every imported benchmark this crate registers.

Imported ONLY behind :func:`screamingface_engine_inspect.deployment.inspect_available`,
so board modules may import ``inspect_ai`` / ``inspect_evals`` freely at module level.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.deployment import BenchmarkRegistration


def board_registrations() -> tuple[BenchmarkRegistration, ...]:
    """Every imported board, in catalogue order."""

    from screamingface_engine_inspect.gsm8k import GSM8K_BOARD
    from screamingface_engine_inspect.mmlu import MMLU_BOARD

    return (GSM8K_BOARD.registration, MMLU_BOARD.registration)


__all__ = ["board_registrations"]
