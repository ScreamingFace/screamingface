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
    # FEATURE: OME-1307 (E14, GW-freeze) - freeze and export counters, in process like the above.
    freezes: collections.Counter[str] = field(
        default_factory=collections.Counter
    )  # by created / reused / not_found / too_large
    missing_total: int = 0
    export_pending: int = 0
    export_failures: int = 0
    export_digest_mismatches: int = 0
    # FEATURE: OME-1307 (E14, GW-replay) - replay lookups by result: hit / miss / invalid_grant.
    replay_lookups: collections.Counter[str] = field(default_factory=collections.Counter)
