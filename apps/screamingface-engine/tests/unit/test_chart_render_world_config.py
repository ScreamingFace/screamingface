"""One privately supplied world config reaches the App AND the runner pool (OME-1770).

FEATURE: hosted BYOM, Unit 2. A deployment that declares a configured-endpoint route needs a
COMPLETE world config that is not the image's public `url4.toml`. The chart mounts it from an
existing ConfigMap or Secret the operator owns, never from a value it renders itself, so no
private stanza ever passes through chart values or Git.

INVARIANT: the App and the pool read the SAME file. Discovery promises what the App parsed and
execution runs what a worker parsed (`world.config.parse_config`), so the two pod templates carry
the same source, key, read-only mount, `URL4_RUNNER_CONFIG` path and content checksum. A
difference between them is a route the catalog offers and the queue refuses, or the reverse.

WHY the checksum is SUPPLIED, not computed: the chart never reads an object it did not render, so
hashing the source's NAME would roll nothing when the file changes. The operator passes the file's
content revision; the same value on both templates is what rolls both together. A render proves
the desired wiring only; that every live worker and child loaded the file is a rollout check.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_CHART = Path(__file__).resolve().parents[2] / "deploy" / "helm"
_RELEASE = "url4-cloud"
_ENV = "URL4_RUNNER_CONFIG"
_ANNOTATION = "checksum/world-config"
_REVISION = "sha256-" + "ab" * 32

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="needs the helm CLI")


def _run(*sets: str) -> subprocess.CompletedProcess[str]:
    args = [
        "helm",
        "template",
        _RELEASE,
        str(_CHART),
        "--set-string",
        "config.natsUrl=nats://nats.example:4222",
    ]
    for value in sets:
        args += ["--set-string", value]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _render(*sets: str) -> list[dict[str, Any]]:
    result = _run(*sets)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _deployments(docs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The App and the pool, keyed by the component label each is selected on."""
    found = {}
    for doc in docs:
        if doc.get("kind") != "Deployment":
            continue
        component = doc["spec"]["template"]["metadata"]["labels"]["app.kubernetes.io/component"]
        found[component] = doc
    assert set(found) == {"control-plane", "runner"}, sorted(found)
    return found


def _container(deployment: dict[str, Any]) -> dict[str, Any]:
    return deployment["spec"]["template"]["spec"]["containers"][0]


def _env(deployment: dict[str, Any]) -> dict[str, Any]:
    return {entry["name"]: entry for entry in _container(deployment).get("env", [])}


def _world_volume(deployment: dict[str, Any]) -> dict[str, Any] | None:
    """The volume behind the mount `URL4_RUNNER_CONFIG` points into, or None."""
    path = _env(deployment).get(_ENV, {}).get("value")
    if path is None:
        return None
    mounts = [m for m in _container(deployment)["volumeMounts"] if path.startswith(m["mountPath"])]
    assert len(mounts) == 1, mounts
    mount = mounts[0]
    assert mount.get("readOnly") is True, mount
    volumes = {v["name"]: v for v in deployment["spec"]["template"]["spec"]["volumes"]}
    return {"mount": mount, "volume": volumes[mount["name"]], "path": path}


def test_without_a_source_both_pods_keep_the_image_config() -> None:
    for deployment in _deployments(_render()).values():
        assert _ENV not in _env(deployment)
        assert _world_volume(deployment) is None
        assert _ANNOTATION not in deployment["spec"]["template"]["metadata"]["annotations"]


