from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from scoreboard.config import Settings
from scoreboard.main import create_app


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, Any] = {
        "database_url": f"sqlite://{tmp_path / 'scoreboard.sqlite3'}",
        "cors_origins": [],
    }
    values.update(overrides)
    return Settings(**values)


def test_portal_has_no_auth_settings() -> None:
    settings = Settings()

    assert not hasattr(settings, "portal_auth_enabled")
    assert not hasattr(settings, "portal_auth_username")
    assert not hasattr(settings, "portal_auth_password")


def test_root_portal_is_public(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/")

        assert response.status_code == 200
        # Structural, not editorial: this test is about the page being publicly reachable.
        # Asserting the hero sentence would make every copy tweak a test failure, and the
        # hero is brand copy that changes on someone else's schedule.
        assert 'id="benchmark-table-wrap"' in response.text


def test_portal_assets_and_pages_are_public(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        for path in ("/index.html", "/benchmark.html", "/spec.html", "/data.html", "/main.js"):
            response = client.get(path)
            assert response.status_code == 200, path


def test_portal_pages_include_plausible_analytics(tmp_path: Path) -> None:
    # OME-373: traffic/visit analytics on the public board — a future rewrite of any
    # of these pages must not silently drop the tracking snippet.
    with TestClient(create_app(_settings(tmp_path))) as client:
        for path in ("/index.html", "/benchmark.html", "/spec.html", "/data.html"):
            response = client.get(path)
            assert "plausible.io/js/pa-ysspwNldM0r_4o-m1utPa.js" in response.text, path


def test_api_routes_remain_public_before_root_static_mount(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        assert client.get("/healthz").status_code == 200


def test_public_jsonl_artifacts_are_inline_text_and_unauthenticated(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        latest = client.get("/livetruth-latest.jsonl")
        assert latest.status_code == 200
        assert latest.headers["content-type"].startswith("text/plain")
        assert '"answer"' in latest.text

        masking = client.get("/livetruth-masking.dataset.jsonl")
        assert masking.status_code == 200
        assert masking.headers["content-type"].startswith("text/plain")
        assert '"question"' in masking.text

        eval_results = client.get("/livetruth-latest.eval.jsonl")
        assert eval_results.status_code == 200
        assert eval_results.headers["content-type"].startswith("text/plain")
        assert '"expected_answer"' in eval_results.text


@pytest.mark.parametrize(
    "path",
    [
        "/livetruth-latest.eval.jsonl.txt",
        "/livetruth-latest.answer-key.jsonl",
    ],
)
def test_forbidden_answer_key_artifacts_return_404_without_auth(tmp_path: Path, path: str) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        assert client.get(path).status_code == 404


def test_missing_artifact_fails_app_creation(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "livetruth-latest.jsonl").write_text("{}\n", encoding="utf-8")
    (artifacts / "livetruth-latest.eval.jsonl").write_text("{}\n", encoding="utf-8")

    settings = _settings(tmp_path, portal_artifacts_dir=artifacts)

    with pytest.raises(RuntimeError, match="livetruth-masking.dataset.jsonl"):
        create_app(settings)


def test_portal_serves_the_vendored_hero_mark(tmp_path: Path) -> None:
    # OME-874: the hero sets the mark AS the "o" in "Fusi[mark]ns". style.css forbids the raw
    # emoji inside display type (its glyph box word-spaces the letters and dips below baseline),
    # so it is an <img> — and it ships app-local, because the portal introduces no external host.
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/assets/mark/sf-mark-128.png")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"


def test_the_hero_mark_is_vendored_not_hotlinked(tmp_path: Path) -> None:
    """The mark must load from this origin, whatever the brand site does later.

    INVARIANT, stated as behaviour rather than as a string match: the element the hero uses
    for the mark resolves to a path this app serves. The mockup hotlinks
    `brand.screamingface.ai/assets/...`; copying that in would make the public board depend on
    another host at render time, and would break silently if that host moved.
    """
    with TestClient(create_app(_settings(tmp_path))) as client:
        markup = client.get("/index.html").text

        match = re.search(r'<img[^>]*class="o-mark"[^>]*src="([^"]+)"', markup)
        assert match is not None, "the hero no longer carries an .o-mark image"
        source = match.group(1)

        assert "//" not in source, f"the hero mark is loaded off-origin: {source}"
        asset = client.get("/" + source.lstrip("/"))
        assert asset.status_code == 200
        assert asset.headers["content-type"] == "image/png"


def test_pareto_copy_describes_standard_dominance() -> None:
    """Equal-score/cheaper and higher-score/equal-cost rows also dominate."""
    portal = Path(__file__).resolve().parents[2] / "portal"
    html = (portal / "benchmark.html").read_text(encoding="utf-8")
    script = (portal / "benchmark.js").read_text(encoding="utf-8")
    explanation = (
        "no submission has an equal-or-higher score at an equal-or-lower cost, "
        "with one strict improvement"
    )

    assert explanation in html
    assert explanation in script
    assert "no submission is both better and cheaper" not in html + script


def test_served_markdown_carries_no_internal_references(tmp_path: Path) -> None:
    """The portal tree is mounted whole, so every file in it is public.

    WHY this test exists: the portal ships unminified and `register_portal` mounts
    `portal/` at `/`, so a maintainer note dropped next to an asset is served to anyone who
    asks for it. `assets/mark/PROVENANCE.md` shipped with a ticket id and a `.claude/` path
    before review caught it — the policy existed, nothing enforced it.

    SCOPE, deliberately narrow: markdown only. The JS and CSS in this tree already carry ~42
    ticket references that predate this test; widening it to those is its own unit of work,
    and a test that fails on arrival gets skipped rather than fixed.
    """
    portal = Path(__file__).resolve().parents[2] / "portal"
    documents = sorted(portal.rglob("*.md"))
    assert documents, "expected at least one markdown file under portal/"

    with TestClient(create_app(_settings(tmp_path))) as client:
        for document in documents:
            route = "/" + document.relative_to(portal).as_posix()
            assert client.get(route).status_code == 200, route

            text = document.read_text(encoding="utf-8")
            leaks = [token for token in ("OME-", ".claude/", "worktrees/") if token in text]
            assert not leaks, (
                f"{route} is publicly served and leaks {leaks}. Keep internal references out of "
                "the portal tree — put the reasoning in docs/work/ instead."
            )


def test_pareto_chart_shell_is_bounded_provenanced_and_loaded_before_its_caller() -> None:
    """Part C stays hidden by default and explains the limits of its public claim."""
    portal = Path(__file__).resolve().parents[2] / "portal"
    html = (portal / "benchmark.html").read_text(encoding="utf-8")
    script = (portal / "benchmark.js").read_text(encoding="utf-8")

    assert re.search(r'<section[^>]*id="pareto-chart-section"[^>]*hidden', html)
    assert re.search(r'<div[^>]*class="pareto-chart-scroll"[^>]*tabindex="0"', html)
    assert 'aria-label="Score for cost chart, horizontally scrollable"' in html
    assert 'id="pareto-chart"' in html
    assert 'aria-hidden="true"' in html
    assert "Costs are self-reported, not verified by re-running." in html
    assert "Frontier membership considers the full board" in html
    assert "plots only the submissions shown on this page" in html

    logic_at = html.index('<script src="leaderboard-logic.js"')
    chart_at = html.index('<script src="pareto-chart.js"')
    caller_at = html.index('<script src="benchmark.js"')
    assert logic_at < chart_at < caller_at
    assert "SFParetoChart.render" in script
