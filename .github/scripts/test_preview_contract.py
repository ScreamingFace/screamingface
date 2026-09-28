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
        status="preview",
        number=123,
        sha="a" * 40,
        components=("engine",),
        images=("engine",),
    )

    assert "## Preview: active" in comment
    assert "fusion-pr-123.preview.dev.screamingface.ai" in comment
    assert "kube-pr-123.preview.dev.screamingface.ai/kubeconfig" in comment
    assert "preview_access.sh?ref=main" in comment
    assert "bash -s -- 123" in comment
    assert "cloudflared access token" not in comment
    assert "CF_ACCESS_TOKEN" not in comment
    assert (
        "kubectl --namespace sf-preview-pr-123 logs deployment/url4-cloud "
        "--all-containers --tail=200" in comment
    )
    assert (
        "kubectl --namespace sf-preview-pr-123 logs --follow "
        "deployment/url4-cloud --all-containers --tail=50" in comment
    )
    assert (
        "kubectl --namespace sf-preview-pr-123 describe pods "
        "--selector app.kubernetes.io/name=url4-cloud" in comment
    )
    assert "kubectl --namespace sf-preview-pr-123 get pods -o wide" in comment
    assert "export KUBECONFIG=/tmp/sf-preview-pr-123.kubeconfig" in comment
    assert "Its token lasts one hour." in comment
    assert "DEPLOYMENT_NAME" not in comment
    assert "This kubeconfig only accesses namespace sf-preview-pr-123." in comment
    assert "Commands with --all-namespaces or -A are blocked." in comment
    assert "signoz.pulse.dev.openmined.org/logs-explorer" in comment
    assert 'k8s.namespace.name="sf-preview-pr-123"' in comment
    assert "k8s_namespace_name" not in comment


@pytest.mark.parametrize(
    ("component", "deployment", "pod_label"),
    [
        ("aigateway", "aigw", "aigateway"),
        ("aigatewayUi", "aigw-ui", "aigateway-ui"),
        ("scoreboard", "leaderboard", "scoreboard"),
        ("engine", "url4-cloud", "url4-cloud"),
    ],
)
def test_active_comment_uses_the_selected_deployment(
    component: str, deployment: str, pod_label: str
) -> None:
    contract = load_contract()

    comment = contract.preview_comment(
        status="preview",
        number=123,
        sha="a" * 40,
        components=(component,),
        images=(component,),
    )

    assert (
        f"kubectl --namespace sf-preview-pr-123 logs deployment/{deployment} "
        in comment
    )
    assert f"--selector app.kubernetes.io/name={pod_label}" in comment


def test_fork_detection_requires_the_exact_repository() -> None:
    contract = load_contract()
    repository = "ScreamingFace/screamingface"

    same = {"head": {"repo": {"full_name": repository}}}
    fork = {"head": {"repo": {"full_name": "outside/screamingface"}}}
    deleted = {"head": {"repo": None}}

    assert not contract.is_fork(same, repository)
    assert contract.is_fork(fork, repository)
    assert contract.is_fork(deleted, repository)


def test_fork_comment_explains_the_removal() -> None:
    contract = load_contract()

    comment = contract.fork_comment()

    assert comment.startswith(contract.COMMENT_MARKER)
    assert "## Preview: unavailable" in comment
    assert "Fork pull requests cannot receive a Preview." in comment
    assert "The Preview labels were removed." in comment


def test_reconcile_strips_a_queued_fork_instead_of_promoting_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = load_contract()
    instances: list = []

    class FakeGitHub:
        repo = "ScreamingFace/screamingface"

        def __init__(self) -> None:
            self.stripped: list[int] = []
            self.commented: list[int] = []
            instances.append(self)

        def pulls(self) -> list[dict]:
            return [
                {
                    "number": 7,
                    "labels": [{"name": "preview-queued"}],
                    "head": {"repo": {"full_name": "outside/screamingface"}},
                    "created_at": "2026-08-24T00:00:00Z",
                    "draft": False,
                }
            ]

        def set_managed_labels(self, number: int, wanted: set[str]) -> None:
            assert wanted == set()
            self.stripped.append(number)

        def upsert_comment(self, number: int, body: str) -> None:
            assert "## Preview: unavailable" in body
            self.commented.append(number)

        def events(self, number: int) -> list[dict]:
            raise AssertionError("fork pull requests must not reach admission")

    monkeypatch.setattr(contract, "GitHub", FakeGitHub)

    contract.reconcile()

    assert instances[0].stripped == [7]
    assert instances[0].commented == [7]


def test_fork_guard_runs_trusted_code_on_the_label_event() -> None:
    guard = (ROOT / ".github/workflows/preview-fork-guard.yml").read_text()

    assert "pull_request_target:" in guard
    assert "types: [labeled]" in guard
    assert "head.repo.full_name != github.repository" in guard
    assert "startsWith(github.event.label.name, 'preview')" in guard
    assert "persist-credentials: false" in guard
    assert "ref:" not in guard
    assert "preview_contract.py guard" in guard
    assert "id-token" not in guard


def test_workflows_keep_oidc_away_from_forks_and_serialize_admission() -> None:
    images = (ROOT / ".github/workflows/preview-images.yml").read_text()
    admission = (ROOT / ".github/workflows/preview-admission.yml").read_text()

    assert "pull_request_target" not in images
    assert "pull_request:" in images
    assert "AZURE_PREVIEW_CLIENT_ID" in images
    assert "head.repo.full_name == github.repository" in images
    assert "  REGISTRY: acropenminedpreview.azurecr.io" in images.splitlines()
    assert "preview-building" in images
    assert '"$BASE_SHA...$HEAD_SHA"' in images
    assert "workflow_run:" in admission
    assert "schedule:" in admission
    assert "screamingface-preview-admission" in admission
    assert "cancel-in-progress: false" in admission