@pytest.mark.parametrize(
    ("source", "volume_key", "name_key"),
    [("existingConfigMap", "configMap", "name"), ("existingSecret", "secret", "secretName")],
)
def test_one_source_reaches_both_pods_identically(
    source: str, volume_key: str, name_key: str
) -> None:
    docs = _render(
        f"worldConfig.{source}=private-world",
        "worldConfig.key=world.toml",
        f"worldConfig.contentChecksum={_REVISION}",
    )
    wired = {}
    for component, deployment in _deployments(docs).items():
        world = _world_volume(deployment)
        assert world is not None, component
        projected = world["volume"][volume_key]
        assert projected[name_key] == "private-world"
        assert projected["items"] == [{"key": "world.toml", "path": "url4.toml"}]
        assert world["path"] == world["mount"]["mountPath"] + "/url4.toml"
        annotations = deployment["spec"]["template"]["metadata"]["annotations"]
        assert annotations[_ANNOTATION] == _REVISION
        wired[component] = (projected, world["mount"]["mountPath"], world["path"])
    assert wired["control-plane"] == wired["runner"]


def test_the_chart_renders_no_object_that_could_hold_the_private_file() -> None:
    plain = _render()
    sourced = _render(
        "worldConfig.existingSecret=private-world", f"worldConfig.contentChecksum={_REVISION}"
    )
    kinds = {"ConfigMap", "Secret"}
    assert sorted(d["metadata"]["name"] for d in sourced if d["kind"] in kinds) == sorted(
        d["metadata"]["name"] for d in plain if d["kind"] in kinds
    )


@pytest.mark.parametrize(
    ("sets", "reason"),
    [
        (("worldConfig.existingSecret=private-world",), "contentChecksum"),
        (
            (
                "worldConfig.existingSecret=a",
                "worldConfig.existingConfigMap=b",
                f"worldConfig.contentChecksum={_REVISION}",
            ),
            "only one",
        ),
        (
            (
                "worldConfig.existingSecret=private-world",
                "worldConfig.key=",
                f"worldConfig.contentChecksum={_REVISION}",
            ),
            "key",
        ),
        ((f"worldConfig.contentChecksum={_REVISION}",), "no source"),
        (
            (
                "worldConfig.existingSecret=private-world",
                "worldConfig.contentChecksum=two words",
            ),
            "contentChecksum",
        ),
    ],
)
def test_a_malformed_world_config_refuses_to_render(sets: tuple[str, ...], reason: str) -> None:
    result = _run(*sets)
    assert result.returncode != 0
    assert "worldConfig" in result.stderr
    assert reason in result.stderr


def _readme_upgrade_sets() -> list[str]:
    """The `worldConfig` values the README's first-upgrade command sets, as `name=value`."""
    import re

    text = (_CHART / "README.md").read_text(encoding="utf-8")
    pairs = re.findall(r"--set(?:-string)? (worldConfig\.\w+)=(\S+)", text)
    # The command passes the file's sha256 through a shell substitution.
    substitution = '"$('
    return [
        f"{name}={_REVISION if value.startswith(substitution) else value}" for name, value in pairs
    ]


def test_the_readme_upgrade_renders_for_a_release_from_before_this_block(tmp_path: Path) -> None:
    """WHY: `--reuse-values` renders with the previous release's values, which have no
    `worldConfig` block and so no default `key`. The README's command must set every field the
    render requires on its own (OME-1770 review)."""
    chart = tmp_path / "helm"
    shutil.copytree(_CHART, chart)
    values = yaml.safe_load((chart / "values.yaml").read_text(encoding="utf-8"))
    del values["worldConfig"]
    (chart / "values.yaml").write_text(yaml.safe_dump(values), encoding="utf-8")
    sets = _readme_upgrade_sets()
    assert {pair.split("=", 1)[0] for pair in sets} >= {
        "worldConfig.existingSecret",
        "worldConfig.contentChecksum",
    }

    args = ["helm", "template", _RELEASE, str(chart)]
    for value in ("config.natsUrl=nats://nats.example:4222", *sets):
        args += ["--set-string", value]
    result = subprocess.run(args, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    for deployment in _deployments(docs).values():
        assert _env(deployment)[_ENV]["value"].endswith("/url4.toml")
        assert deployment["spec"]["template"]["metadata"]["annotations"][_ANNOTATION] == _REVISION
