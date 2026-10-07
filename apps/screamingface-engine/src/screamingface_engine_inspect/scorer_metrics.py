# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on.
"""What kind of headline an inspect scorer declares: a plain mean, or something else.

FEATURE (OME-1268): a Benchmark's Headline Score is the mean of its headline column over
the graded Cases. A scorer whose FIRST declared metric is not a plain mean (SimpleQA's
``simpleqa_metric``, a formula over the column means) would have its headline published
as ``mean(correct)`` by that reducer — the wrong number. The importer (PR 4 of 5) reads
this and refuses such a Task by name until the row declares a reducer.

Mental model: ask the scorer "what number do you put at the top of your results
column?" — if the answer is "the average", we can reproduce it; anything else needs a
declared formula first.
"""

from __future__ import annotations

from typing import Any, Literal

#: inspect registry names of the metrics that ARE a plain mean of one column.
_PLAIN_MEANS: frozenset[str] = frozenset({"accuracy", "mean"})
#: Declared beside a mean on nearly every scorer; it never changes what the headline is.
_IGNORED: frozenset[str] = frozenset({"stderr"})

type HeadlineMetricKind = Literal["mean", "other"]


def headline_metric_kind(scorer: Any) -> HeadlineMetricKind:
    """``"mean"`` when the scorer's first declared metric (ignoring ``stderr``) is inspect's
    ``accuracy`` or ``mean``; ``"other"`` for a custom metric, a grouped metric block, or
    a scorer that declares no metric at all.

    The headline is the FIRST declared metric, inspect's own rule for a Task with no
    ``headline_metric``. Extra metrics after it (cyberseceval_4's grouped breakdowns)
    do not change the answer: they are the importer's Named Deviation, not a refusal.
    """

    headline: str | None = _headline_metric_name(scorer)
    return "mean" if headline in _PLAIN_MEANS else "other"


def _headline_metric_name(scorer: Any) -> str | None:
    """The registry name of the first declared metric that is not ``stderr``; ``None``
    when the scorer declares none, declares a grouped block, or declares one with no name."""

    from inspect_ai.scorer._scorer import scorer_metrics

    try:
        declared: Any = scorer_metrics(scorer)
    except (KeyError, AttributeError):
        declared = []
    # WHY: a dict is inspect's grouped-metric form (name → metrics); it has no single
    # column to average, so the headline cannot be reproduced by a mean.
    names: list[str | None] = (
        [None] if isinstance(declared, dict) else [_metric_name(metric) for metric in declared]
    )
    for name in names:
        if name is None:
            return None
        if name not in _IGNORED:
            return name
    return None


def _metric_name(metric: Any) -> str | None:
    """One metric's unqualified registry name, or ``None`` for a grouped block or an
    unregistered object."""

    from inspect_ai._util.registry import registry_unqualified_name

    if isinstance(metric, dict):
        return None
    try:
        return str(registry_unqualified_name(metric))
    except Exception:  # noqa: BLE001 — an unregistered metric still has no plain name
        return None
