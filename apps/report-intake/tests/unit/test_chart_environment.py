"""The chart renders exactly `Settings`' environment surface — asserted from the app's side.

`Settings` is declared `extra="ignore"`, which makes every name mismatch completely silent: a
variable the chart renders that no field reads is accepted, dropped, and never mentioned, and the
pod runs on the field's DEFAULT. For `AUTH_MODE` that is a production pod with authentication
disabled, indistinguishable from a working one until someone forges a request.

Three checks stand between that and a deploy, and this file is the one a developer runs:

1. `main._reject_unknown_environment` — in-process, at boot, and only for a name that reached a
   real pod.
2. This file — the chart's templates against `Settings.model_fields`, in this stack's own gates,
   with no helm on the box.
3. `.github/scripts/verify_chart_wiring.py` — the same equality against the RENDERED manifest,
   which is what catches a name produced by templating rather than written literally.

WHY the scan is textual here rather than a render: helm is not a dependency of this app, and
"which names appear in the templates" is genuinely a textual property. The structural half —
which object carries each name, and whether the container reads it — needs a render and lives in
the verifier.
"""

from __future__ import annotations

import re
from pathlib import Path

from report_intake.config import ENV_PREFIX, Settings

_CHART_ROOT = Path(__file__).resolve().parents[2] / "charts" / "report-intake"
_TEMPLATES = _CHART_ROOT / "templates"

_ENV_NAME = re.compile(rf"{ENV_PREFIX}[A-Z0-9_]+")


def _declared_env_names() -> set[str]:
    return {f"{ENV_PREFIX}{name.upper()}" for name in Settings.model_fields}


def _charted_env_names() -> set[str]:
    """Every `REPORT_INTAKE_*` name the chart's templates mention, values.yaml excluded.

    `.tpl` as well as `.yaml`: the database URL is emitted from a named helper, because the
    Deployment and the migration Job both need it and must not disagree about which Secret it
    comes from. Scanning only the object files would report it as missing.

    values.yaml is excluded on purpose: it holds the operator-facing knobs (`config.authMode`),
    not the environment names, and a prose mention there would make this assertion pass on a
    template that renders nothing.
    """
    names: set[str] = set()
    for pattern in ("*.yaml", "*.tpl"):
        for path in _TEMPLATES.rglob(pattern):
            names.update(_ENV_NAME.findall(path.read_text(encoding="utf-8")))
    return names


def test_the_chart_names_no_setting_this_service_does_not_read() -> None:
    """The direction that fails silently. `extra="ignore"` drops the unknown name, so the pod
    keeps the default and the manifest says otherwise — nothing anywhere reports a mismatch."""
    assert not _charted_env_names() - _declared_env_names()


def test_every_setting_this_service_reads_is_rendered_by_the_chart() -> None:
    """The other direction, and the reason this is an equality rather than a subset check: a field
    added to `Settings` with no chart line takes its declared default in every deployment, which
    is the same failure wearing different clothes."""
    assert not _declared_env_names() - _charted_env_names()


def test_the_three_secret_valued_settings_are_never_in_the_configmap() -> None:
    """A ConfigMap is not a Secret, and all three carry a credential — the database URL its
    password, the Turnstile secret itself, and the Linear API key a long-lived token to the
    private tracker the team works in. They belong on the Deployment, from a `secretKeyRef`."""
    configmap = (_TEMPLATES / "configmap.yaml").read_text(encoding="utf-8")

    assert f"{ENV_PREFIX}DATABASE_URL" not in configmap
    assert f"{ENV_PREFIX}TURNSTILE_SECRET" not in configmap
    assert f"{ENV_PREFIX}LINEAR_API_KEY" not in configmap


def test_the_chart_holds_no_linear_credential_literal() -> None:
    """The one value in this chart's surface that is a token to the private tracker. It comes from
    a Secret the operator creates — `linear.existingSecret` names it and the Deployment reads it
    with `optional: true`, so the Secret not existing is the normal state and the pod still
    starts. A literal here would be a credential in a values file, in a git repo, forever."""
    for path in _CHART_ROOT.rglob("*.yaml"):
        text = path.read_text(encoding="utf-8")

        assert "lin_api_" not in text
        assert f"{ENV_PREFIX}LINEAR_API_KEY: " not in text


def test_the_chart_never_names_a_turnstile_site_key() -> None:
    """The site key is a browser-side value this service never reads, so a field for it would be
    an environment variable nobody consumes — and `_reject_unknown_environment` would refuse to
    start the pod. Asserted over the whole chart, values files included, because this is exactly
    the kind of key someone adds to values.yaml first."""
    for path in _CHART_ROOT.rglob("*.yaml"):
        assert "TURNSTILE_SITE_KEY" not in path.read_text(encoding="utf-8")


def test_the_chart_this_scans_is_the_real_one() -> None:
    """A path that stops resolving turns every assertion above into a scan over nothing, which
    passes forever."""
    assert (_TEMPLATES / "configmap.yaml").is_file()
    assert (_CHART_ROOT / "values-cloud.yaml").is_file()


def _pod_carrying_templates() -> list[Path]:
    """Every template that renders a Pod spec, found rather than listed.

    A list would be a list somebody forgets to extend. `containers:` is what makes an object a
    Pod carrier, and it is the same string in a Deployment, a Job and a Helm test Pod.
    """
    return sorted(
        path
        for path in _TEMPLATES.rglob("*.yaml")
        if "containers:" in path.read_text(encoding="utf-8")
    )


def test_every_pod_this_chart_renders_disables_kubernetes_service_links() -> None:
    """Without it this service cannot start, and the more obvious the naming the worse it is.

    kubelet injects a legacy Docker-link variable per Service in the namespace, named from the
    Service uppercased with `-` as `_`. Install this release as `report-intake` and its own
    Service yields `REPORT_INTAKE_REPORT_INTAKE_SERVICE_HOST`; a `report-intake-pg` Postgres beside
    it adds `REPORT_INTAKE_PG_RW_SERVICE_PORT` and six more. `create_app` rejects any
    `REPORT_INTAKE_*` matching no `Settings` field -- rightly, since a name nobody reads means a
    value silently on its default -- so the Pod CrashLoopBackOffs on names Kubernetes invented.

    Found on a real cluster. An earlier smoke test passed only because it happened to install as
    `reports` into `report-intake-e2e`, which produces `REPORTS_*` and collides with nothing.
    Same defect as scoreboard's (#538); the engine already carries the line.
    """
    templates = _pod_carrying_templates()

    assert templates, "no pod-carrying template found — the search is wrong, not the chart"
    missing = [
        path.relative_to(_CHART_ROOT).as_posix()
        for path in templates
        if "enableServiceLinks: false" not in path.read_text(encoding="utf-8")
    ]
    assert not missing, f"pod specs without enableServiceLinks: false: {missing}"


def test_the_chart_does_not_offer_sqlite_as_a_deployment() -> None:
    """Migrations run as a hook Job in its OWN Pod. A sqlite URL is migrated in a filesystem the
    application Pod never sees, so the Deployment finds no `reports` table and `/readyz` fails
    closed forever while `/healthz` answers 200 -- Running, never Ready, reading like a routing
    fault. The chart used to call sqlite "right for a single-replica smoke test"; it is right for
    no deployment, and saying so is the whole fix, since the chart cannot read the Secret."""
    values = (_CHART_ROOT / "values.yaml").read_text(encoding="utf-8")

    assert "sqlite" in values, "the refusal has to be stated where an operator sets the value"
    assert "smoke test and nothing else" not in values
    assert "requires Postgres" in values
