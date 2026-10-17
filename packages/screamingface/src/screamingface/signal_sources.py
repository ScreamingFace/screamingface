"""Declared signal sources of a Fusion (E4b): Verbalized, Logprob, Entropy, Sum and Consistency.

FEATURE: a Fusion names a number that each member answer carries (ans:Q1).
STORY: as a benchmark author, I declare signals={"conf": sf.Verbalized(r"Confidence: ([0-9]+)")}
and weight a vote with sf.signal("conf").
INVARIANT: a source compiles to one entry of the combine spec ``signals`` map, and ``_from_spec``
rebuilds an equal source from that entry (url4 → Python).
sf.Sum (E4b part 6, ans:Q1) is derived: it adds other declared names of the same Fusion.
``sf.Consistency`` (E4b part 7) is the one source whose entry also holds the step's ``match``: the
compile gives it to ``_entry(match)``, and ``_spec()`` is the entry without ``match``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Any, ClassVar, Literal, cast

from screamingface._regex_rule import check_signal_pattern
from screamingface._signals import MAX_DECLARED_SIGNALS, _finite_number, is_signal_name


class SignalSource(ABC):
    """Non-constructible umbrella type for the sources a Fusion declares in ``signals=``."""

    source: ClassVar[str]  # the wire word: "verbalized", "logprob", "entropy" or "consistency"

    @abstractmethod
    def _spec(self) -> dict[str, object]:
        """The combine-spec entry, for example {"source": "verbalized", "pattern": "..."}."""

    @classmethod
    @abstractmethod
    def _from_spec(cls, entry: Mapping[str, object]) -> SignalSource:
        """Rebuild an equal source from its spec entry; ValueError when this SDK did not write
        it."""

    def _python(self) -> str:
        return f"sf.{self!r}"


@dataclass(frozen=True, slots=True, init=False)
class Verbalized(SignalSource):
    """A number that the member states in its text, for example ``Confidence: 90`` (ans:Q9).

    The pattern has exactly one capture group (RE2 syntax). The Engine reads the last 65,536
    characters of the reply, takes the LAST match, strips spaces, and keeps the group only when it
    is an ASCII decimal number (``-3``, ``87.5``); else the value is missing. No scale is applied:
    ask every member for the same scale.
    """

    source: ClassVar[str] = "verbalized"
    pattern: str
    ignore_case: bool

    def __init__(self, pattern: str, *, ignore_case: bool = False) -> None:
        check_signal_pattern(pattern, ignore_case, "sf.Verbalized")
        object.__setattr__(self, "pattern", pattern)
        object.__setattr__(self, "ignore_case", ignore_case)

    def __repr__(self) -> str:
        extra = ", ignore_case=True" if self.ignore_case else ""
        return f"Verbalized({self.pattern!r}{extra})"

    def _spec(self) -> dict[str, object]:
        entry: dict[str, object] = {"source": "verbalized", "pattern": self.pattern}
        if self.ignore_case:
            entry["ignore_case"] = True  # WHY only when set: one spelling per declaration (DS-1)
        return entry

    @classmethod
    def _from_spec(cls, entry: Mapping[str, object]) -> Verbalized:
        if entry.get("source") != "verbalized" or not set(entry) <= {
            "source",
            "pattern",
            "ignore_case",
        }:
            raise ValueError(_CANNOT_REBUILD)
        if "ignore_case" in entry and entry["ignore_case"] is not True:
            raise ValueError(_CANNOT_REBUILD)  # this SDK writes ignore_case only as true
        pattern = entry.get("pattern")
        if not isinstance(pattern, str):
            raise ValueError(_CANNOT_REBUILD)
        return cls(pattern, ignore_case="ignore_case" in entry)


_LOGPROB_FORMS: tuple[str, ...] = ("mean", "sum", "prob")
_MIN_TOP_LOGPROBS = 1
_MAX_TOP_LOGPROBS = 20
_DEFAULT_TOP_LOGPROBS = 5  # owner decision Q8


@dataclass(frozen=True, slots=True, init=False)
class Logprob(SignalSource):
    """The token log-probability of each member's reply (OpenRouter models only in v1).

    With n reply tokens and s the sum of their log-probabilities: ``"sum"`` is s, ``"mean"`` is
    s / n, and ``"prob"`` is exp(s / n), a number in (0, 1]. Only ``"prob"`` can be a vote weight,
    because a weight must be greater than 0. ``"sum"`` favors short replies; ``"mean"`` and
    ``"prob"`` do not depend on the reply length.
    """

    source: ClassVar[str] = "logprob"
    form: Literal["mean", "sum", "prob"]

    def __init__(self, form: Literal["mean", "sum", "prob"]) -> None:
        if not isinstance(form, str) or form not in _LOGPROB_FORMS:
            raise ValueError(f"sf.Logprob form must be 'mean', 'sum' or 'prob', not {form!r}")
        object.__setattr__(self, "form", form)

    def __repr__(self) -> str:
        return f"Logprob({self.form!r})"

    def _spec(self) -> dict[str, object]:
        return {"source": "logprob", "form": self.form}

    @classmethod
    def _from_spec(cls, entry: Mapping[str, object]) -> Logprob:
        form = entry.get("form")
        if set(entry) != {"source", "form"} or entry.get("source") != "logprob":
            raise ValueError(_CANNOT_REBUILD)
        if not isinstance(form, str) or form not in _LOGPROB_FORMS:
            raise ValueError(_CANNOT_REBUILD)
        return cls(cast("Literal['mean', 'sum', 'prob']", form))


@dataclass(frozen=True, slots=True, init=False)
class Entropy(SignalSource):
    """The mean token entropy of each member's reply, in nats (OpenRouter models only in v1).

    Each member call asks for its ``top_logprobs`` most likely tokens at each position (1 to 20,
    default 5). A higher entropy means LESS confidence: read it with ``sf.Pick`` or ``sf.Rank`` and
    ``order="min"``. It cannot be a vote weight. A Fusion declares at most one ``sf.Entropy``.
    """

    source: ClassVar[str] = "entropy"
    top_logprobs: int

    def __init__(self, *, top_logprobs: int = _DEFAULT_TOP_LOGPROBS) -> None:
        if (
            isinstance(top_logprobs, bool)
            or not isinstance(top_logprobs, int)
            or not _MIN_TOP_LOGPROBS <= top_logprobs <= _MAX_TOP_LOGPROBS
        ):
            raise ValueError(
                f"sf.Entropy top_logprobs must be an int from {_MIN_TOP_LOGPROBS} to "
                f"{_MAX_TOP_LOGPROBS}, not {top_logprobs!r}"
            )
        object.__setattr__(self, "top_logprobs", top_logprobs)

    def __repr__(self) -> str:
        return f"Entropy(top_logprobs={self.top_logprobs!r})"

    def _spec(self) -> dict[str, object]:
        return {"source": "entropy", "top_logprobs": self.top_logprobs}

    @classmethod
    def _from_spec(cls, entry: Mapping[str, object]) -> Entropy:
        top_logprobs = entry.get("top_logprobs")
        if set(entry) != {"source", "top_logprobs"} or entry.get("source") != "entropy":
            raise ValueError(_CANNOT_REBUILD)
        if isinstance(top_logprobs, bool) or not isinstance(top_logprobs, int):
            raise ValueError(_CANNOT_REBUILD)
        return cls(top_logprobs=top_logprobs)


_MAX_SUM_TERMS = MAX_DECLARED_SIGNALS - 1  # a sum and its components share the 8 names (P4)


@dataclass(frozen=True, slots=True, init=False)
class Sum(SignalSource):
    """A fixed linear sum of other declared signals of the same member (E4b part 6, ans:Q1).

    ``sf.Sum({"sev_a": 0.5, "sev_b": 0.3})`` gives each member 0.5 x sev_a + 0.3 x sev_b. Each key
    is another name of the same Fusion ``signals=``, never another sf.Sum. The value is missing
    when a component is missing. The Engine adds the exact products and rounds once.
    """

    source: ClassVar[str] = "sum"
    coefficients: Mapping[str, float]  # MappingProxyType, sorted by name, float values

    def __init__(self, coefficients: Mapping[str, float]) -> None:
        object.__setattr__(self, "coefficients", MappingProxyType(_sum_terms(coefficients)))

    def __repr__(self) -> str:
        return f"Sum({dict(self.coefficients)!r})"

    def _spec(self) -> dict[str, object]:
        # WHY dict(): json.dumps cannot write a MappingProxyType (combine_spec.canonical_json).
        return {"source": "sum", "coefficients": dict(self.coefficients)}

    @classmethod
    def _from_spec(cls, entry: Mapping[str, object]) -> Sum:
        coefficients = entry.get("coefficients")
        if set(entry) != {"source", "coefficients"} or entry.get("source") != "sum":
            raise ValueError(_CANNOT_REBUILD)
        if not isinstance(coefficients, Mapping) or not all(
            _is_wire_term(name, value) for name, value in coefficients.items()
        ):
            raise ValueError(_CANNOT_REBUILD)
        try:
            return cls(coefficients)
        except (TypeError, ValueError) as exc:
            raise ValueError(_CANNOT_REBUILD) from exc

    __hash__: ClassVar[Any] = None  # WHY: it holds a mapping (the sf.Gate precedent, S/gate.py)


def _sum_terms(coefficients: object) -> dict[str, float]:
    """The checked terms of an sf.Sum, sorted by name, as floats (SA-1, SA-E1).

    The checks run in input order, so the first bad entry gives the error.
    """
    if not isinstance(coefficients, Mapping):
        raise TypeError(
            "sf.Sum takes a mapping of declared names to numbers, such as {'sev_a': 0.5}"
        )
    count = len(coefficients)
    if not 1 <= count <= _MAX_SUM_TERMS:
        raise ValueError(f"sf.Sum adds 1 to {_MAX_SUM_TERMS} declared names, not {count}")
    terms: dict[str, float] = {}
    for name, value in coefficients.items():
        checked = _sum_name(name)
        terms[checked] = _sum_coefficient(checked, value)
    return dict(sorted(terms.items()))


def _sum_name(name: object) -> str:
    if not isinstance(name, str):
        raise TypeError("sf.Sum names must be text")
    if not is_signal_name(name):
        raise ValueError(
            f"sf.Sum adds {name!r}, which is not a declared signal name; an E4a key such as "
            "cost_usd cannot be a sum component"
        )
    return name


def _sum_coefficient(name: str, value: object) -> float:
    number = _finite_number(
        value,
        f"sf.Sum coefficient of {name!r} must be a number",
        f"sf.Sum coefficient of {name!r} must be finite",
    )
    if number == 0:  # 0, 0.0 and -0.0
        raise ValueError(f"sf.Sum coefficient of {name!r} must not be zero")
    return number


def _is_wire_term(name: object, value: object) -> bool:
    """A JSON term this SDK could have written: a text name and a number that is not a bool."""
    return isinstance(name, str) and isinstance(value, int | float) and not isinstance(value, bool)


_MAX_CONSISTENCY_N = 32  # P2: a step of 1/32 in the fraction; 256 members x 32 is above the cap


@dataclass(frozen=True, slots=True, init=False)
class Consistency(SignalSource):
    """How often the member gives the same answer again (E4b part 7).

    Each member makes ``n`` more calls with distinct seeds at ``temperature``; its other
    params do not change. The value is the fraction of the successful samples whose answer,
    read with the step's own extract and normalize, equals the member's answer. A failed
    sample does not count; when every sample fails, the value is missing.
    """

    source: ClassVar[str] = "consistency"
    n: int
    temperature: float

    def __init__(self, n: int, *, temperature: float = 1.0) -> None:
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= _MAX_CONSISTENCY_N:
            raise ValueError(
                f"sf.Consistency n must be an int from 1 to {_MAX_CONSISTENCY_N}, not {n!r}"
            )
        object.__setattr__(self, "n", n)
        object.__setattr__(self, "temperature", _sample_temperature(temperature))

    def __repr__(self) -> str:
        return f"Consistency(n={self.n!r}, temperature={self.temperature!r})"

    def _spec(self) -> dict[str, object]:
        return {"source": "consistency", "n": self.n, "temperature": self.temperature}

    def _entry(self, match: Mapping[str, object]) -> dict[str, object]:
        """The full combine-spec entry: ``_spec()`` plus the step's pinned ``match`` (P3)."""
        return {**self._spec(), "match": dict(match)}

    @classmethod
    def _from_spec(cls, entry: Mapping[str, object]) -> Consistency:
        # WHY match is checked only for its keys: the recompile proves the step ids, because the
        # compile writes the step's own match and any other match changes the bytes (C5).
        n = entry.get("n")
        temperature = entry.get("temperature")
        match = entry.get("match")
        if (
            set(entry) != {"source", "n", "temperature", "match"}
            or entry.get("source") != "consistency"
        ):
            raise ValueError(_CANNOT_REBUILD)
        if isinstance(n, bool) or not isinstance(n, int):
            raise ValueError(_CANNOT_REBUILD)
        if isinstance(temperature, bool) or not isinstance(temperature, int | float):
            raise ValueError(_CANNOT_REBUILD)
        if not isinstance(match, Mapping) or set(match) != {"extract", "normalize"}:
            raise ValueError(_CANNOT_REBUILD)
        return cls(n, temperature=temperature)


