"""The Runner's declared world, read from url4.json.

PORTED FROM url4.json (OME-1183). The rules:
  * `[aigateway]` is `world`.
  * Fixtures are dicts, not text. TOML fixtures were strings that had to parse first,
    so a variant was spelled `_MINIMAL.replace('"/a"', '"/b"')` -- a string edit standing
    in for a data edit. `_with()` makes that a data edit.
  * `[[aigateway.models]]` array-of-tables is `world.models`, a JSON array of objects.
  * The reserved-tables test changes MEANING, not just spelling: `[data]` and friends were
    never "reserved", they were `url4 serve`'s, and now they have a real home under
    `reads`. See test_a_serve_group_says_who_owns_it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine import job_env
from screamingface_engine.models.registry import EMPTY_MODEL_WORLD
from screamingface_engine.world_config import (
    AigatewaySection,
    ModelSpec,
    WorldConfig,
    WorldConfigError,
    load_config,
    parse_config,
    routes_for,
)

_MINIMAL: dict = {
    "world": {
        "base_url": "http://aigateway.test",
        "default_route": "/claude-haiku-4-5",
        "models": ["claude-haiku-4-5", "codex/gpt-5.5"],
    }
}


def _with(**world) -> dict:
    """`_MINIMAL` with `world` keys overridden -- the dict form of the old string edit."""
    return {"world": {**_MINIMAL["world"], **world}}


def _world(**keys) -> dict:
    """A bare world document from scratch, for the validation cases."""
    return {"world": keys}


def _parse(doc: dict, env: dict[str, str] | None = None) -> WorldConfig:
    # OME-859: `registry=EMPTY_MODEL_WORLD` keeps every assertion below meaning exactly what
    # it meant before the declared world moved into code — "the world is precisely this
    # document". The production default is `BUILTIN_MODEL_WORLD`, which would add 88 compiled
    # ids to each of these synthetic worlds; `test_model_seeds.py` and the drift guard cover
    # that world.
    return parse_config(doc, env or {}, registry=EMPTY_MODEL_WORLD)


def _section(doc: dict, env: dict[str, str] | None = None) -> AigatewaySection:
    """Parse and unwrap `world`, asserting it was declared."""
    section = _parse(doc, env).aigateway
    assert section is not None
    return section


def _write(tmp_path: Path, doc: dict, name: str = "url4.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# --- routes ---------------------------------------------------------------------


def test_routes_are_one_to_one_with_gateway_ids() -> None:
    haiku, codex = ModelSpec(id="claude-haiku-4-5"), ModelSpec(id="codex/gpt-5.5")

    assert routes_for((haiku, codex)) == {
        "/claude-haiku-4-5": haiku,
        "/codex/gpt-5.5": codex,
    }


def test_no_bare_alias_is_synthesized_for_a_prefixed_id() -> None:
    # The aliasing this replaces mislabeled `openrouter/openai/gpt-5.5` as `/openai/gpt-5.5`,
    # which reads as the OpenAI API while billing OpenRouter.
    routes = routes_for((ModelSpec(id="openrouter/openai/gpt-5.5"),))

    assert routes == {"/openrouter/openai/gpt-5.5": ModelSpec(id="openrouter/openai/gpt-5.5")}
    assert "/openai/gpt-5.5" not in routes
    assert "/gpt-5.5" not in routes


def test_multi_segment_ids_keep_every_segment() -> None:
    routes = routes_for((ModelSpec(id="openrouter/anthropic/claude-opus-4.8"),))

    assert "/openrouter/anthropic/claude-opus-4.8" in routes


# --- parsing --------------------------------------------------------------------


def test_parses_the_world_section() -> None:
    section = _section(_MINIMAL)

    assert section.base_url == "http://aigateway.test"
    assert section.models == (ModelSpec(id="claude-haiku-4-5"), ModelSpec(id="codex/gpt-5.5"))
    assert section.default_model == "claude-haiku-4-5"


def test_allow_outbound_defaults_to_permissive() -> None:
    # Today's behavior: the aigateway world is a Url4Node, which fetches absolute URLs.
    # Declaring the knob must not silently tighten it.
    assert _section(_MINIMAL).allow_outbound is True


def test_allow_outbound_can_be_declared_false() -> None:
    assert _section(_with(allow_outbound=False)).allow_outbound is False


def test_default_route_accepts_the_bare_id_spelling() -> None:
    section = _section(_with(default_route="claude-haiku-4-5"))

    assert section.default_model == "claude-haiku-4-5"


def test_absent_world_section_is_a_valid_tokenless_world() -> None:
    assert parse_config({}, {}).aigateway is None


# --- validation -----------------------------------------------------------------


def test_default_route_must_be_a_declared_model() -> None:
    with pytest.raises(WorldConfigError, match="not a declared model"):
        _parse(_with(default_route="/claude-opus-4-8"))


def test_empty_models_list_is_rejected() -> None:
    with pytest.raises(WorldConfigError, match="at least one model"):
        _parse(_world(default_route="/x", models=[]))


def test_model_id_may_not_start_with_a_slash() -> None:
    with pytest.raises(WorldConfigError, match="must not start with"):
        _parse(_world(default_route="/x", models=["/x"]))


def test_empty_model_id_is_rejected() -> None:
    with pytest.raises(WorldConfigError, match="empty"):
        _parse(_world(default_route="/x", models=["x", ""]))


def test_duplicate_model_ids_are_rejected() -> None:
    with pytest.raises(WorldConfigError, match="duplicate"):
        _parse(_world(default_route="/x", models=["x", "x"]))


def test_unknown_key_in_the_world_section_is_rejected() -> None:
    with pytest.raises(WorldConfigError, match="unknown"):
        _parse(_with(modles=[]))


def test_a_serve_group_says_who_owns_it() -> None:
    # PORTED, and the meaning changed. Under TOML these were `_RESERVED_TABLES`: declared by
    # the shared format, not parsed by the Runner, so the only honest thing was to refuse
    # them as "not supported yet". They are not reserved any more -- `reads` belongs to
    # `url4 serve`, whose catalog declares it -- so the message names the owner instead.
    with pytest.raises(WorldConfigError, match="belongs to `url4 serve`"):
        _parse({**_MINIMAL, "reads": {"data": {"/corpus": {"value": "x"}}}})


def test_unknown_top_level_group_is_rejected() -> None:
    with pytest.raises(WorldConfigError, match="unknown"):
        _parse({**_MINIMAL, "nonsense": {"x": 1}})


def test_the_old_aigateway_spelling_is_now_unknown() -> None:
    # The rename must be loud. Silently accepting `aigateway` would leave a half-migrated
    # file running and the migration unfinished.
    with pytest.raises(WorldConfigError, match="unknown"):
        _parse({"aigateway": _MINIMAL["world"]})


def test_a_sibling_catalog_group_is_tolerated() -> None:
    # This module reads `world` only. The other eleven groups in engine-node.schema.json
    # belong to the Settings layer and must load without complaint.
    assert _parse({**_MINIMAL, "runs": {}, "worker": {}}).aigateway is not None


def test_models_must_be_an_array() -> None:
    with pytest.raises(WorldConfigError, match="array"):
        _parse(_world(default_route="/x", models="x"))


# --- per-route capability objects -----------------------------------------------

_OBJECTS: dict = {
    "world": {
        "default_route": "/plain",
        "models": [{"id": "plain", "web_search": False}, {"id": "searcher"}],
    }
}


def test_a_route_declared_as_an_object_carries_its_capabilities() -> None:
    assert _section(_OBJECTS).models == (
        ModelSpec(id="plain", web_search=False),
        ModelSpec(id="searcher"),
    )


def test_web_search_stays_off_only_when_a_route_opts_out_explicitly() -> None:
    # `web_search` defaults to true, so a route that must not search has to say so with an
    # explicit `"web_search": false` — supplying a Tavily key must not retroactively turn it on.
    assert _section(_OBJECTS).models[0].web_search is False


def test_a_bare_id_string_is_shorthand_for_a_route_that_searches_by_default() -> None:
    assert _section(_MINIMAL).models[0] == ModelSpec(id="claude-haiku-4-5")


def test_the_two_spellings_may_be_mixed() -> None:
    section = _section(_world(default_route="/a", models=["a", {"id": "b"}]))

    assert section.models == (ModelSpec(id="a"), ModelSpec(id="b"))


def test_a_route_object_without_an_id_is_rejected() -> None:
    with pytest.raises(WorldConfigError, match="missing its `id`"):
        _parse(_world(default_route="/a", models=[{"web_search": True}]))


def test_unknown_key_on_a_route_object_is_rejected() -> None:
    # A typo'd capability must fail loudly, not read as "declared nothing".
    with pytest.raises(WorldConfigError, match="unknown key"):
        _parse(_world(default_route="/a", models=[{"id": "a", "web_tool": True}]))


def test_non_boolean_web_search_is_rejected() -> None:
    with pytest.raises(WorldConfigError, match="web_search must be a boolean"):
        _parse(_world(default_route="/a", models=[{"id": "a", "web_search": "yes"}]))


def test_a_route_entry_of_the_wrong_type_is_rejected() -> None:
    with pytest.raises(WorldConfigError, match="object or an id string"):
        _parse(_world(default_route="/a", models=[1]))


def test_duplicate_ids_are_rejected_across_both_spellings() -> None:
    with pytest.raises(WorldConfigError, match="duplicate"):
        _parse(_world(default_route="/a", models=["a", {"id": "a"}]))


# --- env overrides --------------------------------------------------------------


def test_env_overrides_the_declared_base_url() -> None:
    section = _section(_MINIMAL, {job_env.AIGATEWAY_BASE_URL: "http://override.test"})

    assert section.base_url == "http://override.test"


def test_env_overrides_the_default_model_when_it_is_declared() -> None:
    section = _section(_MINIMAL, {job_env.AIGATEWAY_MODEL: "codex/gpt-5.5"})

    assert section.default_model == "codex/gpt-5.5"


def test_env_default_model_must_still_be_declared() -> None:
    with pytest.raises(WorldConfigError, match="not a declared model"):
        _parse(_MINIMAL, {job_env.AIGATEWAY_MODEL: "not-declared"})


# --- loading --------------------------------------------------------------------


def test_load_config_reads_the_declared_path(tmp_path: Path) -> None:
    path = _write(tmp_path, _MINIMAL)

    # OME-859: EMPTY_MODEL_WORLD for the same reason as `_parse` — this asserts that the FILE
    # at the declared path is what got read, so the compiled world must not contribute to it.
    section = load_config({"URL4_RUNNER_CONFIG": str(path)}, registry=EMPTY_MODEL_WORLD).aigateway

    assert section is not None
    assert section.models == (ModelSpec(id="claude-haiku-4-5"), ModelSpec(id="codex/gpt-5.5"))


def test_missing_config_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(WorldConfigError, match="cannot read"):
        load_config({"URL4_RUNNER_CONFIG": str(tmp_path / "absent.json")})


def test_malformed_json_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "url4.json"
    path.write_text('{"world"\n', encoding="utf-8")

    with pytest.raises(WorldConfigError, match="cannot read"):
        load_config({"URL4_RUNNER_CONFIG": str(path)})


def test_top_level_array_is_rejected_in_json_vocabulary(tmp_path: Path) -> None:
    path = tmp_path / "url4.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(WorldConfigError, match="must be a JSON object, got array"):
        load_config({"URL4_RUNNER_CONFIG": str(path)})
