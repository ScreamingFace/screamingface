"""The Helm chart is renamed while its RENDERED identity stays put (OME-876, Path A).

FEATURE: the Engine app is called `screamingface-engine` everywhere a human reads a name, but the
deployed objects keep the identity they already have, so upgrading a live release is an ordinary
rolling update rather than a replace.

STORY: as an operator I can `helm upgrade` onto the renamed chart and see only a new image roll
out — no renamed objects, no re-created Secret, no NetworkPolicy change in aigateway.

WHY this is a test and not a comment: `Chart.yaml`'s `name` feeds THREE things that are not
cosmetic, and nothing else in the suite notices if one of them moves.

  1. `app.kubernetes.io/name` is part of the Deployment's `spec.selector`.
  2. `apps/aigateway`'s NetworkPolicy admits client Pods BY that label. Denial happens at the CNI
     and surfaces as a connect timeout with nothing in the gateway's logs.
  3. `fullname` is the `lookup` key in `templates/secret.yaml` that re-reads the already-issued JWT
     signing secret. If the Secret's name moves, the lookup misses, the template falls through to
     `randAlphaNum 64`, and every live capability token is invalidated.

`nameOverride` is the valve that decouples the chart's name from all three. These tests pin the
valve open in the safe direction; `OME-877` tracks closing it deliberately.

AIDEV-NOTE: assertions are textual on purpose. pyyaml is only a TRANSITIVE dependency here (via
`kubernetes`), and this contract is not worth taking a direct dependency for.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_APP_ROOT = Path(__file__).resolve().parents[2]
_CHART = _APP_ROOT / "deploy" / "helm"

# INVARIANT: the identity the rendered objects must keep carrying. This is the PREVIOUS chart name,
# retained deliberately — see the module docstring. It is not a typo.
_PINNED_IDENTITY = "url4-cloud"
_NEW_CHART_NAME = "screamingface-engine"


def _chart_yaml() -> str:
    return (_CHART / "Chart.yaml").read_text(encoding="utf-8")


def _values_yaml() -> str:
    return (_CHART / "values.yaml").read_text(encoding="utf-8")


def _helpers_tpl() -> str:
    return (_CHART / "templates" / "_helpers.tpl").read_text(encoding="utf-8")


def test_the_chart_is_named_for_the_engine() -> None:
    """The chart's own name follows the app's rename."""
    declared = re.search(r"^name:\s*(\S+)\s*$", _chart_yaml(), re.MULTILINE)
    assert declared is not None, "Chart.yaml declares no top-level `name:`"
    assert declared.group(1) == _NEW_CHART_NAME


def test_the_chart_pins_its_rendered_name_to_the_previous_identity() -> None:
    """`nameOverride` holds `app.kubernetes.io/name` and every object name where they were.

    INVARIANT: removing this pin is a breaking deployment change, not a cleanup. It renames 12
    objects, changes a Deployment selector, breaks aigateway's allowlist, and regenerates the JWT
    signing secret. `OME-877` carries the three-phase migration that does it safely.
    """
    pinned = re.search(
        rf'^nameOverride:\s*"{re.escape(_PINNED_IDENTITY)}"\s*$',
        _values_yaml(),
        re.MULTILINE,
    )
    assert pinned is not None, (
        'values.yaml must pin `nameOverride: "url4-cloud"`; without it the chart rename '
        "renames every object and invalidates live capability tokens"
    )


def test_the_name_helper_still_honours_the_override() -> None:
    """The valve itself is intact — the helper must prefer `nameOverride` over `.Chart.Name`.

    WHY assert the template body: the pin in values.yaml is inert if the helper stops reading it,
    and that failure mode is silent. Sprig's `default <fallback> <value>` returns `value` when
    non-empty, so this argument order is what makes the override win.
    """
    assert "default .Chart.Name .Values.nameOverride" in _helpers_tpl()


def test_the_selector_labels_are_the_immutable_identity_subset() -> None:
    """Only name + instance may be selector labels.

    INVARIANT: a selector must never gain a label that changes on a rename or a version bump —
    `spec.selector` is immutable on an existing Deployment, so that would make every future
    rename an uninstall.
    """
    helpers = _helpers_tpl()
    selector_block = helpers.split('define "screamingface-engine.selectorLabels"')[-1]
    selector_block = selector_block.split("end")[0]
    assert "app.kubernetes.io/name" in selector_block
    assert "app.kubernetes.io/instance" in selector_block
    assert "helm.sh/chart" not in selector_block
    assert "app.kubernetes.io/version" not in selector_block


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_rendered_objects_keep_the_pinned_identity() -> None:
    """End-to-end proof of the pin: render the chart and read the identity back out.

    This is the assertion the whole Path A decision rests on. The textual tests above can all pass
    while a template hardcodes a name somewhere; only a render proves what ships.
    """
    rendered = subprocess.run(
        [
            "helm",
            "template",
            _PINNED_IDENTITY,
            str(_CHART),
            "--set-string",
            "config.natsUrl=nats://nats.example:4222",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    names = re.findall(r"^\s{2}name:\s*(\S+)\s*$", rendered, re.MULTILINE)
    assert names, "the chart rendered no named objects"
    # Every object name derives from `<release>-<name>`, and both halves are the pinned identity.
    assert all(name.startswith(f"{_PINNED_IDENTITY}-{_PINNED_IDENTITY}") for name in names), (
        f"object names moved off the pinned identity: "
        f"{sorted(n for n in names if not n.startswith(_PINNED_IDENTITY))}"
    )

    selector_names = re.findall(
        r"^\s+app\.kubernetes\.io/name:\s*(\S+)\s*$", rendered, re.MULTILINE
    )
    assert selector_names, "the chart rendered no `app.kubernetes.io/name` labels"
    # The runner pool is the one deliberate exception: aigateway's NetworkPolicy admits the run
    # workload by `app.kubernetes.io/name: url4-runner` (the old Job labels), and the pool
    # replaces the Jobs — so its pods must carry that label or they are denied at the CNI.
    assert set(selector_names) == {_PINNED_IDENTITY, "url4-runner"}, (
        f"`app.kubernetes.io/name` moved to {set(selector_names)}; this breaks the Deployment "
        f"selector and aigateway's NetworkPolicy allowlist"
    )
