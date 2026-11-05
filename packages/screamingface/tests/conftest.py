"""Shared fixtures for the Client SDK test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# INVARIANT: disable analytics before collection imports the SDK, not just in fixtures.
# Analytics tests explicitly clear this only with isolated preferences and mocked sinks.
os.environ["DO_NOT_TRACK"] = "1"

from screamingface._runtime import cli, engine_env  # noqa: E402 -- after DO_NOT_TRACK on purpose
from screamingface._runtime import source as runtime_source  # noqa: E402

_PAID_FLAG = "SCREAMINGFACE_TEST_PAID"
_PAID_LANE: Path = Path(__file__).resolve().parent / "paid"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Drop every paid-lane test unless the paid button opened the fence.

    INVARIANT (OME-1275, owner rule): `tests/paid/` runs ONLY when someone presses the
    paid button — the `workflow_dispatch` workflow or the `test-paid-benchmarks` just
    recipe, both of which set SCREAMINGFACE_TEST_PAID=1. Merge CI runs plain `pytest`.
    WHY deselect instead of `collect_ignore`: the ignore list does not apply to a path
    named on the command line, so `pytest tests/paid` would slip through; deselection
    fences both, and pytest's summary still counts what it dropped. Pinned by
    `test_paid_lane_isolation.py`.
    """
    if os.environ.get(_PAID_FLAG) == "1":
        return
    fenced: list[pytest.Item] = [item for item in items if _PAID_LANE in item.path.parents]
    if not fenced:
        return
    config.hook.pytest_deselected(items=fenced)
    items[:] = [item for item in items if _PAID_LANE not in item.path.parents]


@pytest.fixture(autouse=True)
def _isolated_screamingface_data_dir(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # INVARIANT: the suite never reads the developer's real `~/.screamingface`.
    # Since OME-998 the default client discovers a running `screamingface up` stack
    # from that data dir, so without this isolation any test building a default
    # client would change behavior based on whether the dev's local stack is up.
    # Tests that need populated local state set SCREAMINGFACE_DATA_DIR themselves.
    monkeypatch.setenv(
        "SCREAMINGFACE_DATA_DIR",
        str(tmp_path_factory.mktemp("screamingface-data")),
    )
    # INVARIANT (OME-1169): `up`/`restart` refuse to boot while AIGATEWAY_DATABASE_URL is
    # set, reading live os.environ — on a dev machine that exports it (exactly the
    # gateway-with-Postgres dev the refusal protects), every runtime test would fail with
    # the refusal instead of exercising its own contract. Tests that need the variable
    # set it themselves via monkeypatch.
    monkeypatch.delenv("AIGATEWAY_DATABASE_URL", raising=False)
    # INVARIANT: every Client seeds its Access store from SCREAMINGFACE_ACCESS_TOKEN (e2e
    # workbench U1); a token exported in the dev's shell or by the workbench would otherwise
    # change every Access test. Tests that need it set it via monkeypatch.
    monkeypatch.delenv("SCREAMINGFACE_ACCESS_TOKEN", raising=False)


# FEATURE (OME-1620): `up`, `restart` and `prepare` BUILD a pip user's Engine environment when
# none is set — a 700 MB install. Captured at import, before any test patches it.
_REAL_ENGINE_BUILD = cli._with_built_engine_environment


@pytest.fixture(autouse=True)
def _no_engine_environment_build(monkeypatch: pytest.MonkeyPatch) -> None:
    # INVARIANT: the suite never builds a real Engine environment. Runtime tests force the
    # bundled source to exercise `up` with stubbed apps; without this guard every one of them
    # would start a real `uv venv` + pip install into its temp dir. The in-process Engine is
    # what those tests expect, which is exactly what "no build" leaves them with.
    monkeypatch.setattr(cli, "_with_built_engine_environment", lambda config, source: config)


@pytest.fixture
def real_engine_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt back in to the real decision; stub `ensure_engine_environment`, never install."""
    monkeypatch.setattr(cli, "_with_built_engine_environment", _REAL_ENGINE_BUILD)


# FEATURE (OME-1620): with no interpreter named, `screamingface up` starts the Engine from the
# checkout's own Engine venv when it finds one. Captured at import, before any test patches it.
_REAL_CHECKOUT = runtime_source.checkout_root()
_REAL_CHECKOUT_ENGINE_VENV = engine_env.checkout_engine_venv


@pytest.fixture(autouse=True)
def _no_real_engine_venv(monkeypatch: pytest.MonkeyPatch) -> None:
    # INVARIANT: the suite never reads the developer's real Engine venv, like their real data
    # dir above. Otherwise every test that reaches `_config` in the checkout it runs from
    # depends on that venv: red on a box whose venv lacks the benchmarks extra ("serves only
    # medxpert"), a real 4 s Engine child on one that has it, green in CI only because CI has
    # none. Fake checkouts under tmp_path keep their default, so the rung stays testable.
    def isolated(source: runtime_source.RuntimeSource) -> Path | None:
        if _REAL_CHECKOUT is not None and source.root is not None:
            if source.root.resolve() == _REAL_CHECKOUT.resolve():
                return None
        return _REAL_CHECKOUT_ENGINE_VENV(source)

    monkeypatch.setattr(engine_env, "checkout_engine_venv", isolated)
    # Same invariant for an interpreter exported in the developer's shell.
    monkeypatch.delenv(engine_env.ENGINE_PYTHON_ENV, raising=False)


__all__: list[str] = []


@pytest.fixture(autouse=True)
def _isolated_analytics_preferences(tmp_path, monkeypatch):
    # WHY: isolate explicit preference tests as well as the collection-time opt-out above.
    monkeypatch.setenv("SCREAMINGFACE_ANALYTICS_CONFIG", str(tmp_path / "analytics.json"))
