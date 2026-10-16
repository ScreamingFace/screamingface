from __future__ import annotations

import os
from pathlib import Path

import pytest

from workbench import targets
from workbench.targets import KNOWN_TARGETS, TARGET_ENV, selected_target, start_target


def test_default_target_is_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TARGET_ENV, raising=False)
    assert selected_target() == "replay"


def test_explicit_target_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TARGET_ENV, "local")
    assert selected_target() == "local"


def test_unknown_target_is_refused_with_the_known_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TARGET_ENV, "prod")
    with pytest.raises(ValueError) as caught:
        selected_target()
    assert all(name in str(caught.value) for name in KNOWN_TARGETS)


def test_start_target_refuses_an_unknown_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="prod"):
        with start_target("prod", tmp_path):
            pass


def test_local_target_skips_without_paid_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SCREAMINGFACE_TEST_PAID", raising=False)
    with pytest.raises(pytest.skip.Exception, match="SCREAMINGFACE_TEST_PAID"):
        with start_target("local", tmp_path):
            pass


def test_local_target_skips_without_the_byok_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_TEST_PAID", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(pytest.skip.Exception, match="OPENROUTER_API_KEY"):
        with start_target("local", tmp_path):
            pass


def test_replay_target_skips_through_the_e2e_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SCREAMINGFACE_TEST_E2E", raising=False)
    with pytest.raises(pytest.skip.Exception, match="SCREAMINGFACE_TEST_E2E"):
        with start_target("replay", tmp_path):
            pass


def _paid_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    # A placeholder key: every path below stops before anything could call a provider.
    monkeypatch.setenv("SCREAMINGFACE_TEST_PAID", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder-not-a-key")


def _no_boot(*args: str) -> None:
    raise AssertionError(f"the runtime must not be invoked: {args}")


def test_local_target_skips_without_prepared_ifeval_assets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _paid_opt_in(monkeypatch)
    empty = tmp_path / "assets"
    empty.mkdir()
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(empty))
    monkeypatch.setattr(targets, "_runtime_cli", _no_boot)
    with pytest.raises(pytest.skip.Exception, match=r"ifeval.*SCREAMINGFACE_E2E_ASSETS"):
        with start_target("local", tmp_path / "work"):
            pass


def _prepared_assets(tmp_path: Path) -> Path:
    root = tmp_path / "assets"
    (root / "ifeval").mkdir(parents=True)
    (root / "ifeval" / "cases.json").write_text("[]")
    return root


def test_local_target_boots_on_the_prepared_assets_with_split_hops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _paid_opt_in(monkeypatch)
    assets = _prepared_assets(tmp_path)
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(assets))
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(targets, "_runtime_cli", lambda *args: calls.append(args))
    monkeypatch.setattr(targets, "_listed_benchmarks", lambda url: ["ifeval", "medxpert"])
    work = tmp_path / "work"
    with start_target("local", work) as target:
        assert calls and calls[0][0] == "up"
        # The runtime reads <data-dir>/benchmark-assets (RuntimeConfig.assets_dir).
        assert (work / "data" / "benchmark-assets" / "ifeval" / "cases.json").is_file()
        assert (work / "data" / "benchmark-assets").resolve() == assets.resolve()
        assert target.required_hops == ("engine", "aigateway")
        assert [s.name for s in target.sources] == ["engine", "aigateway"]
    assert calls[-1][0] == "down"


def test_runtime_cli_scrubs_the_foreign_gateway_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIGATEWAY_DATABASE_URL", "postgres://example.invalid/db")
    seen: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(targets.subprocess, "run", fake_run)
    targets._runtime_cli("status")
    env = seen["env"]
    assert isinstance(env, dict)
    assert "AIGATEWAY_DATABASE_URL" not in env
    assert env.get("PATH") == os.environ.get("PATH")


def test_local_target_skips_and_stops_when_the_runtime_does_not_list_ifeval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _paid_opt_in(monkeypatch)
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(_prepared_assets(tmp_path)))
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(targets, "_runtime_cli", lambda *args: calls.append(args))
    monkeypatch.setattr(targets, "_listed_benchmarks", lambda url: ["medxpert"])
    with pytest.raises(pytest.skip.Exception, match=r"does not list ifeval.*medxpert"):
        with start_target("local", tmp_path / "work"):
            pass
    assert [c[0] for c in calls] == ["up", "down"]
