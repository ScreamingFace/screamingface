"""The paid button's `scope` choice — which Benchmarks one press runs.

Mental model: the press's shopping list. The live Engine lists every Benchmark it
serves; the scope word decides which of them go in the basket. `all` takes the whole
shelf, `imported` only the inspect evals copied into ScreamingFace, `hand-built` only the
Benchmarks we wrote in the Engine. Picking a cheap scope is how a press after an inspect
import skips the pro-tier Judges of the rubric Benchmarks.
"""

from __future__ import annotations

from typing import Final

#: Set by the workflow's `scope` input and the just recipe's `scope` argument.
SCOPE_ENV: Final = "SCREAMINGFACE_PAID_SCOPE"

ALL: Final = "all"

#: Each scope word → the Benchmark origins it must cover. `all` names both known kinds
#: so an empty kind is caught, but it filters nothing (see `pick_shelf`).
ORIGINS_BY_SCOPE: Final[dict[str, frozenset[str]]] = {
    ALL: frozenset({"inspect_evals", "screamingface"}),
    "imported": frozenset({"inspect_evals"}),
    "hand-built": frozenset({"screamingface"}),
}

#: Origin → the word a person uses for it, so a problem line reads like the button.
_KIND_NAMES: Final[dict[str, str]] = {
    "inspect_evals": "imported",
    "screamingface": "hand-built",
}

#: Why a kind can be empty, said where the owner reads the failure.
_EMPTY_KIND_HINTS: Final[dict[str, str]] = {
    "inspect_evals": "was the engine's venv synced with --extra benchmarks?",
    "screamingface": "the engine's built-in Benchmarks should always be listed",
}


class UnknownScopeError(ValueError):
    """The scope word is none of the defined ones."""


def resolve_scope(raw: str | None) -> str:
    """Check the button's scope word; unset or empty means `all`.

    Raises:
        UnknownScopeError: for any other word, naming the allowed ones, because a typo
            would otherwise pick zero Benchmarks and pass green.
    """
    scope: str = raw or ALL
    if scope not in ORIGINS_BY_SCOPE:
        allowed: str = ", ".join(ORIGINS_BY_SCOPE)
        raise UnknownScopeError(f"unknown paid smoke scope {scope!r}; use one of: {allowed}")
    return scope


def pick_shelf(listed: list[tuple[str, str]], scope: str) -> tuple[list[str], list[str]]:
    """Choose the Benchmarks this press runs, and say which picked kind listed none.

    Worked example: the Engine lists [(inspect-gsm8k, inspect_evals), (draco,
    screamingface)]. `imported` picks [inspect-gsm8k]; `all` picks both. If the Engine
    listed only draco, `all` still picks [draco] but reports the imported kind as
    missing, so the press fails instead of passing on the hand-built ones alone.

    WHY `all` filters nothing: a Benchmark of a kind added later must still run, never
    drop out of every scope without anyone noticing.

    Args:
        listed: (Benchmark id, origin) pairs in the Engine's listing order.
        scope: a word already checked by `resolve_scope`.

    Returns:
        The picked ids in listing order, and one problem line per picked kind with zero
        Benchmarks listed (empty when every kind is present).
    """
    origins: frozenset[str] = ORIGINS_BY_SCOPE[scope]
    picked: list[str] = [
        benchmark for benchmark, origin in listed if scope == ALL or origin in origins
    ]
    present: set[str] = {origin for _, origin in listed}
    problems: list[str] = [
        f"the live engine lists no {_KIND_NAMES[origin]} Benchmarks (origin={origin!r}) — "
        f"{_EMPTY_KIND_HINTS[origin]}"
        for origin in sorted(origins - present)
    ]
    return picked, problems
