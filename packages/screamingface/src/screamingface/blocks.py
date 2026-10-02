"""Block forms of the deterministic Fusion slot: Extract, Matches, Reduce (OME-1289 gap).

FEATURE: a researcher builds a reducer from named blocks and gets the same combine call as the
named form (block-api ans:Q1).
INVARIANT: v1 blocks use short operator names only (D-13); the catalog pins the version.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from screamingface._regex_rule import check_regex
from screamingface._signals import FIELD_PATH
from screamingface.reducer import _Step

type ExtractRule = Literal[
    "boxed",
    "last_number",
    "field",
    "regex",
    "last_line",
    "whole",
    "json",
    "benchmark",
    "inspect_number",
    "inspect_aime",
]
type NormalizeRule = Literal["numeric", "text", "set", "inspect_numeric", "identity"]

# rule -> (engine op name | None for benchmark, required args, optional args)
_RULES: Mapping[str, tuple[str | None, tuple[str, ...], tuple[str, ...]]] = MappingProxyType(
    {
        "boxed": ("boxed", (), ()),
        "last_number": ("last_number", (), ()),
        "field": ("json_field", ("path",), ()),
        "regex": ("regex", ("pattern",), ("group", "occurrence", "ignore_case")),
        "last_line": ("last_line", (), ()),
        "whole": ("whole", (), ()),
        "json": ("json_object", (), ()),
        "benchmark": (None, (), ()),
        "inspect_number": ("inspect_number", (), ()),
        "inspect_aime": ("inspect_aime", (), ()),
    }
)
_NORMALIZERS = ("numeric", "text", "set", "inspect_numeric", "identity")


@dataclass(frozen=True, slots=True, init=False)
class Extract:
    """How a member's answer is read: a rule, then an optional normalizer (block form)."""

    rule: ExtractRule
    normalize: NormalizeRule | None
    args: Mapping[str, object]

    def __init__(
        self, rule: ExtractRule, normalize: NormalizeRule | None = None, **args: object
    ) -> None:
        if not isinstance(rule, str):
            raise TypeError("sf.Extract rule must be text")
        if rule not in _RULES:
            raise ValueError(f"unknown sf.Extract rule {rule!r}; the rules are {', '.join(_RULES)}")
        _check_normalizer(rule, normalize)
        _check_args(rule, args)
        object.__setattr__(self, "rule", rule)
        object.__setattr__(self, "normalize", normalize)
        object.__setattr__(self, "args", MappingProxyType(dict(sorted(args.items()))))

    def __hash__(self) -> int:
        return hash((self.rule, self.normalize, tuple(sorted(self.args.items()))))

    def __repr__(self) -> str:
        parts = [repr(self.rule)]
        if self.normalize is not None:
            parts.append(f"normalize={self.normalize!r}")
        parts.extend(f"{name}={value!r}" for name, value in sorted(self.args.items()))
        return f"Extract({', '.join(parts)})"

    def _python(self) -> str:
        return "sf." + repr(self)

    def _steps(self) -> tuple[_Step, _Step | None]:
        """The unpinned extract step and the optional normalize step."""

        operator = _RULES[self.rule][0]
        if operator is None:
            raise ValueError("extract='benchmark' needs a benchmark")
        normalize = None if self.normalize is None else _Step(self.normalize)
        return _Step(operator, self.args), normalize


def _check_normalizer(rule: str, normalize: object) -> None:
    if normalize is None:
        return
    if not isinstance(normalize, str) or normalize not in _NORMALIZERS:
        raise ValueError(f"sf.Extract normalize must be one of {', '.join(_NORMALIZERS)}")
    if rule == "benchmark":
        raise ValueError(
            "extract='benchmark' takes the benchmark's own normalizer; "
            "v1 does not let a recipe change it"
        )


def _check_args(rule: str, args: Mapping[str, object]) -> None:
    _, required, optional = _RULES[rule]
    for name in required:
        if name not in args:
            raise ValueError(f"sf.Extract({rule!r}) needs {name!r}")
    for name, value in args.items():
        if name not in (*required, *optional):
            raise ValueError(f"sf.Extract({rule!r}) does not take {name!r}")
        _check_scalar(rule, name, value)
    if rule == "field" and FIELD_PATH.fullmatch(str(args["path"])) is None:
        raise ValueError("sf.Extract('field') path must be a JSON path like 'a', 'a.b' or 'a[0].b'")
    if rule == "regex":
        check_regex(args, "sf.Extract('regex')")


def _check_scalar(rule: str, name: str, value: object) -> None:
    is_scalar = value is None or isinstance(value, str | bool | int)
    if not is_scalar and not (isinstance(value, float) and math.isfinite(value)):
        raise TypeError(f"sf.Extract({rule!r}) {name!r} must be a JSON scalar")


@dataclass(frozen=True, slots=True)
class Matches:
    """A filter predicate: the member text matches a regex@1 pattern (RE2 on the Engine)."""

    pattern: str
    ignore_case: bool = False

    def __post_init__(self) -> None:
        check_regex(_matches_args(self), "sf.matches")

    def _python(self) -> str:
        flag = ", ignore_case=True" if self.ignore_case is True else ""
        return f"sf.matches({self.pattern!r}{flag})"


def _matches_args(value: Matches) -> Mapping[str, object]:
    """ignore_case enters the args only when set, so a default never reaches the check."""

    if value.ignore_case is False:
        return {"pattern": value.pattern}
    return {"pattern": value.pattern, "ignore_case": value.ignore_case}


def matches(pattern: str, *, ignore_case: bool = False) -> Matches:
    """A filter predicate: the member text matches the regex@1 rule (RE2 on the Engine)."""

    return Matches(pattern, ignore_case)


__all__: list[str] = []
