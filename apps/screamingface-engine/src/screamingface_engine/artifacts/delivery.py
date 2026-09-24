"""The inline/spill/refuse decision, shared by the run path and the sync spill path.

FEATURE: deliver large results in full instead of cutting them off at 1 MiB (OME-892);
FEATURE (unit 3, D9): a sync response over 512 KiB spills to the same artifact store.

WHY this is a module and not two copies of an `if`: the two delivery paths — the
Runner's terminal result frame (`runner.executor.build_result`) and the node tier's
sync response (`world.node_tier`) — must agree on the boundary to the byte. The order
of the two checks is the load-bearing part: the HARD cap is absolute and is checked
before the inline cap, so an inverted operator knob (`inline_cap > hard_cap`) cannot
let an over-hard-cap body through a path that only meant to keep small bodies inline.
A second copy of that ordering is how the paths silently diverge.

The decision is pure — byte count in, enum out. It imports neither half, so both the
run mode and the world may reach it (`artifacts` is a shared leaf of the layering gate).
"""

from __future__ import annotations

from enum import StrEnum


class ResultDelivery(StrEnum):
    """What a body of a given size must do on a capped delivery path."""

    INLINE = "inline"
    """Small enough to ride the response/frame unchanged."""

    SPILL = "spill"
    """Over the inline cap but within the hard cap, and a store exists to park it."""

    TOO_LARGE = "too_large"
    """Over the hard cap (or over the inline cap with nowhere to spill): must be refused."""


def allowed_result_bytes(inline_cap: int, hard_cap: int, *, spill_available: bool) -> int:
    """The largest body this path may deliver without failing.

    With a store, the hard cap is the ceiling and anything above the inline cap spills.
    Without one, there is no lossless place for a big body, so the effective ceiling is
    the smaller of the two knobs — the pre-spill truncation boundary, kept so a
    store-less engine fails loudly instead of cutting the body.
    """
    return hard_cap if spill_available else min(inline_cap, hard_cap)


def decide_result_delivery(
    size: int, *, inline_cap: int, hard_cap: int, spill_available: bool
) -> ResultDelivery:
    """Classify a body by size. Hard cap FIRST, then the inline threshold (T6).

    WHY the order is the contract and not an implementation detail: the hard cap is
    absolute. If the inline check ran first with an inverted `inline_cap > hard_cap`, a
    body under the huge inline cap would be treated as inline and sail past the ceiling
    — resurrecting the oversized-frame failure the hard cap exists to prevent. The
    ordering that makes the hard cap win is stated ONCE, here.
    """
    allowed = allowed_result_bytes(inline_cap, hard_cap, spill_available=spill_available)
    if size > allowed:
        return ResultDelivery.TOO_LARGE
    return ResultDelivery.INLINE if size <= inline_cap else ResultDelivery.SPILL


__all__ = ["ResultDelivery", "allowed_result_bytes", "decide_result_delivery"]
