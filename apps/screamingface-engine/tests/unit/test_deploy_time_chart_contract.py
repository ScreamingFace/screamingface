"""Every `DEPLOY_TIME` variable must actually be written by the chart (OME-929).

`job_env.DEPLOY_TIME` carries the docstring "Helm owns these end-to-end." For
`URL4_CLOUD_ARTIFACTS_DIR` that was simply false — Helm set nothing, both halves fell back to
their own pod-local `/tmp`, and every over-cap result 404'd on the hosted Engine.

WHY the existing contract test could not catch it: `test_job_env_contract.py` asserts only the
NEGATIVE direction — that the App does not write a deploy-time name. Nothing asserted the
POSITIVE one. `job_env` even recorded the reasoning that permitted the gap:

    "the direction that breaks silently is an unread WRITE, not an unwritten READ
     (which simply falls back)"

That is inverted for a variable whose fallback is a per-pod temp directory. The fallback was
not a benign default; it was the misconfiguration. This file asserts the direction nobody was
checking, and it would have failed the day OME-892 landed.

WHY textual and not `helm template`: this runs in the engine's own pytest lane, which has no
helm binary. The question — "does the chart name this variable at all?" — is answerable from
the template text, and a check that always runs beats a richer one that gets skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from screamingface_engine import job_env

_CHART = Path(__file__).resolve().parents[2] / "deploy/helm/templates"
_RUNNER_ENV = _CHART / "configmap-runner-env.yaml"
_APP_ENV = _CHART / "configmap.yaml"

# Variables the chart legitimately renders only under a condition. Each entry needs a REASON,
# because "it is optional" is how `ARTIFACTS_DIR` would have been waved through.
_CONDITIONALLY_RENDERED = {
    # Absent => web tools stay off, which is a working deployment (dec:W5). The Secret is
    # attached by name via envFrom, so the KEY appears in the chart's secret template.
    job_env.TAVILY_API_KEY,
    # Absent => the Runner uses the default route declared in the image's own url4.toml.
    job_env.AIGATEWAY_MODEL,
    # Absent => the caps fall back to shipped defaults that are correct at any scale; unlike
    # a storage location, a byte count has a safe default.
    job_env.RESULT_INLINE_CAP_BYTES,
    job_env.RESULT_HARD_CAP_BYTES,
    job_env.BRIDGE_MEMORY_BUDGET_BYTES,
    # Absent => the run mode reads the `url4.toml` baked into the image at its default path.
    # The image guarantees that file exists, so the fallback resolves to real declared config
    # rather than to an empty location — the property `ARTIFACTS_DIR` lacked.
    job_env.RUNNER_CONFIG,
}


def _chart_text() -> str:
    """Every template, because "does the chart name this?" is a chart-wide question.

    Deliberately not just the two ConfigMaps: a credential is named by the Secret template
    instead, and scanning only the ConfigMaps would report it as unrendered and invite an
    allowlist entry for something the chart does supply.
    """
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(_CHART.glob("*.yaml")))


def test_the_chart_templates_exist_so_this_check_is_not_vacuous() -> None:
    assert _RUNNER_ENV.is_file()
    assert _APP_ENV.is_file()


@pytest.mark.parametrize("name", sorted(job_env.DEPLOY_TIME - _CONDITIONALLY_RENDERED))
def test_every_unconditional_deploy_time_variable_is_named_by_the_chart(name: str) -> None:
    """If this fails, the code believes Helm supplies a value that Helm does not supply.

    The fallback then silently decides deployment behaviour — which for a storage location
    means the Runner and the App quietly use different storage.
    """
    assert name in _chart_text(), (
        f"{name} is declared in job_env.DEPLOY_TIME ('Helm owns these end-to-end') but no "
        f"chart template names it, so the code's fallback silently decides it. Either render "
        f"it in deploy/helm/templates/, or move it out of DEPLOY_TIME — and if it is "
        f"deliberately optional, add it to _CONDITIONALLY_RENDERED with the reason why its "
        f"fallback is safe."
    )


def test_the_artifacts_location_is_rendered_for_both_halves() -> None:
    """The specific regression: the writer and the reader must be pointed at ONE store.

    Named separately from the parametrised sweep because this is the variable whose absence
    was the bug, and because it must appear on BOTH sides — the Runner's env and the App's.
    """
    runner = _RUNNER_ENV.read_text(encoding="utf-8")
    app = _APP_ENV.read_text(encoding="utf-8")

    for name in (job_env.ARTIFACT_STORE, job_env.ARTIFACT_S3_BUCKET):
        assert name in runner, f"the Runner Job never receives {name}"
        assert name in app, f"the App never receives {name}"


def _yaml_keys(template: Path) -> list[str]:
    """The `key:` names a template actually assigns, ignoring comments.

    Comment-stripping matters: the runner-env template explains IN A COMMENT that the secret key
    is deliberately absent, and a naive substring search reads that explanation as a violation.
    """
    keys = []
    for raw in template.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("{{"):
            continue
        if ":" in line:
            keys.append(line.split(":", 1)[0].strip())
    return keys


def test_the_secret_key_is_not_assigned_in_a_configmap() -> None:
    """INVARIANT: object-storage credentials travel by Secret, never in a ConfigMap.

    A ConfigMap is readable by anything with `get` on it and is dumped in plain text by
    `helm get manifest` — the same reason `TAVILY_API_KEY` only ever travels by name.
    """
    assert job_env.ARTIFACT_S3_SECRET_KEY not in _yaml_keys(_RUNNER_ENV)
    assert job_env.ARTIFACT_S3_SECRET_KEY not in _yaml_keys(_APP_ENV)


def test_the_secret_key_is_assigned_in_the_secret_template() -> None:
    """The other half of the rule above: it must live SOMEWHERE, or nothing supplies it."""
    secret = _CHART / "secret-artifact-storage.yaml"

    assert job_env.ARTIFACT_S3_SECRET_KEY in _yaml_keys(secret)


def test_runner_scheduling_is_serialized_from_deployment_values() -> None:
    """INVARIANT: the control plane and every Runner Job share one placement source."""
    app = _APP_ENV.read_text(encoding="utf-8")

    assert "URL4_CLOUD_RUNNER_NODE_SELECTOR" in app
    assert "toJson .Values.nodeSelector" in app
    assert "URL4_CLOUD_RUNNER_TOLERATIONS" in app
    assert "toJson .Values.tolerations" in app


# --- the bundled store configures itself (OME-929) ---------------------------------------


def _garage() -> str:
    return (_CHART / "garage.yaml").read_text(encoding="utf-8")


def test_garage_self_configures_with_all_three_server_flags() -> None:
    """INVARIANT: no bootstrap Job, no operator commands, no scripted layout.

    `--single-node` REMOVES the layout operation rather than automating it, which matters because
    Garage's own docs warn that repeating `layout apply --version N` can leave a cluster
    INCONSISTENT — exactly the shape a hook re-running on every `helm upgrade` would produce.
    The other two adopt the credentials and bucket the chart states.
    """
    garage = _garage()

    for flag in ("--single-node", "--default-access-key", "--default-bucket"):
        assert flag in garage, f"{flag} missing — the deployment would need manual bootstrapping"


@pytest.mark.parametrize(
    ("garage_var", "secret_key"),
    [
        ("GARAGE_DEFAULT_ACCESS_KEY", job_env.ARTIFACT_S3_ACCESS_KEY),
        ("GARAGE_DEFAULT_SECRET_KEY", job_env.ARTIFACT_S3_SECRET_KEY),
    ],
)
def test_garage_adopts_the_same_credentials_the_engine_presents(
    garage_var: str, secret_key: str
) -> None:
    """INVARIANT: one source, three consumers — the App, every Runner Job, and Garage itself.

    Garage ADOPTS the pair the chart generates rather than minting its own. If these ever read
    from a different place than the engine does, the store holds a key the engine never presents
    and every artifact request 403s — which reads as a signing bug, not a config one.
    """
    garage = _garage()

    assert garage_var in garage
    # The `key:` of the secretKeyRef must be the variable the engine reads, because `envFrom`
    # injects under the key's own name and cannot rename.
    assert f"key: {secret_key}" in garage


def test_the_bundled_store_pins_a_version_that_has_the_self_configuration_flags() -> None:
    """The three flags landed in Garage 2.3.0. An older tag starts with no layout and no bucket,
    and every artifact PUT fails — so the floor is part of the contract, not a preference."""
    values = (_CHART.parent / "values.yaml").read_text(encoding="utf-8")
    match = re.search(r"image:\s*dxflrs/garage:v(\d+)\.(\d+)\.(\d+)", values)

    assert match is not None, "the bundled Garage image is no longer a pinned dxflrs/garage tag"
    assert (int(match[1]), int(match[2])) >= (2, 3), (
        f"garage.image is v{match[1]}.{match[2]}.{match[3]}, below the v2.3.0 floor that "
        "introduced --single-node / --default-access-key / --default-bucket"
    )
