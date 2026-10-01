"""sf.samples(): N Models of one route differing in an integer seed (OME-1289, SM-2/6/7)."""

from __future__ import annotations

from typing import Any

import pytest
from _reducer_fixtures import FixtureVote, fixture_operators
from url4 import Expression, build

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface.url4 import _calls


def _seeds(models: tuple[sf.Model, ...]) -> list[object]:
    return [model.params["seed"] for model in models]


def test_samples_builds_n_models_with_seeds_0_to_n_minus_1() -> None:
    built = sf.samples("provider/a", 5)

    assert isinstance(built, tuple)
    assert all(isinstance(model, sf.Model) for model in built)
    assert _seeds(built) == [0, 1, 2, 3, 4]
    assert {model.model for model in built} == {"provider/a"}
    assert {model.prompt for model in built} == {None}
    # WHY ints: the gateway seed schema is `integer`, and a str seed fails preflight.
    assert all(type(seed) is int for seed in _seeds(built))


def test_samples_prompts_seeds_temperature_params_and_a_base_model() -> None:
    by_prompt = sf.samples("provider/a", 3, prompts=["en", "fr", "de"])
    assert [(model.prompt, model.params["seed"]) for model in by_prompt] == [
        ("en", 0),
        ("fr", 1),
        ("de", 2),
    ]

    assert _seeds(sf.samples("provider/a", 3, seeds=[10, 20, 30])) == [10, 20, 30]

    warm = sf.samples("provider/a", 2, temperature=0.7)
    assert [model.params["temperature"] for model in warm] == [0.7, 0.7]

    merged = sf.samples("provider/a", 2, params={"max_tokens": 64})
    assert [dict(model.params) for model in merged] == [
        {"max_tokens": 64, "seed": 0},
        {"max_tokens": 64, "seed": 1},
    ]

    base = sf.Model("provider/a", name="mine", prompt="P", params={"top_p": 0.9})
    inherited = sf.samples(base, 2, temperature=0.5)
    assert [list(model.params) for model in inherited] == [["top_p", "temperature", "seed"]] * 2
    assert {model.prompt for model in inherited} == {"P"}
    # WHY: the base name is not copied; each member keeps the route-derived name.
    assert {model.name for model in inherited} == {"a"}
    assert base.params == {"top_p": 0.9}


def test_samples_compile_to_member_calls_that_differ_only_in_the_seed() -> None:
    fusion = sf.Fusion(sf.samples("provider/a", 3), synthesizer=FixtureVote())
    compiled = compile_candidate(fusion, operators=fixture_operators())

    root = build(compiled.url4)
    assert isinstance(root, Expression)
    calls = _calls(root)
    assert [calls[f"model_{index}"].params for index in (1, 2, 3)] == [
        (("seed", "0"),),
        (("seed", "1"),),
        (("seed", "2"),),
    ]


@pytest.mark.parametrize(
    ("kwargs", "error", "message"),
    [
        ({"prompts": "abc"}, TypeError, "prompts"),
        ({"prompts": ["a", "b"]}, ValueError, "got 2 prompts for 3 samples"),
        ({"prompts": ["a", "b", "c", "d"]}, ValueError, "got 4 prompts for 3 samples"),
        ({"prompts": [""] * 3}, ValueError, "prompt"),
        ({"seeds": [1, 2]}, ValueError, "got 2 seeds for 3 samples"),
        ({"seeds": [1, 1, 2]}, ValueError, "seeds must be unique"),
        ({"seeds": "012"}, TypeError, "seeds"),
        ({"seeds": [1, 2, True]}, TypeError, "seeds"),
        ({"seeds": [1, 2, 3.0]}, TypeError, "seeds"),
        ({"seeds": 3}, TypeError, "seeds"),
        ({"params": {"seed": 1}}, ValueError, "samples() sets the seed; pass seeds= instead"),
        (
            {"temperature": 0.5, "params": {"temperature": 0.9}},
            ValueError,
            "pass temperature either as temperature= or in params, not both",
        ),
        ({"temperature": True}, TypeError, "temperature"),
        ({"temperature": "hot"}, TypeError, "temperature"),
        ({"temperature": float("nan")}, ValueError, "temperature"),
        ({"temperature": float("inf")}, ValueError, "temperature"),
    ],
)
def test_samples_prompts_and_seeds_length_and_uniqueness_checks(
    kwargs: dict[str, Any], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message.replace("(", r"\(").replace(")", r"\)")):
        sf.samples("provider/a", 3, **kwargs)


def test_samples_refuses_a_base_model_that_already_has_a_seed() -> None:
    base = sf.Model("provider/a", params={"seed": 5})

    with pytest.raises(ValueError, match=r"samples\(\) sets the seed; pass seeds= instead"):
        sf.samples(base, 2)


def test_samples_refuses_a_base_that_is_neither_a_route_nor_a_model() -> None:
    with pytest.raises(TypeError):
        sf.samples(3, 2)  # type: ignore[arg-type]


@pytest.mark.parametrize("n", [0, -1, 257])
def test_samples_n_bounds(n: int) -> None:
    with pytest.raises(ValueError, match=f"samples\\(\\) n must be between 1 and 256, not {n}"):
        sf.samples("provider/a", n)


def test_samples_n_bounds_accept_the_edges_and_reject_non_integers() -> None:
    assert len(sf.samples("provider/a", 1)) == 1
    assert len(sf.samples("provider/a", 256)) == 256
    with pytest.raises(TypeError):
        sf.samples("provider/a", True)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        sf.samples("provider/a", 2.0)  # type: ignore[arg-type]
