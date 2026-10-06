"""The fetch-pin rules: what the enforcer does to one Hub fetch's arguments (OME-1460).

INVARIANT: a Hub fetch in a replay reads exactly the commit the declaration pins, and a
shuffle the eval makes without a seed is seeded from the declaration, never left random and
never added where the eval did not shuffle (spec R2, R3, D1).

These are pure functions: no network, no patching. test_case_sources.py proves the recorder
applies them to the real primitives.
"""

from __future__ import annotations

from typing import Any

import pytest

from screamingface_engine_inspect.fetch_pins import (
    FetchPinError,
    FetchPins,
    forced_hf_dataset_arguments,
    forced_revision,
    is_commit_sha,
)

#: gsm8k's real pin, as the eval passes it at inspect_evals 0.20.0.
_GSM8K_SHA: str = "cc7b047b6e5bb11b4f1af84efc572db110a51b3c"
_OTHER_SHA: str = "0" * 40
_PINS: FetchPins = FetchPins(source_pins={"openai/gsm8k": _GSM8K_SHA})


def test_is_commit_sha_accepts_only_forty_lowercase_hex() -> None:
    assert is_commit_sha(_GSM8K_SHA)
    assert not is_commit_sha("main")
    assert not is_commit_sha(_GSM8K_SHA.upper())
    assert not is_commit_sha(_GSM8K_SHA[:12])
    assert not is_commit_sha(None)


def test_a_missing_revision_becomes_the_pin() -> None:
    assert forced_revision(_PINS, "openai/gsm8k", None) == _GSM8K_SHA


def test_the_same_sha_passes_through() -> None:
    """gsm8k's eval already passes our pin: stage 2 is a no-op on all 28 rows today."""

    assert forced_revision(_PINS, "openai/gsm8k", _GSM8K_SHA) == _GSM8K_SHA


def test_a_branch_name_is_replaced_by_the_pin() -> None:
    """WHY replaced, not refused: a branch is not identity; only a commit is (F2)."""

    assert forced_revision(_PINS, "openai/gsm8k", "main") == _GSM8K_SHA


def test_a_different_sha_is_refused_naming_both() -> None:
    """F2: the eval's own pin wins, so the declaration must match it."""

    with pytest.raises(FetchPinError) as refused:
        forced_revision(_PINS, "openai/gsm8k", _OTHER_SHA)

    assert _GSM8K_SHA in str(refused.value)
    assert _OTHER_SHA in str(refused.value)
    assert "openai/gsm8k" in str(refused.value)


def test_a_repo_with_no_pin_is_refused_naming_the_repo() -> None:
    """F1: a fetch nobody pinned would read the Hub's moving HEAD at every build."""

    with pytest.raises(FetchPinError, match="allenai/ai2_arc"):
        forced_revision(_PINS, "allenai/ai2_arc", None)


def test_while_learning_the_revision_is_left_as_the_eval_passed_it() -> None:
    """The import's first run has no pins yet: it records what the eval fetches."""

    learning: FetchPins = FetchPins(source_pins=None)

    assert forced_revision(learning, "allenai/ai2_arc", None) is None
    assert forced_revision(learning, "allenai/ai2_arc", "main") == "main"


def test_shuffle_without_a_seed_gets_the_declared_seed() -> None:
    pins: FetchPins = FetchPins(source_pins=None, shuffle_seed=1234)

    forced: dict[str, Any] = forced_hf_dataset_arguments(
        pins, {"path": "tau/commonsense_qa", "shuffle": True}
    )

    assert forced["seed"] == 1234
    assert forced["shuffle"] is True


def test_a_seeded_upstream_shuffle_keeps_its_seed() -> None:
    """mmlu passes seed=42 itself: inspect's own order, untouched."""

    pins: FetchPins = FetchPins(source_pins=None, shuffle_seed=1234)

    forced: dict[str, Any] = forced_hf_dataset_arguments(
        pins, {"path": "cais/mmlu", "shuffle": True, "seed": 42}
    )

    assert forced["seed"] == 42


def test_no_shuffle_never_gains_a_seed() -> None:
    """D1: the enforcer seeds a shuffle the eval makes; it never adds one (aime, hellaswag)."""

    pins: FetchPins = FetchPins(source_pins=None, shuffle_seed=1234, choice_shuffle_seed=7)

    forced: dict[str, Any] = forced_hf_dataset_arguments(
        pins, {"path": "Rowan/hellaswag", "shuffle": False, "shuffle_choices": False}
    )

    assert "seed" not in forced
    assert forced["shuffle"] is False
    assert forced["shuffle_choices"] is False


def test_a_bare_choice_shuffle_becomes_the_int_seed() -> None:
    """lab_bench passes shuffle_choices=True: inspect takes an int there as the seed."""

    pins: FetchPins = FetchPins(source_pins=None, choice_shuffle_seed=7)

    forced: dict[str, Any] = forced_hf_dataset_arguments(
        pins, {"path": "futurehouse/lab-bench", "shuffle_choices": True}
    )

    # WHY `is not True` too: True is an int in Python, so == 7 alone could hide a bool.
    assert forced["shuffle_choices"] == 7
    assert forced["shuffle_choices"] is not True


def test_a_seeded_choice_shuffle_keeps_its_seed() -> None:
    pins: FetchPins = FetchPins(source_pins=None, choice_shuffle_seed=7)

    forced: dict[str, Any] = forced_hf_dataset_arguments(
        pins, {"path": "x/y", "shuffle_choices": 99}
    )

    assert forced["shuffle_choices"] == 99


def test_an_unseeded_shuffle_with_no_declared_seed_is_refused_by_name() -> None:
    """F6: refused before the double run, so a random order never reaches the digest."""

    with pytest.raises(FetchPinError, match=r"tau/commonsense_qa.*shuffle_seed"):
        forced_hf_dataset_arguments(
            FetchPins(source_pins=None), {"path": "tau/commonsense_qa", "shuffle": True}
        )


def test_an_unseeded_choice_shuffle_with_no_declared_seed_is_refused_by_name() -> None:
    with pytest.raises(FetchPinError, match=r"futurehouse/lab-bench.*choice_shuffle_seed"):
        forced_hf_dataset_arguments(
            FetchPins(source_pins=None), {"path": "futurehouse/lab-bench", "shuffle_choices": True}
        )


def test_hf_dataset_arguments_get_the_revision_rule_too() -> None:
    """The revision is forced at hf_dataset as well, because its own cache key reads it."""

    forced: dict[str, Any] = forced_hf_dataset_arguments(_PINS, {"path": "openai/gsm8k"})

    assert forced["revision"] == _GSM8K_SHA


def test_forcing_never_mutates_the_callers_arguments() -> None:
    arguments: dict[str, Any] = {"path": "openai/gsm8k", "shuffle": True}

    forced_hf_dataset_arguments(
        FetchPins(source_pins={"openai/gsm8k": _GSM8K_SHA}, shuffle_seed=1), arguments
    )

    assert arguments == {"path": "openai/gsm8k", "shuffle": True}