def _sample_temperature(value: object) -> float:
    """The checked sf.Consistency temperature as a float; an int becomes a float, -0.0 becomes
    0.0."""
    number = math.nan
    if isinstance(value, int | float) and not isinstance(value, bool):
        with suppress(OverflowError):  # an int beyond the float range stays nan: refused
            number = float(value) + 0.0
    if not math.isfinite(number) or number < 0:
        raise ValueError(
            f"sf.Consistency temperature must be a finite number of at least 0, not {value!r}"
        )
    return number


def consistency_seed(k: int, j: int) -> int:
    """The seed of sample ``j`` (1..n) of member ``k`` (1-based): the first 31 bits of
    ``sha256(f"consistency:{k}:{j}")`` (erd §2, P5).

    WHY not ``sf.samples()`` seeds: they are 0..n-1 for every member, so two members of one
    route would share their samples. For k <= 256 and j <= 32 the seeds are all different and
    never below 256.
    """
    return int.from_bytes(sha256(f"consistency:{k}:{j}".encode()).digest()[:4], "big") >> 1


def consistency_source(declared: Mapping[str, SignalSource] | None) -> Consistency | None:
    """The one sf.Consistency of a declaration (CN-I1), else None."""
    return next((s for s in (declared or {}).values() if isinstance(s, Consistency)), None)


