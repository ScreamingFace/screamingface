"""Answer signal keys and the sf.signal seam (OME-1289 gap, signals I-S1, BU-E2).

INVARIANT: FIELD_PATH is the Engine's combine/ports.py field-path grammar, copied line for line;
STU/test_signal_key_conformance.py binds the copy. E4b adds declared signals through this seam.
"""

from __future__ import annotations

import re

_FIELD_KEY = r"[A-Za-z_][A-Za-z0-9_]*"  # verbatim E/combine/ports.py
_FIELD_INDEX = r"\[(?:0|[1-9][0-9]*)\]"
FIELD_PATH = re.compile(rf"(?:{_FIELD_KEY}|{_FIELD_INDEX})(?:\.{_FIELD_KEY}|{_FIELD_INDEX})*")
ACCOUNTING_SIGNALS: tuple[str, ...] = ("cost_usd", "latency_ms", "tokens_in", "tokens_out")
FIELD_SIGNAL_PREFIX = "field:"
JUDGE_SIGNAL = "score:judge"


def is_signal_key(key: object) -> bool:
    """I-S1: an accounting key, score:judge, or field:<FIELD_PATH>."""

    if not isinstance(key, str):
        return False
    if key in ACCOUNTING_SIGNALS or key == JUDGE_SIGNAL:
        return True
    return key.startswith(FIELD_SIGNAL_PREFIX) and (
        FIELD_PATH.fullmatch(key[len(FIELD_SIGNAL_PREFIX) :]) is not None
    )


__all__: list[str] = []
