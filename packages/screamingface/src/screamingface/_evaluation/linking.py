"""Bind one complete Candidate Recipe into one Benchmark expression."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, replace

from url4 import Expression, Text, VarRef, build, render, src, text

from screamingface.errors import PlanningError

_WHOLE_CANDIDATE = "$candidate"
_CANDIDATE_REFERENCE = re.compile(
    r"(?<!\$)\$candidate(?:_members|_synthesizer|_member_[A-Za-z0-9_]+)?(?![A-Za-z0-9_])"
)


@dataclass(frozen=True, slots=True)
class _LinkedCandidate:
    url4: str


@dataclass(frozen=True, slots=True)
class _PreparedBenchmark:
    """One parsed-and-validated Benchmark expression, reusable across Candidates.

    WHY: the Benchmark is loop-invariant across an Evaluation's Candidates — parse
    and reference-scan it once, then bind each compiled Candidate's canonical text.
    """

    node: Expression

    def bind(self, candidate_url4: str) -> _LinkedCandidate:
        """Bind one canonical Candidate expression text into this Benchmark.

        The Candidate is the FIRST source of the Benchmark's own top-level group, so every
        ``$candidate`` inside it resolves. WHY no wrapper group: ``(candidate, benchmark)!''``
        puts an empty prompt in intent position, which URL4 reads as an LLM prompt.
        """

        # WHY `$$`: the Benchmark's terminal is code, so its group is an RDS scope where quoted
        # text is interpolated strictly (Spec B §6.3); the Recipe's own `$input` must stay
        # literal, and `$$` is the grammar's literal dollar (Spec B §6.2).
        binding = src(text(candidate_url4.replace("$", "$$")), name="candidate", weight=0.0)
        rendered = render(replace(self.node, sources=(binding, *self.node.sources)))
        _require_candidate_references_bound(rendered)
        return _LinkedCandidate(url4=rendered)


def link_candidate(candidate_url4: str, benchmark_url4: str) -> _LinkedCandidate:
    """Bind the sole public Candidate seam without interpreting Benchmark behavior.

    Canonicalizes arbitrary caller Candidate text through build+render; the internal
    Evaluation path calls ``_prepare_benchmark(...).bind(...)`` directly because the
    compiler's output is already canonical.
    """

    return _prepare_benchmark(benchmark_url4).bind(render(build(candidate_url4)))


def _prepare_benchmark(benchmark_url4: str) -> _PreparedBenchmark:
    benchmark = build(benchmark_url4)
    references = _text_references(benchmark)
    if _WHOLE_CANDIDATE not in references:
        structural = sorted(value for value in references if value.startswith("$candidate_"))
        if structural:
            names = ", ".join(structural)
            raise PlanningError(
                f"Benchmark uses unsupported structural Candidate bindings: {names}; "
                "Benchmarks must consume one complete $candidate Recipe",
                code="candidate_shape_mismatch",
                permanent=True,
            )
        raise PlanningError(
            "Benchmark URL4 does not invoke the Candidate",
            code="invalid_benchmark_resource",
            permanent=True,
        )
    unsupported = sorted(value for value in references if value != _WHOLE_CANDIDATE)
    if unsupported:
        names = ", ".join(unsupported)
        raise PlanningError(
            f"Benchmark uses unsupported structural Candidate bindings: {names}; "
            "Benchmarks must consume one complete $candidate Recipe",
            code="candidate_shape_mismatch",
            permanent=True,
        )
    if not isinstance(benchmark, Expression) or benchmark.intent is None:
        raise PlanningError(
            "Benchmark URL4 must be one top-level (sources)!intent expression",
            code="invalid_benchmark_resource",
            permanent=True,
        )
    return _PreparedBenchmark(node=benchmark)


def _require_candidate_references_bound(rendered: str) -> None:
    """Refuse to ship a linked artifact that still names something nothing binds.

    INVARIANT: every ``$candidate*`` reference in the shipped artifact resolves to the
    one ``candidate`` binding emitted above. This is checked on the RENDERED surface
    rather than the parsed tree on purpose: ``_text_references`` reasons over an AST
    where a reference has several shapes and the node set can grow upstream, while
    ``render`` collapses them all into one form. The check is therefore
    representation-independent — it closes the whole class of walker-blindness bugs
    rather than the one shape that motivated it, and it turns a mid-Run failure into
    a plan-time one, before the Candidate has been paid for.
    """

    unresolved = _references(rendered) - {_WHOLE_CANDIDATE}
    if unresolved:
        names = ", ".join(sorted(unresolved))
        raise PlanningError(
            f"Benchmark URL4 references {names}, which this Candidate does not bind",
            code="candidate_shape_mismatch",
            permanent=True,
        )


def _text_references(value: object) -> set[str]:
    leaf = _leaf_references(value)
    if leaf is not None:
        return leaf
    selected: set[str] = set()
    for child in _children(value):
        selected.update(_text_references(child))
    return selected


def _leaf_references(value: object) -> set[str] | None:
    selected = None
    if isinstance(value, Text):
        selected = _references(value.value)
    elif isinstance(value, VarRef):
        selected = _references(f"${value.name}") | _text_references(value.path)
    elif isinstance(value, str):
        selected = _references(value)
    return selected


def _children(value: object) -> tuple[object, ...]:
    selected: tuple[object, ...] = ()
    if isinstance(value, tuple | list):
        selected = tuple(value)
    elif isinstance(value, Mapping):
        selected = tuple(item for pair in value.items() for item in pair)
    elif is_dataclass(value) and not isinstance(value, type):
        selected = tuple(getattr(value, field.name) for field in fields(value))
    return selected


def _references(value: str) -> set[str]:
    return set(_CANDIDATE_REFERENCE.findall(value))


__all__: list[str] = []
