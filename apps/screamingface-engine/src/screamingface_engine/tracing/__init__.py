"""Turning a run's frame stream into spans (OME-1130, Phase 2).

INVARIANT: `span_tree` is PURE — standard library only, no OTel, no network. The OTel
dependency lives in the sink beside it and nowhere else, because
`packages/url4/tests/unit/test_import_isolation.py` forbids `opentelemetry` anywhere reachable
from `import url4` and checks it in a clean subprocess. Keeping the semantics separate from the
transport is also what lets the risky half change without re-testing the meaning.

AIDEV-NOTE — DO NOT re-export from `.otlp` here. This package is imported by
`runner/main.py`, and `otlp` pulls the OTel SDK, protobuf and `requests` (~62 ms of a Job's
~227 ms import budget). Importing it from this `__init__` would re-introduce that cost on every
run while looking like tidy-up, and would silently undo the lazy import in `main.span_sink`.
`tests/unit/test_span_export_wiring.py` fails if it happens.
"""

from .relay import SpanRelay, SpanSink, otlp_configured
from .span_tree import Span, SpanTree, build_span_tree, span_from_frame

__all__ = [
    "Span",
    "SpanRelay",
    "SpanSink",
    "SpanTree",
    "build_span_tree",
    "otlp_configured",
    "span_from_frame",
]
