from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = Path(__file__).with_name("preview_contract.py")


def load_contract():
    spec = importlib.util.spec_from_file_location("preview_contract", CONTRACT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_engine_source_and_shared_url4_select_only_engine_images() -> None:
    contract = load_contract()

    selection = contract.classify_paths(
        [
            "apps/screamingface-engine/src/screamingface_engine/config.py",
            "packages/url4/src/url4/parser.py",
        ]
    )

    assert selection.components == ("engine",)
    assert selection.images == ("engine",)


def test_chart_only_selects_runtime_without_an_image() -> None:
    contract = load_contract()

    selection = contract.classify_paths(
        ["apps/aigateway/charts/aigateway/templates/deployment.yaml"]
    )

    assert selection.components == ("aigateway",)
    assert selection.images == ()


def test_tests_and_docs_do_not_select_a_runtime() -> None:
    contract = load_contract()

    selection = contract.classify_paths(
        [
            "apps/aigateway/tests/unit/test_health.py",
            "apps/scoreboard/README.md",
            "apps/screamingface-engine/docs/architecture.md",
        ]
    )

    assert selection.components == ()
    assert selection.images == ()


def test_root_dockerignore_selects_every_runtime_and_image() -> None:
    contract = load_contract()

    selection = contract.classify_paths([".dockerignore"])

    assert selection.components == ("aigateway", "aigatewayUi", "scoreboard", "engine")
    assert selection.images == ("aigateway", "aigatewayUi", "scoreboard", "engine")


def test_ui_uses_the_infrastructure_label_slug() -> None:
    contract = load_contract()

    assert contract.COMPONENT_LABELS["aigatewayUi"] == "preview-component-aigateway-ui"
    assert contract.IMAGE_LABELS["aigatewayUi"] == "preview-image-aigateway-ui"


def test_old_and_new_rename_paths_are_both_classified() -> None:
    contract = load_contract()

    selection = contract.classify_paths(
        [
            "apps/aigateway/src/aigateway/old.py",
            "apps/scoreboard/src/scoreboard/new.py",
        ]
    )

    assert selection.components == ("aigateway", "scoreboard")
    assert selection.images == ("aigateway", "scoreboard")


def test_preview_tag_requires_exact_pr_and_sha() -> None:
    contract = load_contract()

    assert contract.preview_tag(42, "a" * 40) == "pr-42-aaaaaaa"
    with pytest.raises(ValueError):
        contract.preview_tag(0, "a" * 40)
    with pytest.raises(ValueError):
        contract.preview_tag(42, "not-a-sha")


def test_admission_expires_first_then_promotes_oldest_queue() -> None:
    contract = load_contract()
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    pulls = [
        contract.PullState(1, frozenset({"preview"}), now - timedelta(hours=73), now),
        contract.PullState(2, frozenset({"preview"}), now - timedelta(hours=1), now),
        contract.PullState(3, frozenset({"preview"}), now - timedelta(hours=1), now),
        contract.PullState(
            4, frozenset({"preview-queued"}), None, now - timedelta(hours=2)
        ),
        contract.PullState(
            5, frozenset({"preview-queued"}), None, now - timedelta(hours=1)
        ),
    ]

    plan = contract.plan_admission(pulls, now)

    assert plan.expire == (1,)
    assert plan.promote == (4,)


def test_disabled_and_draft_requests_never_promote() -> None:
    contract = load_contract()
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    pulls = [
        contract.PullState(
            1,
            frozenset({"preview-queued", "no-preview"}),
            None,
            now,
        ),
        contract.PullState(2, frozenset({"preview-queued"}), None, now, draft=True),
    ]

    plan = contract.plan_admission(pulls, now)

    assert plan.promote == ()


def test_active_comment_contains_access_and_observability_contract() -> None:
    contract = load_contract()

    comment = contract.preview_comment(
        status="active",
        number=123,
        sha="a" * 40,
        components=("engine",),
        images=("engine",),
    )

    assert "fusion-pr-123.preview.dev.screamingface.ai" in comment
    assert "kube-pr-123.preview.dev.screamingface.ai/kubeconfig" in comment
    assert "kubectl logs" in comment
    assert "signoz.pulse.dev.openmined.org/logs-explorer" in comment
    assert 'k8s_namespace_name="sf-preview-pr-123"' in comment


def test_workflows_keep_oidc_away_from_forks_and_serialize_admission() -> None:
    images = (ROOT / ".github/workflows/preview-images.yml").read_text()
    admission = (ROOT / ".github/workflows/preview-admission.yml").read_text()

    assert "pull_request_target" not in images
    assert "pull_request:" in images
    assert "AZURE_PREVIEW_CLIENT_ID" in images
    assert "head.repo.full_name == github.repository" in images
    assert "acropenminedpreview.azurecr.io" in images
    assert "preview-building" in images
    assert '"$BASE_SHA...$HEAD_SHA"' in images
    assert "workflow_run:" in admission
    assert "schedule:" in admission
    assert "screamingface-preview-admission" in admission
    assert "cancel-in-progress: false" in admission
