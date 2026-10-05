"""Fetch pins: the declaration's Hub revisions and seeds, forced onto the eval's own fetches.

FEATURE: one Case Preparation path (OME-1460, spec R2, R3, D1). Every Imported Benchmark is
prepared by calling the eval's own task function; these rules make what that call fetches
the same at every build, without editing the eval.

Think of it as a customs officer who also stamps the visa the traveller forgot: each Hub
fetch is checked against the declaration's list of pinned repos, and a fetch that names no
commit leaves with the pinned one. Stages, in the order the recorder applies them to one
call:

    Stage 1 — revision: look the repo up in ``source_pins``. No pin → refused (F1). The
              eval passes a different 40-hex sha → refused, naming both (F2): the eval's own
              pin wins and the declaration must match it. No revision, or a branch or tag
              name → replaced by the pin, because only a commit is Benchmark identity.
    Stage 2 — row shuffle (``hf_dataset`` only): ``shuffle=True`` with no ``seed`` gets the
              declaration's ``shuffle_seed``; with none declared → refused (F6). A seeded
              call is left alone, and a call that does not shuffle never gains a seed.
    Stage 3 — choice shuffle (``hf_dataset`` only): ``shuffle_choices=True`` becomes the int
              ``choice_shuffle_seed`` (inspect reads an int there as the seed); an int or
              False is left alone.

Worked example: gsm8k calls ``hf_dataset("openai/gsm8k", revision="cc7b047b…")`` and the
declaration pins ``openai/gsm8k`` to ``cc7b047b…``, so stage 1 passes it through unchanged
(true of all 28 rows moving in OME-1460: the force is a no-op today, and the guarantee when
a future inspect_evals bump drops a pin). commonsense_qa calls ``hf_dataset(...,
shuffle=True)`` with no seed; its declaration says ``shuffle_seed=1234``, so stage 2 passes
``seed=1234`` and inspect's own shuffle produces one order at every build.

``source_pins=None`` means "learning": the import's first run does not know the pins yet, so
stage 1 passes the revision through and the recorder notes it; the importer then resolves
each to a commit and seals them. Stages 2 and 3 apply while learning too, because the seeds
come from the dev's command, not from the fetch.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_COMMIT_SHA: re.Pattern[str] = re.compile(r"[0-9a-f]{40}")


class FetchPinError(Exception):
    """A fetch the declaration does not pin, or pins differently: refused by name."""


@dataclass(frozen=True)
class FetchPins:
    """What the enforcer forces onto one replay's fetches.

    Attributes:
        source_pins: Hub repo id → 40-hex commit; None while the import's first run learns
            them (stage 1 then forces nothing).
        shuffle_seed: the seed for an ``hf_dataset`` row shuffle the eval makes without one.
        choice_shuffle_seed: the seed for a bare ``shuffle_choices=True``.
    """

    source_pins: Mapping[str, str] | None
    shuffle_seed: int | None = None
    choice_shuffle_seed: int | None = None


def is_commit_sha(value: Any) -> bool:
    """Whether a revision names one commit (40 lowercase hex), not a branch or a tag."""

    return isinstance(value, str) and _COMMIT_SHA.fullmatch(value) is not None


def forced_revision(pins: FetchPins, repo_id: str, revision: Any) -> Any:
    """Stage 1 — the revision this fetch must read: the pin, or a refusal.

    Args:
        pins: the replay's fetch pins.
        repo_id: the Hub repo the fetch names (``path`` or ``repo_id``).
        revision: what the eval passed; None for none.

    Returns:
        The pinned commit; while learning, ``revision`` unchanged.

    Raises:
        FetchPinError: no pin for the repo (F1), or the eval pins a different commit (F2).
    """

    if pins.source_pins is None:
        return revision
    pin: str | None = pins.source_pins.get(repo_id)
    if pin is None:
        raise FetchPinError(
            f"the eval fetches Hugging Face repo {repo_id} but the declaration pins no "
            f"revision for it — add {repo_id!r} to source_pins (re-import the Benchmark)"
        )
    if is_commit_sha(revision) and revision != pin:
        raise FetchPinError(
            f"the eval pins Hugging Face repo {repo_id} at {revision} but the declaration "
            f"pins {pin} — the eval's own pin wins; re-import the Benchmark"
        )
    return pin


def forced_hf_dataset_arguments(pins: FetchPins, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Stages 1 to 3 on one ``hf_dataset`` call's bound arguments; returns a new mapping.

    WHY the revision here too, not only at ``datasets.load_dataset``: ``hf_dataset`` keys its
    own disk cache on the revision and reads that cache back when the revision is None, so
    the pin must be in place before ``hf_dataset`` decides where to load from.

    Args:
        pins: the replay's fetch pins.
        arguments: the call's arguments, bound to ``hf_dataset``'s signature.

    Returns:
        A copy with the revision and seeds forced; ``arguments`` itself is never changed.

    Raises:
        FetchPinError: a stage 1 refusal, or a shuffle with no seed anywhere (F6).
    """

    forced: dict[str, Any] = dict(arguments)
    path: str = str(forced["path"])
    # Stage 1
    revision: Any = forced_revision(pins, path, forced.get("revision"))
    if revision is not None:
        forced["revision"] = revision
    # Stage 2 — INVARIANT: only a shuffle the eval asked for is seeded (D1).
    if forced.get("shuffle") is True and forced.get("seed") is None:
        forced["seed"] = _declared_seed(pins.shuffle_seed, path, "shuffle=True", "shuffle_seed")
    # Stage 3 — WHY `is True`: True is an int in Python, so an int check would take the bool
    # for a seed of 1.
    if forced.get("shuffle_choices") is True:
        forced["shuffle_choices"] = _declared_seed(
            pins.choice_shuffle_seed, path, "shuffle_choices=True", "choice_shuffle_seed"
        )
    return forced


def _declared_seed(seed: int | None, path: str, call: str, field: str) -> int:
    """The declaration's seed for an unseeded shuffle, or the F6 refusal naming both."""

    if seed is None:
        raise FetchPinError(
            f"the eval calls hf_dataset({path!r}, {call}) with no seed, so every replay "
            f"orders it differently — declare {field} (--{field.replace('_', '-')})"
        )
    return seed


__all__ = [
    "FetchPinError",
    "FetchPins",
    "forced_hf_dataset_arguments",
    "forced_revision",
    "is_commit_sha",
]
