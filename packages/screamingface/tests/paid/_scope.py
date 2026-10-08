"""The paid button's `scope` choice — which Benchmarks one press runs.

Mental model: the press's shopping list. The live Engine lists every Benchmark it
serves; the scope word decides which of them go in the basket. `all` takes the whole
shelf, `imported` only the inspect evals copied into ScreamingFace, `hand-built` only the
Benchmarks we wrote in the Engine. Picking a cheap scope is how a press after an inspect
import skips the pro-tier Judges of the rubric Benchmarks.

The `benchmarks` field (OME-1522) is the short list that replaces the scope: when the
owner names Benchmark ids, exactly those go in the basket, whatever the scope says.
"""

from __future__ import annotations

from typing import Final

#: Set by the workflow's `scope` input and the just recipe's `scope` argument.
SCOPE_ENV: Final = "SCREAMINGFACE_PAID_SCOPE"

#: Set by the workflow's `benchmarks` input and the just recipe's `benchmarks` argument:
#: comma-separated Benchmark ids, e.g. "musique,inspect-gsm8k". Blank means unset.
NAMED_ENV: Final = "SCREAMINGFACE_PAID_BENCHMARKS"

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


def parse_named(raw: str | None) -> tuple[str, ...]:
    """Split the button's `benchmarks` field into Benchmark ids; blank means unset.

    Worked example: " musique, inspect-gsm8k ,musique" → ("musique", "inspect-gsm8k").
    Spaces are trimmed, empty pieces dropped (so " , ," is unset and `scope` decides),
    and a repeated id kept once in first-seen order, so it is never run or paid twice.
    """
    pieces: list[str] = [piece.strip() for piece in (raw or "").split(",")]
    return tuple(dict.fromkeys(piece for piece in pieces if piece))


def pick_shelf(
    listed: list[tuple[str, str]], scope: str, named: tuple[str, ...] = ()
) -> tuple[list[str], list[str]]:
    """Choose the Benchmarks this press runs, and say what is wrong with the choice.

    Worked example: the Engine lists [(inspect-gsm8k, inspect_evals), (draco,
    screamingface)]. `imported` picks [inspect-gsm8k]; `all` picks both. If the Engine
    listed only draco, `all` still picks [draco] but reports the imported kind as
    missing, so the press fails instead of passing on the hand-built ones alone.
    Naming ("draco",) picks [draco] under any scope; naming ("dracoo",) reports the
    unknown name with the valid ids, so the press fails before any paid call.

    WHY `all` filters nothing: a Benchmark of a kind added later must still run, never
    drop out of every scope without anyone noticing.

    Args:
        listed: (Benchmark id, origin) pairs in the Engine's listing order.
        scope: a word already checked by `resolve_scope`; ignored when `named` is given.
        named: Benchmark ids from `parse_named`; empty means the scope decides.

    Returns:
        The picked ids in listing order, and the problem lines that must fail the press
        before any spend (empty when the choice is sound).
    """
    if named:
        return _pick_named(listed, named)
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


def _pick_named(
    listed: list[tuple[str, str]], named: tuple[str, ...]
) -> tuple[list[str], list[str]]:
    """Pick exactly the named Benchmarks; any name the Engine does not list is a problem.

    WHY names replace the scope instead of intersecting with it: "draco under imported"
    would pick nothing, and an empty press is a boot paid for nothing.
    WHY no empty-kind check here: that check guards a scope, and naming one hand-built
    Benchmark on an Engine without the inspect extra is exactly what the owner asked for.
    """
    wanted: set[str] = set(named)
    picked: list[str] = [benchmark for benchmark, _ in listed if benchmark in wanted]
    known: set[str] = {benchmark for benchmark, _ in listed}
    unknown: list[str] = [name for name in named if name not in known]
    if not unknown:
        return picked, []
    # INVARIANT: a typo never runs green on fewer Benchmarks than were named; the line
    # lists every valid id (sorted, to spot the near-miss) so the next press is right.
    return picked, [
        f"the live engine lists no Benchmark named {', '.join(map(repr, unknown))} — "
        f"valid ids: {', '.join(sorted(known))}"
    ]
