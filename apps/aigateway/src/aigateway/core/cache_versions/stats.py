"""In-process capture counters (OME-1307, GW-capture).

FEATURE: OME-1307 (E14) - the PRD metrics ``aigw_capture_rows_total{outcome}`` and
``aigw_capture_failures_total``.

AIDEV-NOTE: the counters stay in process. There is no exporter and no route (decided: D7, X-15).
The gateway has no metrics stack today; do not add a metrics library here.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field


@dataclass
class CaptureStats:
    rows: collections.Counter[str] = field(default_factory=collections.Counter)  # by outcome
    failures: int = 0
