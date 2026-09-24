"""Parse the request ``Cache-Control`` field into a run's cache INTENT (spec §5.1, D6).

WHY this is now a re-export: unit 3's node tier parses the SAME header through the same
function, but it lives in the shared ``world`` package and may not import the control plane
(``.claude/scripts/check_layering.py``). The parser therefore moved to the shared leaf
:mod:`screamingface_engine.cache_intent`, and this module stays as a re-export for existing
importers (``tests/unit/test_rest_cache_header.py``) rather than a second copy — the REST edge
now imports :mod:`screamingface_engine.cache_intent` directly. The full rationale lives with
the implementation; this file owns only the App-side name.
"""

from __future__ import annotations

from screamingface_engine.cache_intent import parse_cache_control

__all__ = ["parse_cache_control"]
