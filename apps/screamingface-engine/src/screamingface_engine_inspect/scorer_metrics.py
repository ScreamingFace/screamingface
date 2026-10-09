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
this and refuses such a Task unless the importing agent chooses, per Benchmark, to honour
the eval's own metric or to keep the mean under a Named Deviation (OME-1527, R1).

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
#: What the importer writes for a metric that has no registry name (inspect's grouped
#: form, name → metrics). WHY words, not a sentinel: the note lands in a generated row and
#: must pass the renderer's reference charset; ``<unnamed metric>`` refused the whole import.
_GROUPED_BLOCK: str = "a grouped metric block"

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


def extra_metric_names(scorer: Any) -> tuple[str, ...]:
    """Every declared metric that is neither the headline nor ``stderr`` nor a plain mean,
    by registry name — the breakdowns the Benchmark does not reproduce (cyberseceval_4's
    grouped accuracy and Jaccard). The importer writes them as a Named Deviation note; a
    grouped metric block after the headline, which has no registry name, is written in
    words (``a grouped metric block``)."""

    extras: list[str] = []
    seen_headline: bool = False
    for metric in _declared_metrics(scorer):
        if metric is None:
            extras.append(_GROUPED_BLOCK)
            continue
        if _qualified_name(metric) in _IGNORED:
            continue
        if not seen_headline:
            seen_headline = True
            continue
        if not _is_plain_mean(metric):
            extras.append(_metric_name(metric))
    return tuple(extras)


def headline_metric_name(scorer: Any) -> str | None:
    """The unqualified registry name of the headline metric, for a refusal message;
    ``None`` when the scorer declares none, a grouped block, or an unregistered one."""

    headline: Any | None = _headline_metric(scorer)
    return None if headline is None else _metric_name(headline)


def headline_metric_reference(scorer: Any) -> str:
    """The dotted ``module:constructor`` reference a row writes to honour the scorer's
    headline metric (``inspect_evals.xstest.xstest:refusal_rate``), called with no arguments.

    Raises ``ValueError`` saying why the row cannot name it: a grouped metric block or an
    unregistered metric has no constructor; one built with arguments (bbeh's
    ``grouped(accuracy(), group_key="task")``) is a metric OBJECT the row cannot rebuild from
    a name; one whose module does not export its constructor cannot be imported back; one
    declared ``@metric(scores="unreduced")`` reads each Sample's raw Score, where the tally
    hands it the reduced one.
    """

    from importlib import import_module

    from inspect_ai._util.registry import registry_params

    headline: Any | None = _headline_metric(scorer)
    if headline is None:
        raise ValueError("a grouped metric block or an unregistered metric has no constructor")
    if reads_unreduced_scores(headline):
        raise ValueError("it asks for unreduced Scores, which the tally does not keep")
    name: str = _metric_name(headline)
    params: dict[str, Any] = dict(registry_params(headline))
    if params:
        raise ValueError(f"it is created with arguments {sorted(params)}")
    qualified: str = str(_qualified_name(headline))
    # WHY: inspect's own metrics are defined in private modules and exported here.
    module_name: str = (
        "inspect_ai.scorer" if qualified.startswith("inspect_ai/") else headline.__module__
    )
    if not hasattr(import_module(module_name), name):
        raise ValueError(f"{module_name} does not export its constructor")
    return f"{module_name}:{name}"


def reads_unreduced_scores(metric: Any) -> bool:
    """True for a metric declared ``@metric(scores="unreduced")``: inspect hands it each
    Sample's raw Score ("C"), never the reduced one (1.0) the whole-run tally keeps."""

    from inspect_ai.scorer._metric import metric_scores

    return metric_scores(metric) == "unreduced"


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


def _metric_name(metric: Any) -> str:
    """One registered metric's unqualified name (``accuracy``), for messages and notes."""

    from inspect_ai._util.registry import registry_unqualified_name

    return str(registry_unqualified_name(metric))
