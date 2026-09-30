"""E14 spine PB-22 (nightly): submit, publish, download, the asset digest matches the version.

FEATURE: OME-1307 (E14) E2E. STORY: as Ana, I publish my cache version, and anybody can download
the release asset and check that its sha256 is the one the scoreboard shows.

Nightly only, against a SANDBOX GitHub repo. The E2E replay lane (push and pull request) never
runs it: without ``SCREAMINGFACE_TEST_E2E_GITHUB=1`` and the sandbox variables it skips, with the
names of the missing variables (never their values). It never creates a repo or an App.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import httpx
import pytest
from harness._gating import require_e2e_stack
from harness.e14_stack import E14Stack, e14_candidate, e14_stack
from harness.goldens import GoldenReport
from harness.identity import edge_client, edge_http

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_github]

ANA = "ana@e2e.example"
BOARD = "ifeval"
GITHUB_GATE: Final = "SCREAMINGFACE_TEST_E2E_GITHUB"
_SANDBOX_VARIABLES: Final = (
    "E14_SANDBOX_APP_ID",
    "E14_SANDBOX_APP_INSTALLATION_ID",
    "E14_SANDBOX_APP_PRIVATE_KEY",
    "E14_SANDBOX_REPO",
    "E14_SANDBOX_TOKEN",
)
_POLL_SECONDS: Final = 2.0
_DEADLINE_SECONDS: Final = 300.0  # the PB NFR: published within 5 minutes (p95)
_GITHUB_API: Final = "https://api.github.com"
_ASSETS: Final = ("entries.jsonl.gz", "manifest.json")


def _sandbox_env() -> dict[str, str]:
    """The sandbox variables, or a clean skip that names the missing ones."""
    if os.environ.get(GITHUB_GATE) != "1":
        pytest.skip(f"{GITHUB_GATE}=1 not set (PB-22 is nightly-only, against a sandbox repo)")
    missing = [name for name in _SANDBOX_VARIABLES if not os.environ.get(name, "").strip()]
    if missing:
        pytest.skip(f"sandbox GitHub variables not set: {', '.join(missing)}")
    return {name: os.environ[name] for name in _SANDBOX_VARIABLES}


def _scoreboard_github_env(sandbox: Mapping[str, str]) -> dict[str, str]:
    return {
        "SCOREBOARD_GITHUB_APP_ID": sandbox["E14_SANDBOX_APP_ID"],
        "SCOREBOARD_GITHUB_APP_INSTALLATION_ID": sandbox["E14_SANDBOX_APP_INSTALLATION_ID"],
        "SCOREBOARD_GITHUB_APP_PRIVATE_KEY": sandbox["E14_SANDBOX_APP_PRIVATE_KEY"],
        "SCOREBOARD_GITHUB_REPO": sandbox["E14_SANDBOX_REPO"],
        # WHY short: the default poll is 30 s, and the NFR deadline is what the test enforces.
        "SCOREBOARD_PUBLISH_POLL_INTERVAL_S": "1",
    }


def _github(sandbox: Mapping[str, str]) -> httpx.Client:
    return httpx.Client(
        base_url=_GITHUB_API,
        timeout=60.0,
        follow_redirects=True,
        headers={
            "Authorization": f"Bearer {sandbox['E14_SANDBOX_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def _publication_state(stack: E14Stack, head_id: object, result_id: object) -> str | None:
    with edge_http(stack.scoreboard_url, None) as http:
        response = http.get(f"/v1/scores/{head_id}/results")
    assert response.status_code == 200, response.text
    item = next(row for row in response.json()["results"] if row["id"] == str(result_id))
    state: str | None = item["publication_state"]
    return state


def _wait_until_published(stack: E14Stack, head_id: object, result_id: object) -> None:
    deadline = time.monotonic() + _DEADLINE_SECONDS
    state = _publication_state(stack, head_id, result_id)
    while state != "published" and time.monotonic() < deadline:
        time.sleep(_POLL_SECONDS)
        state = _publication_state(stack, head_id, result_id)
    assert state == "published", (
        f"not published within {_DEADLINE_SECONDS:.0f}s; last state {state}"
    )


def _release_assets(github: httpx.Client, repo: str, tag: str) -> dict[str, bytes]:
    response = github.get(f"/repos/{repo}/releases/tags/{tag}")
    assert response.status_code == 200, f"release {tag} not found: {response.status_code}"
    assets = {asset["name"]: asset["id"] for asset in response.json()["assets"]}
    assert sorted(assets) == sorted(_ASSETS), f"unexpected release assets: {sorted(assets)}"
    downloaded: dict[str, bytes] = {}
    for name, asset_id in assets.items():
        # WHY octet-stream: the API answers the asset bytes, not its JSON description.
        body = github.get(
            f"/repos/{repo}/releases/assets/{asset_id}",
            headers={"Accept": "application/octet-stream"},
        )
        assert body.status_code == 200, f"asset {name} not downloadable: {body.status_code}"
        downloaded[name] = body.content
    return downloaded


def _delete_release(github: httpx.Client, repo: str, tag: str) -> None:
    """Leave the sandbox repo clean. A 404 is fine (nothing was published)."""
    release = github.get(f"/repos/{repo}/releases/tags/{tag}")
    if release.status_code == 200:
        github.delete(f"/repos/{repo}/releases/{release.json()['id']}")
    github.delete(f"/repos/{repo}/git/refs/tags/{tag}")


def _assert_asset_digests(
    assets: Mapping[str, bytes], version_id: str, sha: str, archive_dir: Path
) -> None:
    entries = assets["entries.jsonl.gz"]
    # INVARIANT (D7 X-16): `archive_sha256` is the sha256 of the gzip bytes of the entries file.
    assert hashlib.sha256(entries).hexdigest() == sha
    gzip.decompress(entries)  # a valid gzip stream
    manifest = json.loads(assets["manifest.json"])
    assert manifest["version_id"] == version_id
    assert manifest["entries_sha256"] == sha
    # PB-H3: the asset bytes equal the archive the gateway wrote.
    for name in _ASSETS:
        assert (archive_dir / "cache-versions" / version_id / name).read_bytes() == assets[name]


def test_submit_publish_download_asset_digest_matches_version(
    tmp_path: Path, e14_assets: Path, e14_golden: GoldenReport
) -> None:
    sandbox = _sandbox_env()
    require_e2e_stack()
    repo = sandbox["E14_SANDBOX_REPO"]
    with (
        e14_stack(
            work_dir=tmp_path,
            assets_dir=e14_assets,
            scoreboard_extra_env=_scoreboard_github_env(sandbox),
        ) as stack,
        _github(sandbox) as github,
        edge_client(stack, ANA) as ana,
    ):
        report = ana.evaluate(
            e14_candidate(e14_golden), benchmark=BOARD, limit=e14_golden.limit, progress=False
        )
        submitted = ana.leaderboards.submit(report.candidates.only)
        assert submitted.reported_result is not None
        version = submitted.reported_result.cache_version
        assert version is not None
        tag = f"cv-{version.id}"
        try:
            # WHY Ana: the publish owner check uses the verified email (D5).
            publication = ana.leaderboards.publish_cache_version(submitted.reported_result.id)
            assert publication.state == "requested"
            _wait_until_published(stack, submitted.id, submitted.reported_result.id)
            assets = _release_assets(github, repo, tag)
            _assert_asset_digests(assets, str(version.id), version.sha256, stack.archive_dir)
        finally:
            _delete_release(github, repo, tag)
