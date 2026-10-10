"""Plain data for code-pointer intents (url4 2.0, Spec B §5.3.12, contracts C2).

A code pointer names a handler mounted on a node. The compiler builds a
:class:`CodeCall` from the expansion (inputs, positional and named) and the
pointer's query tail; the node runs the handler with it. These types are the
shared vocabulary of that path, so they sit in the core layer: ``io``, ``dag``
and ``peer`` all import them, and this module imports only the standard library.

Layering: stdlib only, no ``url4`` import at all.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

type CodeValue = str | int | float | bool | None | list[CodeValue] | dict[str, CodeValue]
"""A JSON-shaped input value (Spec B §5.3.12)."""

type CodeWeight = float | Mapping[str, float]
"""A weight: a scalar, or a structured mapping (Spec B §4.1.1)."""


@dataclass(frozen=True, slots=True)
class CodeInput:
    """One expanded input of a code call, in source order."""

    position: int
    """1-based ``$N`` position, after expansion (Spec B §6.2, §5.3.12.4)."""

    name: str | None
    """``name``, ``name[i]`` or ``src[i]`` (Spec B §5.3.12.5); ``None`` if unnamed."""

    value: CodeValue

    weight: CodeWeight | None
    """``None`` when no weight was given. ``0.0`` IS a weight (Spec B §5.3.10.3)."""


@dataclass(frozen=True, slots=True)
class CodeCall:
    """What a handler receives: the pointer, its query tail, and its inputs."""

    pointer: str
    """The code path after ``$``-interpolation."""

    params: Mapping[str, str]
    """The pointer's query tail (contracts C7), read-only once built."""

    inputs: tuple[CodeInput, ...]
    """Source order; positions strictly increasing."""

    def __post_init__(self) -> None:
        # WHY: a handler must not alter the params the compiler fixed. The copy keeps
        # the caller's dict out of the call, and the proxy makes the view read-only.
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))

    def input(self, ref: int | str) -> CodeInput:
        """The input for ``ref``: ``2`` or ``"$2"`` by position, ``"member_1"`` by name.

        Raises ``KeyError`` when no input matches, and ``ValueError`` when a name is held
        by more than one input (use the position then). A ``bool`` is refused: it is an
        ``int`` in Python, but never a position.
        """
        if isinstance(ref, bool):
            raise TypeError(f"a code input is referenced by position or name, not {ref!r}")
        if isinstance(ref, int):
            return self._by_position(ref)
        text = ref[1:] if ref.startswith("$") else ref
        if text.isascii() and text.isdigit():
            return self._by_position(int(text))
        matches = [item for item in self.inputs if item.name == text]
        if not matches:
            raise KeyError(text)
        if len(matches) > 1:
            raise ValueError(
                f"input name {text!r} is ambiguous ({len(matches)} inputs); use its position"
            )
        return matches[0]

    def _by_position(self, position: int) -> CodeInput:
        for item in self.inputs:
            if item.position == position:
                return item
        raise KeyError(position)


type CodeHandler = Callable[[CodeCall], str | Awaitable[str]]
"""A mounted handler: sync or async, returning the text the intent resolves to."""


async def call_handler(handler: CodeHandler, call: CodeCall) -> object:
    """Run ``handler``, awaiting it when it returns an awaitable; return the raw result.

    The result is not type-checked here: the caller decides what a non-``str`` return
    means (Spec C §13.6, ``intent_error``).
    """
    result = handler(call)
    if inspect.isawaitable(result):
        return await result
    return result


__all__ = [
    "CodeCall",
    "CodeHandler",
    "CodeInput",
    "CodeValue",
    "CodeWeight",
    "call_handler",
]
