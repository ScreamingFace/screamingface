"""The execution axis of :func:`url4.src`: its typed keywords as ordered annotation pairs.

:mod:`url4.core.builders` appends the ``annotations=`` pairs after these, so a typed keyword
always precedes an extension key in the rendered ``;`` chain, and then places the C19 mark
(:func:`url4.core.at_most_one.with_mark`).
"""

from __future__ import annotations

from url4.core._annotations import checked_retries, checked_timeout

# WHY: the renderer owns the canonical number form; a builder must not drift from it.
from url4.core._render_values import format_number
from url4.core.nodes import Params


def exec_annotations(
    mode: str | None,
    t: float | int | None,
    retry: int | None,
    accept: str | None,
    required: bool | None,
) -> Params:
    """The typed keys in their fixed order, then the guard."""
    typed = (
        ("mode", mode),
        ("t", None if t is None else _timeout_text(t)),
        ("retry", None if retry is None else _retry_text(retry)),
        ("accept", accept),
    )
    pairs: list[tuple[str, str | None]] = [(k, v) for k, v in typed if v is not None]
    if required is not None:
        pairs.append(("required" if required else "optional", None))
    return tuple(pairs)


def _timeout_text(t: float | int) -> str:
    return format_number(checked_timeout(t))


def _retry_text(retry: int) -> str:
    return str(checked_retries(retry))
