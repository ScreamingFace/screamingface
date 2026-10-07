# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on.
"""What inspect's registry says about a scorer: its name, and what kind of headline it
declares — a plain mean, or something else.

FEATURE (OME-1268): a Benchmark's Headline Score is the mean of its headline column over
the graded Cases. A scorer whose FIRST declared metric is not a plain mean (SimpleQA's
``simpleqa_metric``, a formula over the column means) would have its headline published
as ``mean(correct)`` by that reducer — the wrong number. The importer (PR 4 of 5) reads
this and refuses such a Task by name until the row declares a reducer.

Mental model: ask the scorer "what number do you put at the top of your results
column?" — if the answer is "inspect's own average, unmodified", we can reproduce it;
anything else needs a declared formula first.
"""

from __future__ import annotations

from typing import Any, Literal

#: QUALIFIED registry names of the metrics that ARE a plain mean of one column.
#: WHY qualified: an eval may register its own metric named ``accuracy`` (hle's, which
#: converts each value first); only inspect's own, default-constructed, is the mean we
#: reproduce.
_PLAIN_MEANS: frozenset[str] = frozenset({"inspect_ai/accuracy", "inspect_ai/mean"})
#: Declared beside a mean on nearly every scorer; it never changes what the headline is.
_IGNORED: frozenset[str] = frozenset({"inspect_ai/stderr"})

type HeadlineMetricKind = Literal["mean", "other"]


def headline_metric_kind(scorer: Any) -> HeadlineMetricKind:
    """``"mean"`` when the scorer's first declared metric (ignoring ``stderr``) is inspect's
    own ``accuracy`` or ``mean`` with no conversion argument; ``"other"`` for a custom
    metric (even one named ``accuracy``), an ``accuracy(to_float=...)``, a grouped metric
    block, or a scorer that declares no metric at all.

    The headline is the FIRST declared metric, inspect's own rule for a Task with no
    ``headline_metric``. Extra metrics after it (cyberseceval_4's grouped breakdowns)
    do not change the answer: they are the importer's Named Deviation, not a refusal.
    """

    headline: Any | None = _headline_metric(scorer)
    return "mean" if headline is not None and _is_plain_mean(headline) else "other"


def scorer_registry_name(scorer: Any) -> str:
    """The unqualified registry name of a scorer or its constructor (``f1`` for
    ``inspect_ai.scorer.f1``) — the name a Named Score column carries.

    Raises ``ValueError`` (inspect's own) for an object the registry does not know.
    """

    from inspect_ai._util.registry import registry_unqualified_name

    return str(registry_unqualified_name(scorer))


def _headline_metric(scorer: Any) -> Any | None:
    """The first declared metric that is not ``stderr``; ``None`` when the scorer declares
    none, declares a grouped block, or declares one the registry does not know."""

    for metric in _declared_metrics(scorer):
        if metric is None:
            return None
        if _qualified_name(metric) not in _IGNORED:
            return metric
    return None


def _declared_metrics(scorer: Any) -> list[Any | None]:
    """The scorer's declared metrics in order; ``None`` stands for one with no registry
    identity (a grouped block, an unregistered object); a dict declaration is one ``None``."""

    from inspect_ai.scorer._scorer import scorer_metrics

    try:
        declared: Any = scorer_metrics(scorer)
    except (KeyError, AttributeError):
        declared = []
    # WHY: a dict is inspect's grouped-metric form (name → metrics); it has no single
    # column to average, so the headline cannot be reproduced by a mean.
    if isinstance(declared, dict):
        return [None]
    return [None if _qualified_name(metric) is None else metric for metric in declared]


def _is_plain_mean(metric: Any) -> bool:
    """True for inspect's own ``accuracy`` or ``mean``, default-constructed.

    WHY the parameter check: ``accuracy(to_float=lambda v: 1 - float(v))`` keeps the
    registry name ``inspect_ai/accuracy`` but averages a transformed column — inspect
    would publish 1.0 where our column mean says 0.0. Identity is name AND no arguments.
    """

    from inspect_ai._util.registry import registry_params

    return _qualified_name(metric) in _PLAIN_MEANS and not registry_params(metric)


def _qualified_name(metric: Any) -> str | None:
    """One metric's qualified registry name (``inspect_ai/accuracy``), or ``None`` for a
    grouped block or an unregistered object."""

    from inspect_ai._util.registry import registry_info

    if isinstance(metric, dict):
        return None
    try:
        return str(registry_info(metric).name)
    except Exception:  # noqa: BLE001 — an unregistered metric still has no plain name
        return None
