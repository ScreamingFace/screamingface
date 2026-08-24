"""Select Preview inputs and manage the bounded Preview lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

COMPONENTS = ("aigateway", "aigatewayUi", "scoreboard", "engine")
STATUS_LABELS = frozenset(
    {"preview-building", "preview-queued", "preview", "preview-expired"}
)
LABEL_SLUG = {
    "aigateway": "aigateway",
    "aigatewayUi": "aigateway-ui",
    "scoreboard": "scoreboard",
    "engine": "engine",
}
COMPONENT_LABELS = {
    name: f"preview-component-{LABEL_SLUG[name]}" for name in COMPONENTS
}
IMAGE_LABELS = {name: f"preview-image-{LABEL_SLUG[name]}" for name in COMPONENTS}
MANAGED_LABELS = (
    STATUS_LABELS
    | frozenset(COMPONENT_LABELS.values())
    | frozenset(IMAGE_LABELS.values())
)
COMMENT_MARKER = "<!-- screamingface-preview -->"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class Selection(NamedTuple):
    components: tuple[str, ...]
    images: tuple[str, ...]


class PullState(NamedTuple):
    number: int
    labels: frozenset[str]
    preview_since: datetime | None
    queued_since: datetime
    draft: bool = False


class AdmissionPlan(NamedTuple):
    expire: tuple[int, ...]
    promote: tuple[int, ...]


def _starts(path: str, prefixes: Sequence[str]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def _is_file(path: str, names: Sequence[str]) -> bool:
    return path in names


def _select_path(path: str) -> Selection:
    if path == ".dockerignore":
        return Selection(COMPONENTS, COMPONENTS)

    rules = {
        "aigateway": {
            "chart": ("apps/aigateway/charts/aigateway/",),
            "prefix": ("apps/aigateway/src/",),
            "files": (
                "apps/aigateway/Dockerfile",
                "apps/aigateway/pyproject.toml",
                "apps/aigateway/uv.lock",
            ),
        },
        "aigatewayUi": {
            "chart": ("apps/aigateway-ui/charts/aigateway-ui/",),
            "prefix": ("apps/aigateway-ui/src/", "apps/aigateway-ui/public/"),
            "files": (
                "apps/aigateway-ui/Dockerfile",
                "apps/aigateway-ui/package.json",
                "apps/aigateway-ui/package-lock.json",
                "apps/aigateway-ui/next.config.ts",
                "apps/aigateway-ui/next.config.js",
            ),
        },
        "scoreboard": {
            "chart": ("apps/scoreboard/charts/scoreboard/",),
            "prefix": (
                "apps/scoreboard/src/",
                "apps/scoreboard/portal/",
                "apps/scoreboard/artifacts/",
            ),
            "files": (
                "apps/scoreboard/Dockerfile",
                "apps/scoreboard/pyproject.toml",
                "apps/scoreboard/uv.lock",
            ),
        },
        "engine": {
            "chart": ("apps/screamingface-engine/deploy/helm/",),
            "prefix": ("apps/screamingface-engine/src/", "packages/url4/"),
            "files": (
                "apps/screamingface-engine/Dockerfile",
                "apps/screamingface-engine/Dockerfile.benchmark",
                "apps/screamingface-engine/pyproject.toml",
                "apps/screamingface-engine/uv.lock",
                "apps/screamingface-engine/url4.toml",
            ),
        },
    }
    for component, rule in rules.items():
        if _starts(path, rule["prefix"]) or _is_file(path, rule["files"]):
            return Selection((component,), (component,))
        if _starts(path, rule["chart"]):
            return Selection((component,), ())
    return Selection((), ())


def classify_paths(paths: Sequence[str]) -> Selection:
    """Return ordered runtime and image selections for changed paths."""
    components: set[str] = set()
    images: set[str] = set()
    for path in paths:
        selected = _select_path(path)
        components.update(selected.components)
        images.update(selected.images)
    return Selection(
        tuple(name for name in COMPONENTS if name in components),
        tuple(name for name in COMPONENTS if name in images),
    )


def preview_tag(number: int, sha: str) -> str:
    if number < 1 or not SHA_PATTERN.fullmatch(sha):
        raise ValueError(
            "Preview tag needs a positive pull request and a 40-character SHA"
        )
    return f"pr-{number}-{sha[:7]}"


def plan_admission(
    pulls: Sequence[PullState],
    now: datetime,
    max_active: int = 3,
    max_age: timedelta = timedelta(hours=72),
) -> AdmissionPlan:
    expire = tuple(
        pull.number
        for pull in pulls
        if "preview" in pull.labels
        and pull.preview_since is not None
        and now - pull.preview_since > max_age
    )
    active = sum(
        "preview" in pull.labels and pull.number not in expire for pull in pulls
    )
    queue = sorted(
        (
            pull
            for pull in pulls
            if "preview-queued" in pull.labels
            and "no-preview" not in pull.labels
            and not pull.draft
        ),
        key=lambda pull: (pull.queued_since, pull.number),
    )
    promote = tuple(pull.number for pull in queue[: max(0, max_active - active)])
    return AdmissionPlan(expire, promote)


def preview_comment(
    status: str,
    number: int,
    sha: str,
    components: Sequence[str],
    images: Sequence[str],
) -> str:
    display_status = "active" if status == "preview" else status
    namespace = f"sf-preview-pr-{number}"
    component_text = ", ".join(components) or "none"
    image_text = ", ".join(images) or "none"
    lines = [
        COMMENT_MARKER,
        f"## Preview: {display_status}",
        "",
        f"- Revision: `{sha}`",
        f"- Components: `{component_text}`",
        f"- Images: `{image_text}`",
    ]
    if display_status == "active":
        routes: list[str] = []
        if {"aigateway", "aigatewayUi", "engine"} & set(components):
            routes.append(
                f"- AI Gateway: https://aigw-pr-{number}.preview.dev.screamingface.ai"
            )
        if "aigatewayUi" in components:
            routes.append(
                f"- AI Gateway UI: https://console-pr-{number}.preview.dev.screamingface.ai"
            )
        if "scoreboard" in components:
            routes.append(
                f"- Scoreboard: https://leaderboard-pr-{number}.preview.dev.screamingface.ai"
            )
        if "engine" in components:
            routes.append(
                f"- Fusion: https://fusion-pr-{number}.preview.dev.screamingface.ai"
            )
        lines.extend(
            [
                "",
                "### Applications",
                "",
                *routes,
                "",
                "### Kubernetes access",
                "",
                "```bash",
                f'PREVIEW_KUBECONFIG="/tmp/sf-preview-pr-{number}.kubeconfig"',
                f'PREVIEW_KUBECONFIG_URL="https://kube-pr-{number}.preview.dev.screamingface.ai/kubeconfig"',
                'CF_ACCESS_TOKEN="$(cloudflared access token -app="$PREVIEW_KUBECONFIG_URL")"',
                'GITHUB_TOKEN="$(gh auth token)"',
                "{",
                '  printf \'header = "cf-access-token: %s"\\n\' "$CF_ACCESS_TOKEN"',
                '  printf \'header = "X-Preview-Access-Token: %s"\\n\' "$CF_ACCESS_TOKEN"',
                '  printf \'header = "X-GitHub-Token: %s"\\n\' "$GITHUB_TOKEN"',
                '  printf \'url = "%s"\\n\' "$PREVIEW_KUBECONFIG_URL"',
                '} | curl --fail --silent --show-error --config - > "$PREVIEW_KUBECONFIG"',
                "unset CF_ACCESS_TOKEN GITHUB_TOKEN",
                'chmod 600 "$PREVIEW_KUBECONFIG"',
                'export KUBECONFIG="$PREVIEW_KUBECONFIG"',
                "kubectl get pods",
                "kubectl logs POD_NAME --all-containers --tail=200",
                "```",
                "",
                "### Observability",
                "",
                f"[Open SigNoz logs](https://signoz.pulse.dev.openmined.org/logs-explorer?query=k8s_namespace_name%3D%22{namespace}%22)",
                "",
                f'Filter: `k8s_namespace_name="{namespace}"`',
            ]
        )
    return "\n".join(lines) + "\n"


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GitHub:
    def __init__(self) -> None:
        self.repo = os.environ["GITHUB_REPOSITORY"]
        self.token = os.environ["GITHUB_TOKEN"]
        self.api = os.environ.get("GITHUB_API_URL", "https://api.github.com")

    def request(self, method: str, path: str, data: object | None = None) -> object:
        body = None if data is None else json.dumps(data).encode()
        request = urllib.request.Request(
            f"{self.api}/repos/{self.repo}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "screamingface-preview",
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                content = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise RuntimeError(
                f"GitHub API {method} {path}: {error.code}: {detail}"
            ) from error
        return json.loads(content) if content else {}

    def pull(self, number: int) -> dict:
        return self.request("GET", f"/pulls/{number}")  # type: ignore[return-value]

    def pulls(self) -> list[dict]:
        return self.request("GET", "/pulls?state=open&per_page=100")  # type: ignore[return-value]

    def events(self, number: int) -> list[dict]:
        return self.request("GET", f"/issues/{number}/events?per_page=100")  # type: ignore[return-value]

    def set_managed_labels(self, number: int, wanted: set[str]) -> None:
        pull = self.pull(number)
        current = {item["name"] for item in pull["labels"]}
        labels = sorted((current - MANAGED_LABELS) | wanted)
        self.request("PUT", f"/issues/{number}/labels", {"labels": labels})

    def upsert_comment(self, number: int, body: str) -> None:
        comments = self.request("GET", f"/issues/{number}/comments?per_page=100")
        for comment in comments:  # type: ignore[union-attr]
            if COMMENT_MARKER in comment["body"]:
                self.request(
                    "PATCH", f"/issues/comments/{comment['id']}", {"body": body}
                )
                return
        self.request("POST", f"/issues/{number}/comments", {"body": body})


def _pull_selection(pull: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    labels = {item["name"] for item in pull["labels"]}
    components = tuple(name for name in COMPONENTS if COMPONENT_LABELS[name] in labels)
    images = tuple(name for name in COMPONENTS if IMAGE_LABELS[name] in labels)
    return components, images


def _update(number: int, sha: str, status: str, selection: Selection) -> None:
    github = GitHub()
    pull = github.pull(number)
    if pull["head"]["sha"] != sha:
        print(f"Ignore stale revision {sha}; current revision is {pull['head']['sha']}")
        return
    wanted = {COMPONENT_LABELS[name] for name in selection.components}
    wanted.update(IMAGE_LABELS[name] for name in selection.images)
    if status in STATUS_LABELS:
        wanted.add(status)
    github.set_managed_labels(number, wanted)
    github.upsert_comment(number, preview_comment(status, number, sha, *selection))


def reconcile() -> None:
    github = GitHub()
    now = datetime.now(UTC)
    raw_pulls = github.pulls()
    pulls: list[PullState] = []
    for pull in raw_pulls:
        labels = frozenset(item["name"] for item in pull["labels"])
        events = github.events(pull["number"])
        added = {
            name: [
                _parse_time(event["created_at"])
                for event in events
                if event["event"] == "labeled"
                and event.get("label", {}).get("name") == name
            ]
            for name in ("preview", "preview-queued")
        }
        created = _parse_time(pull["created_at"])
        pulls.append(
            PullState(
                pull["number"],
                labels,
                max(added["preview"], default=None),
                max(added["preview-queued"], default=created),
                pull["draft"],
            )
        )
    plan = plan_admission(pulls, now)
    by_number = {pull["number"]: pull for pull in raw_pulls}
    for number in plan.expire:
        pull = by_number[number]
        components, images = _pull_selection(pull)
        _update(
            number,
            pull["head"]["sha"],
            "preview-expired",
            Selection(components, images),
        )
    for number in plan.promote:
        pull = by_number[number]
        components, images = _pull_selection(pull)
        _update(number, pull["head"]["sha"], "preview", Selection(components, images))


def _selection(value: argparse.Namespace) -> Selection:
    return Selection(
        tuple(json.loads(value.components)), tuple(json.loads(value.images))
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    classify = subparsers.add_parser("classify")
    classify.add_argument("--paths", type=Path, required=True)
    classify.add_argument("--number", type=int, required=True)
    classify.add_argument("--sha", required=True)
    classify.add_argument("--output", type=Path, required=True)
    for name in ("prepare", "ready", "failed", "disable"):
        command = subparsers.add_parser(name)
        command.add_argument("--number", type=int, required=True)
        command.add_argument("--sha", required=True)
        command.add_argument("--components", default="[]")
        command.add_argument("--images", default="[]")
    subparsers.add_parser("reconcile")
    args = parser.parse_args()
    if args.command == "classify":
        selection = classify_paths(args.paths.read_text().splitlines())
        matrix = [name for name in selection.images if name != "engine"]
        outputs = {
            "components": json.dumps(selection.components, separators=(",", ":")),
            "images": json.dumps(selection.images, separators=(",", ":")),
            "matrix": json.dumps(matrix, separators=(",", ":")),
            "engine": str("engine" in selection.images).lower(),
            "any": str(bool(selection.components)).lower(),
            "tag": preview_tag(args.number, args.sha),
        }
        with args.output.open("a") as output:
            for name, value in outputs.items():
                output.write(f"{name}={value}\n")
    elif args.command == "reconcile":
        reconcile()
    else:
        selection = _selection(args)
        status = {
            "prepare": "preview-building",
            "ready": "preview-queued",
            "failed": "failed",
            "disable": "disabled",
        }[args.command]
        _update(args.number, args.sha, status, selection)


if __name__ == "__main__":
    main()
