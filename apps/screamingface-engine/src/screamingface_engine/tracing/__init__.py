"""Turning a run's frame stream into spans (OME-1130, Phase 2).

INVARIANT: `span_tree` is PURE — standard library only, no OTel, no network. The OTel
dependency lives in the sink beside it and nowhere else, because
`packages/url4/tests/unit/test_import_isolation.py` forbids `opentelemetry` anywhere reachable
from `import url4` and checks it in a clean subprocess. Keeping the semantics separate from the
transport is also what lets the risky half change without re-testing the meaning.
"""

from .span_tree import Span, SpanTree, build_span_tree

__all__ = ["Span", "SpanTree", "build_span_tree"]