# The member params that a Logprob or Entropy declaration owns (P12, DS-D10, U4-D1).
INJECTED_PARAMS: frozenset[str] = frozenset({"logprobs", "top_logprobs"})


def injected_member_params(declared: Mapping[str, SignalSource] | None) -> dict[str, bool | int]:
    """The params a declaration adds to every member call: ``logprobs=True`` for any
    ``sf.Logprob`` or ``sf.Entropy``, then ``top_logprobs=k`` for the one ``sf.Entropy`` (DS-I2).
    Empty when the declaration needs no logprobs.

    INVARIANT (U4-D5, C2): ``logprobs`` is the first key, and ``top_logprobs`` never comes alone.
    """
    params: dict[str, bool | int] = {}
    for source in (declared or {}).values():
        if isinstance(source, Logprob | Entropy):
            params["logprobs"] = True
    for source in (declared or {}).values():
        if isinstance(source, Entropy):
            params["top_logprobs"] = source.top_logprobs
    return params


_CANNOT_REBUILD = "URL4 Candidate has a signals declaration this SDK version cannot rebuild"
# wire word -> class
_SOURCES: Mapping[str, type[SignalSource]] = MappingProxyType(
    {
        "verbalized": Verbalized,
        "logprob": Logprob,
        "entropy": Entropy,
        "sum": Sum,
        "consistency": Consistency,
    }
)


def declared_from_spec(entries: object) -> dict[str, SignalSource] | None:
    """The declaration of a decoded combine spec (its ``signals`` value), or None when absent."""
    if entries is None:
        return None
    if not isinstance(entries, Mapping) or not entries:
        raise ValueError(_CANNOT_REBUILD)
    declared: dict[str, SignalSource] = {}
    for name, entry in entries.items():
        source = entry.get("source") if isinstance(entry, Mapping) else None
        kind = _SOURCES.get(source) if isinstance(source, str) else None
        if not isinstance(name, str) or kind is None or not isinstance(entry, Mapping):
            raise ValueError(_CANNOT_REBUILD)
        try:
            declared[name] = kind._from_spec(entry)
        except (TypeError, ValueError) as exc:
            raise ValueError(_CANNOT_REBUILD) from exc
    return declared


def python_signals(declared: Mapping[str, SignalSource]) -> str:
    """``{'conf': sf.Verbalized('...')}``: the ``signals=`` text of ``Url4.to_python``."""
    return (
        "{" + ", ".join(f"{name!r}: {source._python()}" for name, source in declared.items()) + "}"
    )


__all__ = ["Consistency", "Entropy", "Logprob", "SignalSource", "Sum", "Verbalized"]
