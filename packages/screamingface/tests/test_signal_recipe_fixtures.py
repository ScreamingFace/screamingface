"""Drift guard for the E4b part 3 signal recipe fixtures (recipes PRD RC-1, RC-D1).

FEATURE: the Engine runs ``combine_contract/recipe_*.url4`` verbatim. When the SDK compile of a
signal recipe changes, this test fails until the fixture is written again with
``write_signal_recipe_fixture``, so the Engine test always runs the bytes that the SDK compiles
today. The part 1 fixtures are pinned to the bytes of the base commit (RC-D1).
"""

from __future__ import annotations

import hashlib

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, requires_engine_app
from _combine_recipes import RECIPES, compile_recipe
from _signal_recipes import SIGNAL_RECIPES, compile_signal_recipe
from test_pick_output_url4_fixtures import BUILDERS as PICK_OUTPUT_BUILDERS

# SHA-256 of each part 1 recipe fixture at base 0f4b9e292
# (git show 0f4b9e292:<path> | shasum -a 256). The oracle is the base commit, not today's
# compiler. Never update these values, except S10 and S11 max (the judge-template@2 bytes of
# unit 7b, overview §4.3) and S5, S5 pick output and S7 (a field pick reads a signal since 7d-1,
# overview §4 change 4: S5 now equals S8).
_PART1_FIXTURE_SHA256: dict[str, str] = {
    "recipe_s1.url4": "acf8c07b98c0bb3d0e1bc92e97ceaf552107b656b68b59e01f2f662fe1e27097",
    "recipe_s10.url4": "772d7f30080d877c9e53e2678b8d7d99bffb05f7caa48fe448236e6db660fef2",
    "recipe_s11_max.url4": "3dc99ebe14dee3e15dedd88e0873e40d548b9a2ff94e504e4eaa07162f98f19b",
    "recipe_s2.url4": "ecb1a2a974974f0a47a5947f60dec7845cf5393781bab9a22c1ff7700db5508c",
    "recipe_s3.url4": "cd41189b501ce7f4729abe71f044dd6e6dbb7f34614fe2d0d50c7188176e772d",
    "recipe_s4.url4": "192d37444364b4a8c72e71d75fb0a313860943a940033c8e009ba663b76a4988",
    "recipe_s4_median.url4": "063c205c0cef0bfa82aaa1540102a5b13b8ace11af1a32671cb8e0140880724f",
    "recipe_s5.url4": "ea786d01e5a922c68f5a679c2437c2b779239bb4cfba581e983709ce42e87e2a",
    "recipe_s5_pick_output.url4": (
        "57ca02ae94ed458f578b253924fc6847a2fa3d5e466551032ebeda4d5188a7d9"
    ),
    "recipe_s7.url4": "95fe7267a1e3aae60256c80d4ec702ba1569c0789ffdaa25abbeeac1552d1cd3",
    "recipe_s8.url4": "ea786d01e5a922c68f5a679c2437c2b779239bb4cfba581e983709ce42e87e2a",
    "recipe_s8_pick_output.url4": (
        "57ca02ae94ed458f578b253924fc6847a2fa3d5e466551032ebeda4d5188a7d9"
    ),
    "recipe_s9.url4": "70876d8b77c3f428034535890e97ae4f7f45decbc783355b5b52a5ad6aaf4566",
}
_SIGNAL_FIXTURES = {
    "recipe_s12.url4",
    "recipe_s13.url4",
    "recipe_s14.url4",
    "recipe_s15.url4",
    "recipe_s16.url4",
}


def _sdk_compile(name: str) -> str:
    # The part 1 builders live in two registries (recipes, and the Pick output pair).
    return compile_recipe(name) if name in RECIPES else PICK_OUTPUT_BUILDERS[name]()


@requires_engine_app
@pytest.mark.parametrize("name", sorted(_PART1_FIXTURE_SHA256))
def test_recipes_s1_to_s11_fixtures_are_unchanged(name: str) -> None:
    fixture = COMBINE_CONTRACT / name
    assert ENGINE_APP.exists()
    assert fixture.exists(), f"combine_contract/{name} is missing"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == _PART1_FIXTURE_SHA256[name]
    # the SDK compile of today is the same bytes (the fixture is the compile plus one "\n")
    assert (
        hashlib.sha256((_sdk_compile(name) + "\n").encode("utf-8")).hexdigest()
        == _PART1_FIXTURE_SHA256[name]
    )


@requires_engine_app
@pytest.mark.parametrize("name", sorted(SIGNAL_RECIPES))
def test_signal_recipe_fixtures_match_the_sdk_compile(name: str) -> None:
    # WHY the guard is split in two: skip only when the whole engine app is absent; a present
    # app with a missing fixture must FAIL, not skip.
    fixture = COMBINE_CONTRACT / name
    assert ENGINE_APP.exists()
    assert fixture.exists(), (
        f"combine_contract/{name} is missing - run write_signal_recipe_fixture({name!r})"
    )
    # WHY removesuffix: every fixture ends with exactly one newline.
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == compile_signal_recipe(name)


def test_signal_recipe_builders_cover_s12_to_s16() -> None:
    assert set(SIGNAL_RECIPES) == _SIGNAL_FIXTURES
