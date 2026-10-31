"""This process's resident memory — current and peak — as one diagnostic log line.

FEATURE (memory diagnostics, epic OME-1314): a FigQA run on fusion.dev was killed at 2,862 MiB
while measurement explained ~2.1 GiB of it. The worker samples the run's process TREE every 2 s
(`worker.memory_watch`), so a short spike and the idle baseline are both invisible there. The
run itself logs what it holds at three points — `run_start`, `cases_loaded`, `run_end` — so the
baseline and the Cases' cost read straight off the run's log, attributed by `logs.run_scope`.

Standard library only, deliberately: this sits on a Job's cold path (`check_layering.py`).

INVARIANT: a line carries readings and counts only — never a prompt, a Case, or an expression.
INVARIANT: a reading that fails is skipped; diagnostics never fail the run they describe.
"""

from __future__ import annotations

import logging
import os
import resource
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

STATM = Path("/proc/self/statm")

_MIB = 2**20


def current_resident_bytes(statm: Path = STATM, page_size: int | None = None) -> int | None:
    """Resident bytes of THIS process now, or ``None`` when unknown.

    WHY ``statm`` and not ``status``: one short line, field 2 is resident pages — cheaper than
    scanning ``VmRSS:``. WHY ``None`` off Linux: macOS has no ``/proc`` and the standard library
    offers no current-RSS call there; ``unknown`` is honest, a 0 would read as a measurement.
    """
    try:
        resident_pages = int(statm.read_text().split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return resident_pages * (page_size if page_size is not None else os.sysconf("SC_PAGE_SIZE"))


def peak_resident_bytes(*, maxrss: int | None = None, platform: str = sys.platform) -> int:
    """This process's peak resident bytes since it started (``getrusage`` ``ru_maxrss``).

    WHY the platform switch: Linux reports ``ru_maxrss`` in KiB, macOS in bytes.
    """
    if maxrss is None:
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return maxrss if platform == "darwin" else maxrss * 1024


def _mib(value: int) -> str:
    return f"{value / _MIB:.1f}"


def log_process_memory(point: str, **counts: int) -> None:
    """Log ``process memory point=<point> rss_mib=… peak_rss_mib=…`` plus integer counts.

    AIDEV-NOTE: ``counts`` is typed ``int`` on purpose — it is the only free-form field, and a
    count cannot carry Case content. Keep it that way.
    """
    try:
        current = current_resident_bytes()
        peak = peak_resident_bytes()
    except (OSError, ValueError) as exc:
        logger.debug("process memory at %s unreadable: %s", point, type(exc).__name__)
        return
    extra = "".join(f" {key}={value:d}" for key, value in counts.items())
    logger.info(
        "process memory point=%s rss_mib=%s peak_rss_mib=%s%s",
        point,
        "unknown" if current is None else _mib(current),
        _mib(peak),
        extra,
    )
