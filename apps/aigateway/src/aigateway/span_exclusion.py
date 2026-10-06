"""Which routes' server spans are never exported — health-check probes, by default (OME-1217).

FEATURE (OME-1217): `GET /healthz` was 60.2% of aigateway's spans in SigNoz (14,403 of 23,906 in
24h), and as ROOT spans they buried real requests in the trace list. aigateway's server spans
come from `middleware/call_id.py`, not `FastAPIInstrumentor`, so OTel's own exclusion knob had
no effect until this module gave the middleware one.

WHY a gateway-specific `AIGW_TRACE_EXCLUDED_ROUTES` (OME-1453), not OTel's
`OTEL_PYTHON_EXCLUDED_URLS`: the list is searched against the RESOLVED ROUTE TEMPLATE, not the raw
URL — a raw path invites bypass via `/healthz/` or a query string, and matching the template
means a parametrised route is excluded as one route, not as a family of paths. That makes it a
different knob from OTel's, and sharing OTel's name was a trap: operators set that variable
cluster-wide with UNANCHORED values for the stock instrumentors (e.g. `healthz,models`), and read
here such a value silently dropped real gateway routes like `/v1/models`. The format is otherwise
OTel's (comma-separated regexes, `re.search`), and entries are meant to be ANCHORED (`^…$`).

HOW (owner decision 2026-10-01, option A): the route is only known AFTER routing — FastAPI's
nested `_IncludedRouter` resolves nothing before dispatch through any public API — so the span is
built as usual, FLAGGED once routing has resolved a probe route (`mark_excluded`), and dropped at
export by `DropExcludedSpans`. Built-but-never-exported is the cost of using public APIs only.

AIDEV-NOTE: `OTEL_PYTHON_EXCLUDED_URLS` is NOT honoured here, deliberately (OME-1453) — do not
"restore" it as a fallback. aigateway reads `AIGW_TRACE_EXCLUDED_ROUTES` through its `Settings`
and hands the raw value to `SpanExclusion.from_setting`; `from_env` remains for callers without a
settings object. Write entries anchored: an unanchored `models` matches `/v1/models`.

AIDEV-NOTE: stdlib + `opentelemetry-sdk` only, no aigateway import, on purpose. Apps must not
import each other's internals (see `logs.py`), so the engine's control plane (OME-1218: `url4.run`
as a child of the accept span, probes excluded) takes a copy of this file — keep it liftable.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor
from opentelemetry.trace import Span as ApiSpan

logger = logging.getLogger(__name__)

ENV_VAR = "AIGW_TRACE_EXCLUDED_ROUTES"

EXCLUDED_ATTRIBUTE = "aigw.span.excluded"
"""The internal flag `DropExcludedSpans` drops on. Never exported: a flagged span is dropped."""

DEFAULT_EXCLUDED_ROUTES: tuple[str, ...] = ("^/healthz$",)
"""The probe routes. Anchored: an unanchored `healthz` would also swallow any future route that
merely contains the word."""


@dataclass(frozen=True)
class SpanExclusion:
    """A compiled exclusion list. `None` pattern means "exclude nothing"."""

    pattern: re.Pattern[str] | None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> SpanExclusion:
        """Read the list from `env[ENV_VAR]`; see `from_setting` for the semantics."""
        return cls.from_setting(env.get(ENV_VAR))

    @classmethod
    def from_setting(cls, raw: str | None) -> SpanExclusion:
        """Parse the raw setting value (comma-separated, anchored regexes over route templates).

        - unset (`None`) → the probe default;
        - set but blank (or only commas) → exclude nothing — an operator can turn probe spans
          back on without a code change;
        - an invalid regex → the probe default, with a warning.

        INVARIANT: never raises. Like `tracing.install`, a telemetry misconfiguration must not
        stop an AI gateway from serving.
        """
        if raw is None:
            return cls._compile(DEFAULT_EXCLUDED_ROUTES)
        entries = tuple(entry.strip() for entry in raw.split(",") if entry.strip())
        try:
            return cls._compile(entries)
        except re.error:
            # WHY the value is not echoed: a log line is the wrong place to reflect arbitrary
            # env input back out. The variable name is enough to find it.
            logger.warning("%s is not a valid pattern list; using the probe default", ENV_VAR)
            return cls._compile(DEFAULT_EXCLUDED_ROUTES)

    @classmethod
    def _compile(cls, entries: tuple[str, ...]) -> SpanExclusion:
        if not entries:
            return cls(pattern=None)
        return cls(pattern=re.compile("|".join(f"(?:{entry})" for entry in entries)))

    def excludes(self, route: str | None) -> bool:
        """Whether a request resolved to `route` (a template) gets no server span.

        INVARIANT: an unresolved request (`None`) is never excluded — "we could not tell what
        this is" must produce MORE telemetry, not less.
        """
        if route is None or self.pattern is None:
            return False
        return self.pattern.search(route) is not None


def mark_excluded(span: ApiSpan | None) -> None:
    """Flag `span` so the export path drops it. A no-op for no span (tracing off)."""
    if span is not None:
        span.set_attribute(EXCLUDED_ATTRIBUTE, True)


class DropExcludedSpans(SpanProcessor):
    """Forward every span to `delegate` EXCEPT the ones `mark_excluded` flagged.

    WHY a wrapping processor rather than a sampler: a sampler decides at span START, and the
    route is only known after routing — by then the span exists. Dropping at `on_end` is the
    only public point where the decision can be made after the fact.
    INVARIANT: the flag is the ONLY thing this inspects; an unflagged span passes untouched.
    """

    def __init__(self, delegate: SpanProcessor) -> None:
        self._delegate = delegate

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        self._delegate.on_start(span, parent_context=parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        if (span.attributes or {}).get(EXCLUDED_ATTRIBUTE) is True:
            return
        self._delegate.on_end(span)

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._delegate.force_flush(timeout_millis)


__all__ = [
    "DEFAULT_EXCLUDED_ROUTES",
    "ENV_VAR",
    "EXCLUDED_ATTRIBUTE",
    "DropExcludedSpans",
    "SpanExclusion",
    "mark_excluded",
]
