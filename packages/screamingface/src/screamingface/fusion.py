"""Composite Candidate values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import get_close_matches
from types import MappingProxyType
from typing import Any, ClassVar, Literal

from screamingface._signals import (
    ACCOUNTING_SIGNALS,
    MAX_DECLARED_SIGNALS,
    RESERVED_NAME_PREFIXES,
    Signal,
    is_signal_key,
    is_signal_name,
)
from screamingface.model import Model
from screamingface.recipe import Recipe, _inferred_name, _name, _optional, _recipe
from screamingface.reducer import _MAX_REDUCER_MEMBERS, Reducer, Vote, _read_signal
from screamingface.signal_sources import (
    INJECTED_PARAMS,
    Consistency,
    Entropy,
    Logprob,
    SignalSource,
    Sum,
    consistency_seed,
)


@dataclass(frozen=True, slots=True, init=False)
class Fusion(Recipe):
    """Combine ordered parallel members through an explicit synthesizer Recipe.

    ``quorum`` is the successful-member floor, checked after members finish.
    Member Recipes marked ``optional=True`` tolerate failure; required members
    must succeed. ``all`` requires every member; zero permits
    synthesis with no successful member. The synthesizer itself stays required.

    ``sf.Fusion(members, synthesizer=sf.Model(p))`` is the named recipe Fan-out →
    ``Reduce.compute(context)`` → Model. Its block form,
    ``sf.Pipeline([sf.Fusion(members, synthesizer=sf.Reduce("context")), sf.Model(p)])``,
    compiles to the same url4 byte for byte.

    ``signals=`` declares up to 8 named sources (``sf.Verbalized(...)``) that the members
    carry. A reducer synthesizer reads one of them with ``sf.signal(name)``; a rule that reads a
    name the Fusion does not declare fails here, before any member call. Only a reducer
    synthesizer takes ``signals=``. A vote gate that reads ``chosen:<name>`` or ``mean:<name>``
    needs ``<name>`` in ``signals=`` too.
    ``sf.Sum({"a": 0.5, "b": 0.3})`` declares a fixed linear sum of other names of the same
    ``signals=`` (never another sum); it counts toward the 8 names, and a vote weight cannot read
    a sum that adds ``sf.Logprob("mean")``, ``sf.Logprob("sum")`` or ``sf.Entropy``.
    """

    name: str
    members: tuple[Recipe, ...]
    synthesizer: Recipe | Reducer
    quorum: int | Literal["all"]
    optional: bool
    signals: Mapping[str, SignalSource] | None

    def __init__(
        self,
        members: Sequence[str | Recipe],
        *,
        name: str | None = None,
        signals: Mapping[str, SignalSource] | None = None,
        synthesizer: str | Recipe | Reducer,
        quorum: int | Literal["all"] = "all",
        optional: bool = False,
    ) -> None:
        selected_members = _members(members)
        optional = _optional(optional)
        object.__setattr__(self, "quorum", _quorum(quorum, len(selected_members)))
        object.__setattr__(self, "optional", optional)
        inferred_name = _inferred_name(selected_members)
        object.__setattr__(
            self,
            "name",
            inferred_name if name is None else _name(name, "fusion name"),
        )
        object.__setattr__(self, "members", selected_members)
        object.__setattr__(self, "synthesizer", _synthesizer(synthesizer, selected_members))
        object.__setattr__(self, "signals", _declared(signals, self.synthesizer))
        _check_logprob_sources(self.signals, selected_members, self.synthesizer)
        _check_consistency_source(self.signals, selected_members)

    @property
    def _recipe_marker(self) -> None:
        return None

    def __repr__(self) -> str:
        # WHY: member failure policy must be visible without expanding required members.
        members = ", ".join(
            repr(member) if member.optional else repr(member.name) for member in self.members
        )
        inferred_name = _inferred_name(self.members)
        arguments = [f"[{members}]"]
        if self.name != inferred_name:
            arguments.append(f"name={self.name!r}")
        if self.signals is not None:
            arguments.append(f"signals={_signals_repr(self.signals)}")
        arguments.append(f"synthesizer={self.synthesizer!r}")
        if self.quorum != "all":
            arguments.append(f"quorum={self.quorum!r}")
        if self.optional:
            arguments.append("optional=True")
        return f"Fusion({', '.join(arguments)})"

    def _repr_html_(self) -> str:
        from screamingface._ui.cards import fusion_card_html

        return fusion_card_html(self)

    __hash__: ClassVar[Any] = None


def _declared(value: object, synthesizer: Recipe | Reducer) -> Mapping[str, SignalSource] | None:
    """The checked declaration (sorted by name), and every name the reducer reads (ans:Q1, P2)."""
    declared = _declaration(value)
    combine = isinstance(synthesizer, Reducer) and synthesizer._compiles_to_combine()
    if declared is not None and not combine:
        raise ValueError(
            "Fusion signals= needs a reducer synthesizer such as sf.Vote, sf.Median, sf.Mean, "
            "sf.Pick, sf.Rank or sf.Filter: a model synthesizer has no combine step to record them"
        )
    if combine:
        assert isinstance(synthesizer, Reducer)
        _check_reads(synthesizer, declared)
        _check_gate_name(synthesizer, declared)
    return declared


def _declaration(value: object) -> Mapping[str, SignalSource] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("Fusion signals must map names to sources such as sf.Verbalized(...)")
    if not value:
        return None  # signals={} is no declaration: the same bytes as none
    if len(value) > MAX_DECLARED_SIGNALS:
        raise ValueError(
            f"a Fusion declares at most {MAX_DECLARED_SIGNALS} signals, not {len(value)}"
        )
    for name, source in value.items():
        _check_declared(name, source)
    if sum(source.source == "entropy" for source in value.values()) > 1:
        raise ValueError(
            "a Fusion declares at most one sf.Entropy source: every member call takes one "
            "top_logprobs value"
        )
    if sum(source.source == "consistency" for source in value.values()) > 1:
        raise ValueError(
            "a Fusion declares at most one sf.Consistency source: every member gets one set "
            "of samples"
        )
    _check_sums(value)
    return MappingProxyType(dict(sorted(value.items())))


def _check_declared(name: object, source: object) -> None:
    if not isinstance(name, str):
        raise TypeError("Fusion signal names must be text")
    if not is_signal_name(name):
        raise ValueError(_name_rejection(name))
    if not isinstance(source, SignalSource):
        raise TypeError(f"Fusion signal {name!r} must be a source such as sf.Verbalized(...)")


def _name_rejection(name: str) -> str:
    if is_signal_key(name):
        return (
            f"{name!r} is an E4a signal key; read it with sf.signal({name!r}) and do not declare it"
        )
    if name.startswith(RESERVED_NAME_PREFIXES):
        return (
            f"{name!r} is reserved: a declared name must not start with logprob, entropy, "
            "verbalized or consistency"
        )
    return f"{name!r} is not a declared name: a declared name matches [a-z][a-z0-9_]{{0,31}}"


def _check_sums(declared: Mapping[str, SignalSource]) -> None:
    """Each sf.Sum adds only names this Fusion declares, and never a sum (SA-E2, SA-E3; P3).

    WHY no sum of sums: no cycle and no order rule (D3). The sums go in name order and their terms
    in name order, so the first error does not depend on the dict order of ``signals=``.
    """
    listed = ", ".join(sorted(declared))
    for name, source in sorted(declared.items()):
        if isinstance(source, Sum):
            for component in source.coefficients:
                _check_sum_component(name, component, declared, listed)


def _check_sum_component(
    name: str, component: str, declared: Mapping[str, SignalSource], listed: str
) -> None:
    if component not in declared:
        raise ValueError(
            f"sf.Sum {name!r} adds {component!r}, which this Fusion does not declare "
            f"(declared: {listed})"
        )
    if isinstance(declared[component], Sum):
        raise ValueError(
            f"sf.Sum {name!r} adds {component!r}, which is an sf.Sum; a sum adds only other "
            "sources, not sums"
        )


def _check_reads(reducer: Reducer, declared: Mapping[str, SignalSource] | None) -> None:
    """A rule that reads a name this Fusion does not declare fails here, before any call (DS-E1)."""
    signal = _read_signal(reducer._plan())
    if signal is None or is_signal_key(signal.key):
        return
    names = () if declared is None else tuple(declared)
    if signal.key in names:
        return
    listed = ", ".join(names) if names else "none"
    message = (
        f"the synthesizer reads sf.signal({signal.key!r}), which this Fusion does not declare "
        f"(declared: {listed})"
    )
    hint = get_close_matches(signal.key, ACCOUNTING_SIGNALS, n=1)
    if hint:
        message += f"; did you mean {hint[0]}?"
    raise ValueError(message)


def _check_gate_name(reducer: Reducer, declared: Mapping[str, SignalSource] | None) -> None:
    """A vote gate that reads a name this Fusion does not declare fails here, before any call
    (GA-E2)."""
    gate = reducer.gate if isinstance(reducer, Vote) else None
    name = None if gate is None else gate._declared_name()
    names = () if declared is None else tuple(declared)
    if gate is None or name is None or name in names:
        return
    listed = ", ".join(names) if names else "none"
    raise ValueError(
        f"the gate reads {gate.observe!r}, but this Fusion does not declare {name!r} "
        f"(declared: {listed})"
    )


def _check_logprob_sources(
    declared: Mapping[str, SignalSource] | None,
    members: tuple[Recipe, ...],
    synthesizer: Recipe | Reducer,
) -> None:
    """The checks that only a Fusion can make, because only it sees the declaration, the members
    and the rule (P14): a vote weight must be greater than 0 (LP-E1, EN-E2), and sf.Logprob or
    sf.Entropy needs each member to be one OpenRouter sf.Model call (DS-I4, LP-E2, LP-E3, EN-E3,
    U4-D1)."""
    if declared is None:
        return
    needs = [s for s in declared.values() if isinstance(s, Logprob | Entropy)]
    if not needs:
        return
    assert isinstance(synthesizer, Reducer)  # _declared refused a model synthesizer
    _check_weight_source(declared, synthesizer)
    label = f"sf.{type(needs[0]).__name__}"
    for position, member in enumerate(members, 1):
        _check_logprob_member(label, position, member)


def _check_weight_source(declared: Mapping[str, SignalSource], reducer: Reducer) -> None:
    weights = reducer._plan().weights
    if not isinstance(weights, Signal) or weights.key not in declared:
        return
    source = declared[weights.key]
    if isinstance(source, Sum):
        _check_sum_weight(weights.key, source, declared)
    if isinstance(source, Logprob) and source.form != "prob":
        raise ValueError(
            f"sf.Logprob({source.form!r}) cannot be a vote weight: a weight must be greater "
            f"than 0 and a log-probability is at most 0; declare {weights.key!r} as "
            "sf.Logprob('prob') instead"
        )
    if isinstance(source, Entropy):
        raise ValueError(
            "sf.Entropy cannot be a vote weight: a higher entropy means LESS confidence; read "
            f"sf.signal({weights.key!r}) with sf.Pick or sf.Rank and order='min'"
        )


def _check_sum_weight(key: str, total: Sum, declared: Mapping[str, SignalSource]) -> None:
    """P13: a vote weight must be greater than 0, so a sum that adds a raw logprob or an entropy
    cannot be one (part 3 ans:Q11). ``_check_sums`` already proved each component is declared."""
    for component in total.coefficients:
        part = declared[component]
        if (isinstance(part, Logprob) and part.form != "prob") or isinstance(part, Entropy):
            raise ValueError(
                f"sf.Sum {key!r} cannot be a vote weight: it adds {component!r} ({part!r}), and "
                f"a weight must be greater than 0; read sf.signal({key!r}) with sf.Pick, "
                "sf.Rank or sf.Filter instead"
            )


def _check_logprob_member(label: str, position: int, member: Recipe) -> None:
    if not isinstance(member, Model):
        raise ValueError(
            f"{label} needs each Fusion member to be one sf.Model call; member {position} "
            f"({member.name!r}) is a nested Fusion or Pipeline"
        )
    if not member.model.removeprefix("/").startswith("openrouter/"):
        raise ValueError(
            f"{label} supports OpenRouter models in v1; member {position} uses {member.model!r}"
        )
    clash = sorted(INJECTED_PARAMS & set(member.params))
    if clash:
        raise ValueError(
            f"{label} sets the {' and '.join(clash)} param of every member; remove it from "
            f"member {position} ({member.name!r})"
        )


_MAX_CONSISTENCY_CALLS = 1024  # P4: bounds the url4 and the combine context


def _check_consistency_source(
    declared: Mapping[str, SignalSource] | None, members: tuple[Recipe, ...]
) -> None:
    """The sf.Consistency rules that need the members (P4, P5; erd CN-I2, CN-I3, CN-I5): each
    member is one sf.Model call, the Fusion makes at most 1024 extra calls, and no member seed
    equals a sample seed of this Fusion."""
    source = next((s for s in (declared or {}).values() if isinstance(s, Consistency)), None)
    if source is None:
        return
    models: list[Model] = []
    for position, member in enumerate(members, 1):
        if not isinstance(member, Model):
            raise ValueError(
                "sf.Consistency needs each Fusion member to be one sf.Model call; member "
                f"{position} ({member.name!r}) is a nested Fusion or Pipeline"
            )
        models.append(member)
    calls = len(models) * source.n
    if calls > _MAX_CONSISTENCY_CALLS:
        raise ValueError(
            f"sf.Consistency(n={source.n}) on {len(models)} members makes {calls} extra calls; "
            f"the limit is {_MAX_CONSISTENCY_CALLS} per Fusion"
        )
    _check_sample_seeds(models, source.n)


def _check_sample_seeds(models: list[Model], n: int) -> None:
    """CN-I5: a member seed must not equal the seed of ANY sample of this Fusion. WHY every
    member: a member call and a sample call of one route with one temperature and one seed send
    one gateway body and share one cached reply. The url4 carries a param as text, so the text
    is compared (a bool is never a seed)."""
    seeded = [
        (position, model, model.params["seed"])
        for position, model in enumerate(models, 1)
        if "seed" in model.params and not isinstance(model.params["seed"], bool)
    ]
    if not seeded:
        return  # WHY: most members set no seed; skip the up to 1024 hashes
    samples = {
        str(consistency_seed(k, j)): (k, j)
        for k in range(1, len(models) + 1)
        for j in range(1, n + 1)
    }
    for position, model, seed in seeded:
        hit = samples.get(str(seed))
        if hit is not None:
            raise ValueError(
                f"member {position} ({model.name!r}) sets seed={seed}, which is the seed of "
                f"consistency sample {hit[1]} of member {hit[0]}; choose another seed"
            )


def _signals_repr(declared: Mapping[str, SignalSource]) -> str:
    return "{" + ", ".join(f"{name!r}: {source!r}" for name, source in declared.items()) + "}"


def _quorum(value: object, member_count: int) -> int | Literal["all"]:
    if value == "all":
        return "all"
    if type(value) is not int:
        raise TypeError("Fusion quorum must be an integer or 'all'")
    if value < 0 or value > member_count:
        raise ValueError("Fusion quorum must be between zero and the member count")
    return value


def _synthesizer(value: object, members: tuple[Recipe, ...]) -> Recipe | Reducer:
    if isinstance(value, Reducer):
        if value._compiles_to_combine() and len(members) > _MAX_REDUCER_MEMBERS:
            raise ValueError(
                f"a reducer Fusion supports at most {_MAX_REDUCER_MEMBERS} members, "
                f"not {len(members)}"
            )
        value._check_members(len(members))
        return value
    return _recipe(value, "Fusion synthesizer")


def _members(values: object) -> tuple[Recipe, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("Fusion members must be an ordered sequence of model routes or Recipes")
    selected = tuple(_recipe(value, "Fusion member", allow_optional=True) for value in values)
    if not selected:
        raise ValueError("a Fusion requires at least one member")
    return selected


__all__ = ["Fusion"]
