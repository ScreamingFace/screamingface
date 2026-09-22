from __future__ import annotations

from pathlib import Path

import pytest

from screamingface_engine import job_env
from screamingface_engine.world.config import (
    AigatewaySection,
    ModelSpec,
    WorldConfig,
    WorldConfigError,
    load_config,
    parse_config,
    routes_for,
)
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD

_MINIMAL = """
[aigateway]
base_url = "http://aigateway.test"
default_route = "/claude-haiku-4-5"
models = ["claude-haiku-4-5", "codex/gpt-5.5"]
"""


def _parse(toml_text: str, env: dict[str, str] | None = None) -> WorldConfig:
    # OME-859: `registry=EMPTY_MODEL_WORLD` keeps every assertion below meaning exactly what it
    # meant before the declared world moved into code — "the world is precisely this TOML text".
    # The production default is `BUILTIN_MODEL_WORLD`, which would add 88 compiled ids to each
    # of these synthetic worlds; `test_model_seeds.py` and the drift guard cover that world.
    return parse_config(_toml(toml_text), env or {}, registry=EMPTY_MODEL_WORLD)


def _section(toml_text: str, env: dict[str, str] | None = None) -> AigatewaySection:
    """Parse and unwrap `[aigateway]`, asserting it was declared."""
    section = _parse(toml_text, env).aigateway
    assert section is not None
    return section


def _toml(text: str) -> dict:
    import tomllib

    return tomllib.loads(text)


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


def test_parses_the_aigateway_table() -> None:
    section = _section(_MINIMAL)

    assert section.base_url == "http://aigateway.test"
    assert section.models == (ModelSpec(id="claude-haiku-4-5"), ModelSpec(id="codex/gpt-5.5"))
    assert section.default_model == "claude-haiku-4-5"


def test_allow_outbound_defaults_to_permissive() -> None:
    # Today's behavior: the aigateway world is a Url4Node, which fetches absolute URLs.
    # Declaring the knob must not silently tighten it.
    assert _section(_MINIMAL).allow_outbound is True


def test_allow_outbound_can_be_declared_false() -> None:
    assert _section(_MINIMAL + "allow_outbound = false\n").allow_outbound is False


def test_default_route_accepts_the_bare_id_spelling() -> None:
    section = _section(_MINIMAL.replace('"/claude-haiku-4-5"', '"claude-haiku-4-5"'))

    assert section.default_model == "claude-haiku-4-5"


def test_absent_aigateway_table_is_a_valid_tokenless_world() -> None:
    assert parse_config({}, {}).aigateway is None


# --- validation -----------------------------------------------------------------


def test_default_route_must_be_a_declared_model() -> None:
    with pytest.raises(WorldConfigError, match="not a declared model"):
        _parse(_MINIMAL.replace('"/claude-haiku-4-5"', '"/claude-opus-4-8"'))


def test_empty_models_list_is_rejected() -> None:
    with pytest.raises(WorldConfigError, match="at least one model"):
        _parse('[aigateway]\ndefault_route = "/x"\nmodels = []\n')


def test_model_id_may_not_start_with_a_slash() -> None:
    with pytest.raises(WorldConfigError, match="must not start with"):
        _parse('[aigateway]\ndefault_route = "/x"\nmodels = ["/x"]\n')


def test_empty_model_id_is_rejected() -> None:
    with pytest.raises(WorldConfigError, match="empty"):
        _parse('[aigateway]\ndefault_route = "/x"\nmodels = ["x", ""]\n')


def test_duplicate_model_ids_are_rejected() -> None:
    with pytest.raises(WorldConfigError, match="duplicate"):
        _parse('[aigateway]\ndefault_route = "/x"\nmodels = ["x", "x"]\n')


def test_unknown_key_in_the_aigateway_table_is_rejected() -> None:
    with pytest.raises(WorldConfigError, match="unknown"):
        _parse(_MINIMAL + "modles = []\n")


def test_reserved_tables_fail_loudly_rather_than_being_ignored() -> None:
    # `[data]`/`[commands]`/`[holdings]`/`[identities]` are reserved in the format but not
    # parsed yet — silently ignoring them would look like they worked.
    with pytest.raises(WorldConfigError, match="not supported yet"):
        _parse(_MINIMAL + '\n[data]\n"/corpus" = { value = "x" }\n')


