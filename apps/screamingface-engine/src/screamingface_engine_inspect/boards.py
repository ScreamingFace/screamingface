"""The plugin's board list — every imported benchmark this crate registers.

Imported ONLY behind :func:`screamingface_engine_inspect.deployment.inspect_available`,
so board modules may import ``inspect_ai`` / ``inspect_evals`` freely at module level.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.deployment import BenchmarkRegistration


def board_registrations() -> tuple[BenchmarkRegistration, ...]:
    """Every imported board, in catalogue order.

    AIDEV-NOTE: empty while the seam lands first — the two proof boards
    (`inspect-gsm8k`, `inspect-mmlu`) register here in this ticket's later commits.
    """

    return ()


__all__ = ["board_registrations"]
