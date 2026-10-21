"""Contract tests for the Fusion regression lane's golden models (OME-1289 E4a, FR#13 support).

DEFAULT lane: no docker, no subprocesses, no key. They pin what the GSM8K Fusion lane
(``test_fusion_replay.py``) stands on, so a mistake in the models or in the replay checks
shows up now and not after the user's paid recording:

- ``FusionLaneSpec`` builds the two recorded shapes;
- ``FusionGolden`` validates on read, and ``outcome()`` maps to a ``GoldenReport`` so that the five
  locks of ``compare_outcome`` run unchanged;
- ``body_digests`` and ``assert_fusion_replay`` hold a replay to the recorded outputs and requests.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest
from harness.fusion_golden import (
    CHECK_PROMPT,
    FUSION_GOLDEN_SCHEMA,
    RECIPES,
    FusionGolden,
    FusionLaneSpec,
    assert_fusion_replay,
    body_digests,
)
from harness.goldens import GoldenReport
from pydantic import ValidationError

import screamingface as sf

_MODEL = "openrouter/prov/model-x"
_SHA = hashlib.sha256(b"rendered expression").hexdigest()


def _spec_doc() -> dict[str, Any]:
    return {"model": _MODEL, "samples": 3, "temperature": 0.7}


def _digest(body: dict[str, Any]) -> str:
    text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lock_doc(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "expression_sha": _SHA,
        "final_score": "0.5",
        "case_count": 2,
        "gradeable_count": 1,
        "case_statuses": {"1": "scored", "2": "failed"},
        "case_failures": {"2": [{"stage": "candidate", "code": "upstream_error"}]},
        "case_outputs": {"1": "so 42", "2": None},
        "request_bodies": sorted([_digest({"a": 1}), _digest({"b": 2})]),
    }
    document.update(overrides)
    return document


def _golden_doc(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": FUSION_GOLDEN_SCHEMA,
        "lane": "inspect-gsm8k-fusion",
        "board": "inspect-gsm8k",
        "revision": "rev-1",
        "limit": 2,
        "candidate": _spec_doc(),
        "recipes": {recipe: _lock_doc() for recipe in RECIPES},
    }
    document.update(overrides)
    return document


# -- FusionLaneSpec -----------------------------------------------------------------


def test_build_uses_seeded_samples_and_the_recipe_synthesizer() -> None:
    spec = FusionLaneSpec.model_validate(_spec_doc())

    model = spec.build("model_synthesizer")
    recipe = spec.build("recipe_synthesizer")

    assert isinstance(model, sf.Pipeline) and isinstance(recipe, sf.Pipeline)
    for chain in (model, recipe):
        fanout = chain.steps[0]
        assert isinstance(fanout, sf.Fanout)
        members = [member for member in fanout.members if isinstance(member, sf.Model)]
        assert [member.params for member in members] == [
            {"temperature": 0.7, "seed": seed} for seed in range(3)
        ]
    assert model.steps[1:] == (sf.Synthesize(sf.Model(_MODEL)),)
    writer = recipe.steps[1]
    assert isinstance(writer, sf.Synthesize)
    synthesizer = writer.model
    assert isinstance(synthesizer, sf.Pipeline)
    assert list(synthesizer.steps) == [sf.Model(_MODEL), sf.Model(_MODEL, prompt=CHECK_PROMPT)]


# -- body digests and the replay check ----------------------------------------


def _record(body: dict[str, Any]) -> dict[str, Any]:
    return {"request_body": body, "status": 200, "cache_header": "HIT"}


def test_body_digests_keep_key_order_and_count_duplicates() -> None:
    ab = _record({"b": 1, "a": 2})
    ba = _record({"a": 2, "b": 1})

    assert body_digests([ab]) != body_digests([ba])
    assert len(body_digests([ab, ab])) == 2
    assert body_digests([ab, ba]) == tuple(sorted(body_digests([ab]) + body_digests([ba])))
    assert body_digests([ab]) == (_digest({"b": 1, "a": 2}),)
    assert body_digests([_record({"t": "é"})]) == (_digest({"t": "é"}),)


def _cases(outputs: dict[str, str | None]) -> list[Any]:
    return [SimpleNamespace(case_id=case_id, output=text) for case_id, text in outputs.items()]


def test_assert_fusion_replay_names_an_output_or_body_drift() -> None:
    lock = FusionGolden.model_validate(_golden_doc()).recipes["model_synthesizer"]
    same = body_digests([_record({"a": 1}), _record({"b": 2})])

    assert_fusion_replay(lock, _cases({"1": "so 42", "2": None}), same)
    with pytest.raises(AssertionError, match=r"case '1'.*'so 42'.*'so 41'"):
        assert_fusion_replay(lock, _cases({"1": "so 41", "2": None}), same)
    with pytest.raises(AssertionError, match="request bodies drifted: 1 missing, 1 new"):
        assert_fusion_replay(
            lock, _cases({"1": "so 42", "2": None}), body_digests([_record({"a": 1}), _record({})])
        )
    with pytest.raises(AssertionError, match="request bodies drifted: 1 missing, 0 new"):
        assert_fusion_replay(lock, _cases({"1": "so 42", "2": None}), same[:1])
    with pytest.raises(AssertionError, match="request bodies drifted: 0 missing, 1 new"):
        assert_fusion_replay(lock, _cases({"1": "so 42", "2": None}), (*same, same[0]))


# -- FusionGolden --------------------------------------------------------------------


def test_golden_validates_and_maps_each_recipe_to_a_golden_report() -> None:
    golden = FusionGolden.model_validate(_golden_doc())

    for recipe in RECIPES:
        outcome = golden.outcome(recipe)
        assert isinstance(outcome, GoldenReport)
        assert outcome.kind == "model"
        assert outcome.models == ()
        assert (outcome.board, outcome.revision, outcome.limit) == ("inspect-gsm8k", "rev-1", 2)
        assert outcome.expression_sha == _SHA
        assert (outcome.final_score, outcome.case_count, outcome.gradeable_count) == ("0.5", 2, 1)
        assert outcome.case_statuses == {"1": "scored", "2": "failed"}


def _without(recipe: str) -> dict[str, Any]:
    return {key: _lock_doc() for key in RECIPES if key != recipe}


@pytest.mark.parametrize(
    "overrides",
    [
        {"recipes": _without("recipe_synthesizer")},  # a recipe is missing
        {"recipes": {r: _lock_doc(case_outputs={"1": "so 42"}) for r in RECIPES}},
        {"recipes": {r: _lock_doc(gradeable_count=2) for r in RECIPES}},
        {"lane": "inspect-gsm8k-vote"},  # another lane
    ],
    ids=[
        "missing recipe",
        "outputs keys differ from statuses keys",
        "counters disagree",
        "another lane",
    ],
)
def test_golden_validates_and_refuses_bad_shapes(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        FusionGolden.model_validate(_golden_doc(**overrides))