def test_unknown_top_level_table_is_rejected() -> None:
    with pytest.raises(WorldConfigError, match="unknown"):
        _parse(_MINIMAL + "\n[nonsense]\nx = 1\n")


def test_models_must_be_a_list() -> None:
    with pytest.raises(WorldConfigError, match="list"):
        _parse('[aigateway]\ndefault_route = "/x"\nmodels = "x"\n')


# --- per-route capability tables ------------------------------------------------

_TABLES = """
[aigateway]
default_route = "/plain"

[[aigateway.models]]
id = "plain"
web_search = false

[[aigateway.models]]
id = "searcher"
"""


def test_a_route_declared_as_a_table_carries_its_capabilities() -> None:
    assert _section(_TABLES).models == (
        ModelSpec(id="plain", web_search=False),
        ModelSpec(id="searcher"),
    )


def test_web_search_stays_off_only_when_a_route_opts_out_explicitly() -> None:
    # `web_search` now defaults to true, so a route that must not search has to say so with an
    # explicit `web_search = false` — supplying a Tavily key must not retroactively turn it on.
    assert _section(_TABLES).models[0].web_search is False


def test_a_bare_id_string_is_shorthand_for_a_route_that_searches_by_default() -> None:
    assert _section(_MINIMAL).models[0] == ModelSpec(id="claude-haiku-4-5")


def test_the_two_spellings_may_be_mixed() -> None:
    section = _section('[aigateway]\ndefault_route = "/a"\nmodels = ["a", { id = "b" }]\n')

    assert section.models == (ModelSpec(id="a"), ModelSpec(id="b"))


def test_a_route_table_without_an_id_is_rejected() -> None:
    with pytest.raises(WorldConfigError, match="missing its `id`"):
        _parse('[aigateway]\ndefault_route = "/a"\nmodels = [{ web_search = true }]\n')


def test_unknown_key_on_a_route_table_is_rejected() -> None:
    # A typo'd capability must fail loudly, not read as "declared nothing".
    with pytest.raises(WorldConfigError, match="unknown key"):
        _parse('[aigateway]\ndefault_route = "/a"\nmodels = [{ id = "a", web_tool = true }]\n')


def test_non_boolean_web_search_is_rejected() -> None:
    with pytest.raises(WorldConfigError, match="web_search must be a boolean"):
        _parse('[aigateway]\ndefault_route = "/a"\nmodels = [{ id = "a", web_search = "yes" }]\n')


def test_a_route_entry_of_the_wrong_type_is_rejected() -> None:
    with pytest.raises(WorldConfigError, match="table or an id string"):
        _parse('[aigateway]\ndefault_route = "/a"\nmodels = [1]\n')


def test_duplicate_ids_are_rejected_across_both_spellings() -> None:
    with pytest.raises(WorldConfigError, match="duplicate"):
        _parse('[aigateway]\ndefault_route = "/a"\nmodels = ["a", { id = "a" }]\n')


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
    path = tmp_path / "url4.toml"
    path.write_text(_MINIMAL, encoding="utf-8")

    # OME-859: EMPTY_MODEL_WORLD for the same reason as `_parse` — this asserts that the FILE at
    # the declared path is what got read, so the compiled world must not contribute to it.
    section = load_config({"URL4_RUNNER_CONFIG": str(path)}, registry=EMPTY_MODEL_WORLD).aigateway

    assert section is not None
    assert section.models == (ModelSpec(id="claude-haiku-4-5"), ModelSpec(id="codex/gpt-5.5"))


def test_missing_config_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(WorldConfigError, match="cannot read"):
        load_config({"URL4_RUNNER_CONFIG": str(tmp_path / "absent.toml")})


def test_malformed_toml_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "url4.toml"
    path.write_text("[aigateway\n", encoding="utf-8")

    with pytest.raises(WorldConfigError, match="cannot read"):
        load_config({"URL4_RUNNER_CONFIG": str(path)})
