"""The catalogue's closed axis vocabularies — the SDK's deliberate engine copies.

FEATURE: the catalogue listing grouped by difficulty × interaction (OME-1257).
WHY copies at all: the listing needs the easy→hard ORDER of the tiers (and display
labels keyed by these values) without importing engine internals. A pure-data module
with no imports, so both the wire decoder and the notebook renderer can read it
without a cycle (`_report_primitives.py` precedent for the failure-code vocabulary).

INVARIANT: value-for-value AND order-for-order identical to the engine's
_DIFFICULTY_TIERS / _INTERACTION_TYPES in `benchmarks/definition.py` — pinned by
test_catalogue_vocabulary_conformance on BOTH sides (failure-codes bind, OME-1233).
Decoding stays tolerant of values outside these tuples; they order the KNOWN groups,
they never refuse a row.
"""

from __future__ import annotations

DECLARED_DIFFICULTY_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
DECLARED_INTERACTION_TYPES: tuple[str, ...] = ("single_shot", "multi_turn")

__all__: list[str] = []
