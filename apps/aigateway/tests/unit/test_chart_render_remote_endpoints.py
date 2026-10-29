"""The chart delivers the private endpoints file to the gateway, opt-in (OME-1771).

FEATURE: hosted BYOM. `AIGW_REMOTE_ENDPOINTS_CONFIG` names a TOML file the gateway reads once at
startup (Unit 0); unset means no configured endpoints. The chart mounts that file from a
ConfigMap or Secret the operator owns, so endpoint URLs and grants never pass through chart
values, a rendered object or Git.

WHY the checksum is SUPPLIED: the file is read only at startup, so a changed file must roll the
pod, and the chart never reads an object it did not render. Hashing the source's NAME would roll
nothing when its content changes; the operator passes the content revision instead.

INVARIANT: off by default. Every existing install renders exactly as before, with no env, mount
or annotation, because an empty path would make the gateway refuse to start.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_APP_ROOT = Path(__file__).resolve().parents[2]
_CHART = _APP_ROOT / "charts" / "aigateway"
_RELEASE = "aigw"
_FULLNAME = f"{_RELEASE}-aigateway"
_BASE = (
    "database.existingSecret=db-secret",
    "auth.existingSecret=auth-secret",
)
_ENV = "AIGW_REMOTE_ENDPOINTS_CONFIG"
_ANNOTATION = "checksum/remote-endpoints"
_REVISION = "sha256-" + "cd" * 32

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _run(*sets: str) -> subprocess.CompletedProcess[str]:
    args = ["helm", "template", _RELEASE, str(_CHART)]
    for value in (*_BASE, *sets):
        args += ["--set-string", value]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _render(*sets: str) -> list[dict[str, Any]]:
    result = _run(*sets)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _gateway(docs: list[dict[str, Any]]) -> dict[str, Any]:
    for doc in docs:
        if doc.get("kind") == "Deployment" and doc["metadata"]["name"] == _FULLNAME:
            return doc
    raise AssertionError(f"no Deployment/{_FULLNAME} in the rendered chart")


def _container(deployment: dict[str, Any]) -> dict[str, Any]:
    return deployment["spec"]["template"]["spec"]["containers"][0]


def _env(deployment: dict[str, Any]) -> dict[str, Any]:
    return {entry["name"]: entry for entry in _container(deployment).get("env", [])}


def test_without_a_source_the_gateway_renders_no_endpoints_wiring() -> None:
    deployment = _gateway(_render())

    assert _ENV not in _env(deployment)
    assert "volumeMounts" not in _container(deployment)
    assert "volumes" not in deployment["spec"]["template"]["spec"]
    assert _ANNOTATION not in deployment["spec"]["template"]["metadata"]["annotations"]


@pytest.mark.parametrize(
    ("source", "volume_key", "name_key"),
    [("existingConfigMap", "configMap", "name"), ("existingSecret", "secret", "secretName")],
)
def test_one_source_is_mounted_read_only_where_the_variable_points(
    source: str, volume_key: str, name_key: str
) -> None:
    deployment = _gateway(
        _render(
            f"remoteEndpoints.{source}=private-endpoints",
            "remoteEndpoints.key=endpoints-v3.toml",
            f"remoteEndpoints.contentChecksum={_REVISION}",
        )
    )

    path = _env(deployment)[_ENV]["value"]
    mounts = [m for m in _container(deployment)["volumeMounts"] if path.startswith(m["mountPath"])]
    assert len(mounts) == 1, mounts
    assert mounts[0]["readOnly"] is True
    assert path == mounts[0]["mountPath"] + "/endpoints.toml"
    volumes = {v["name"]: v for v in deployment["spec"]["template"]["spec"]["volumes"]}
    projected = volumes[mounts[0]["name"]][volume_key]
    assert projected[name_key] == "private-endpoints"
    assert projected["items"] == [{"key": "endpoints-v3.toml", "path": "endpoints.toml"}]
    assert deployment["spec"]["template"]["metadata"]["annotations"][_ANNOTATION] == _REVISION


def test_the_chart_renders_no_object_that_could_hold_the_private_file() -> None:
    kinds = {"ConfigMap", "Secret"}
    plain = _render()
    sourced = _render(
        "remoteEndpoints.existingSecret=private-endpoints",
        f"remoteEndpoints.contentChecksum={_REVISION}",
    )

    assert sorted(d["metadata"]["name"] for d in sourced if d["kind"] in kinds) == sorted(
        d["metadata"]["name"] for d in plain if d["kind"] in kinds
    )


def test_the_migrate_job_never_receives_the_endpoints_file() -> None:
    """Only the serving gateway composes providers; the schema migration has no use for it."""
    docs = _render(
        "remoteEndpoints.existingSecret=private-endpoints",
        f"remoteEndpoints.contentChecksum={_REVISION}",
    )

    for doc in docs:
        if doc.get("kind") == "Job":
            assert "private-endpoints" not in yaml.safe_dump(doc)


@pytest.mark.parametrize(
    ("sets", "reason"),
    [
        (("remoteEndpoints.existingSecret=private-endpoints",), "contentChecksum"),
        (
            (
                "remoteEndpoints.existingSecret=a",
                "remoteEndpoints.existingConfigMap=b",
                f"remoteEndpoints.contentChecksum={_REVISION}",
            ),
            "only one",
        ),
        (
            (
                "remoteEndpoints.existingSecret=private-endpoints",
                "remoteEndpoints.key=",
                f"remoteEndpoints.contentChecksum={_REVISION}",
            ),
            "key",
        ),
        ((f"remoteEndpoints.contentChecksum={_REVISION}",), "no source"),
        (
            (
                "remoteEndpoints.existingSecret=private-endpoints",
                "remoteEndpoints.contentChecksum=two words",
            ),
            "contentChecksum",
        ),
    ],
)
def test_a_malformed_endpoints_source_refuses_to_render(sets: tuple[str, ...], reason: str) -> None:
    """The chart has no values schema, so the template `fail` is the only guard."""
    result = _run(*sets)

    assert result.returncode != 0, "the chart rendered when it should have refused"
    assert "remoteEndpoints" in result.stderr
    assert reason in result.stderr


def _readme_upgrade_sets() -> list[str]:
    """The `remoteEndpoints` values the README's first-upgrade command sets, as `name=value`."""
    import re

    text = (_CHART / "README.md").read_text(encoding="utf-8")
    pairs = re.findall(r"--set(?:-string)? (remoteEndpoints\.\w+)=(\S+)", text)
    # The command passes the file's sha256 through a shell substitution.
    substitution = '"$('
    return [
        f"{name}={_REVISION if value.startswith(substitution) else value}" for name, value in pairs
    ]


def test_the_readme_upgrade_renders_for_a_release_from_before_this_block(tmp_path: Path) -> None:
    """WHY: `--reuse-values` renders with the previous release's values, which have no
    `remoteEndpoints` block and so no default `key`. The README's command must set every field
    the render requires on its own (OME-1771 review)."""
    chart = tmp_path / "aigateway"
    shutil.copytree(_CHART, chart)
    values = yaml.safe_load((chart / "values.yaml").read_text(encoding="utf-8"))
    del values["remoteEndpoints"]
    (chart / "values.yaml").write_text(yaml.safe_dump(values), encoding="utf-8")
    sets = _readme_upgrade_sets()
    assert {pair.split("=", 1)[0] for pair in sets} >= {
        "remoteEndpoints.existingSecret",
        "remoteEndpoints.contentChecksum",
    }

    args = ["helm", "template", _RELEASE, str(chart)]
    for value in (*_BASE, *sets):
        args += ["--set-string", value]
    result = subprocess.run(args, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    gateway = _gateway(docs)
    assert _env(gateway)[_ENV]["value"].endswith("/endpoints.toml")
    assert gateway["spec"]["template"]["metadata"]["annotations"][_ANNOTATION] == _REVISION
