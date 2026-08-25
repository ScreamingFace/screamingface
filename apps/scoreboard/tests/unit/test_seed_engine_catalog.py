"""Benchmark prose is seeded from the Engine catalogue, never from chart values (OME-904).

FEATURE: benchmark descriptions on the leaderboard, with one authoring site.
STORY: as a leaderboard reader, I see what a benchmark tests without leaving the board.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from scoreboard.scores.models import Benchmark
from scoreboard.scores.store import ScoreStore
from scoreboard.seed import (
    EngineCatalogUnavailable,
    SeedBenchmark,
    fetch_engine_benchmarks,
    load_benchmarks_json,
    seed_benchmarks,
    seed_from_sources,
)

pytestmark = pytest.mark.asyncio

ENGINE_URL = "https://engine.test"

_CATALOG = {
    "object": "list",
    "data": [
        {
            "object": "benchmark",
            "id": "draco",
            "title": "DRACO",
            "description": "A 100-task DRACO reproduction with official score arithmetic.",
            "revision": "rev-draco",
            "case_count": 100,
            "focus": "Research reports with citations",
            "dataset_url": "https://huggingface.co/datasets/perplexity-ai/draco",
            "href": "/v1/benchmarks/draco",
        },
        {
            "object": "benchmark",
            "id": "ifeval",
            "title": "IFEval",
            "description": "The canonical 541-prompt instruction-following benchmark.",
            "revision": "rev-ifeval",
            "case_count": 541,
            "href": "/v1/benchmarks/ifeval",
        },
    ],
}


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _serving(payload: object, *, status: int = 200) -> httpx.Client:
    return _client(lambda request: httpx.Response(status, json=payload))


def _refusing(exc: Exception) -> httpx.Client:
    def _raise(request: httpx.Request) -> httpx.Response:
        raise exc

    return _client(_raise)


# --- reading the catalogue ------------------------------------------------------------------


async def test_a_catalog_entry_becomes_a_seed_row() -> None:
    with _serving(_CATALOG) as client:
        read = fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)

    draco = read.rows[0]
    assert draco.id == "draco"
    # The Engine calls it `title`; the board's column is `display_name`. One mapping, one place.
    assert draco.display_name == "DRACO"
    assert draco.description == "A 100-task DRACO reproduction with official score arithmetic."
    assert draco.revision == "rev-draco"
    assert draco.focus == "Research reports with citations"
    assert draco.dataset_url == "https://huggingface.co/datasets/perplexity-ai/draco"


async def test_an_entry_without_display_extras_seeds_them_as_absent() -> None:
    # WHY: the Engine omits the key rather than sending null, and the portal already renders an
    # em dash for a benchmark with no focus line.
    with _serving(_CATALOG) as client:
        ifeval = fetch_engine_benchmarks(ENGINE_URL, client=client).rows[1]

    assert ifeval.focus is None
    assert ifeval.dataset_url is None
    assert ifeval.revision == "rev-ifeval"


async def test_catalog_fields_the_board_does_not_display_are_ignored() -> None:
    # INVARIANT: the Engine may grow its catalogue (case_count, href, check_surface, whatever
    # comes next) without breaking a deploy. The board reads the fields it displays and no more.
    payload = {
        "object": "list",
        "data": [
            {
                "id": "draco",
                "title": "DRACO",
                "description": "Text.",
                "revision": "rev",
                "case_count": 100,
                "href": "/v1/benchmarks/draco",
                "check_surface": {"check_route": "/x", "feedback_intent": "f"},
                "a_field_invented_next_quarter": True,
            }
        ],
    }
    with _serving(payload) as client:
        read = fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)

    assert [row.id for row in read.rows] == ["draco"]


async def test_the_catalog_path_is_appended_to_the_configured_engine_url() -> None:
    seen: list[str] = []

    def _record(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"object": "list", "data": []})

    with _client(_record) as client:
        fetch_engine_benchmarks("https://engine.test/", client=client)

    assert seen == ["https://engine.test/v1/benchmarks"]


# --- refusing to guess when the catalogue cannot be read -------------------------------------


async def test_a_transport_failure_is_reported_as_a_seed_error() -> None:
    # INVARIANT: an httpx exception never escapes the seed module. The deploy log must name the
    # thing that failed, not leak a library's internals.
    with _refusing(httpx.ConnectError("no route to host")) as client:
        with pytest.raises(EngineCatalogUnavailable, match="engine.test"):
            fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)


async def test_an_error_status_is_reported_as_a_seed_error() -> None:
    with _serving({"detail": "down"}, status=503) as client:
        with pytest.raises(EngineCatalogUnavailable, match="503"):
            fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)


async def test_a_body_that_is_not_json_is_reported_as_a_seed_error() -> None:
    with _client(lambda request: httpx.Response(200, text="<html>proxy error</html>")) as client:
        with pytest.raises(EngineCatalogUnavailable):
            fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)


async def test_a_catalog_entry_missing_a_displayed_field_is_reported_and_skipped() -> None:
    # WHY reported rather than fatal: one unreadable entry must not cost every other benchmark
    # its refresh. The board keeps that one benchmark's old text and names it in the deploy log.
    payload = {
        "object": "list",
        "data": [
            {"id": "draco", "revision": "rev"},
            {"id": "ifeval", "title": "IFEval", "description": "Text.", "revision": "rev-ifeval"},
        ],
    }
    with _serving(payload) as client:
        read = fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)

    assert [row.id for row in read.rows] == ["ifeval"]
    assert read.rejected == ["draco"]


async def test_a_document_that_is_not_a_catalog_at_all_is_a_seed_error() -> None:
    # INVARIANT: a missing envelope is not a partial read — there is nothing to skip past, so
    # it fails rather than seeding an empty board.
    with _serving({"totally": "unrelated"}) as client:
        with pytest.raises(EngineCatalogUnavailable, match="unreadable catalog"):
            fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)


# --- the Engine is the only copy, not merely the preferred one -------------------------------


async def test_an_engine_row_wins_over_a_configured_row_with_the_same_id(
    tortoise_db: None,
) -> None:
    # INVARIANT: this is what makes the Engine the ONLY copy. A deploy that reintroduces prose
    # under a published id is ignored, so the text cannot drift back into configuration.
    configured = load_benchmarks_json(
        '[{"id":"draco","display_name":"Stale DRACO","description":"Hand-typed copy"}]'
    )
    with _serving(_CATALOG) as client:
        report = await seed_from_sources(
            engine_url=ENGINE_URL, configured=configured, client=client, retry_delay=0
        )

    draco = await Benchmark.get(id="draco")
    assert draco.display_name == "DRACO"
    assert draco.description == "A 100-task DRACO reproduction with official score arithmetic."
    assert report.shadowed == ["draco"]


async def test_a_configured_row_the_engine_does_not_publish_is_kept(tortoise_db: None) -> None:
    # WHY: the legacy demo entries predate the Engine catalogue and have no Engine counterpart.
    configured = load_benchmarks_json(
        '[{"id":"hle","display_name":"News Hallucinations","description":"OpenMined HLE"}]'
    )
    with _serving(_CATALOG) as client:
        await seed_from_sources(engine_url=ENGINE_URL, configured=configured, client=client)

    assert sorted(row.id for row in await Benchmark.all()) == ["draco", "hle", "ifeval"]


async def test_the_seeded_revision_is_the_catalog_revision(tortoise_db: None) -> None:
    # INVARIANT: a submission carries the Engine's revision and the board ranks per revision.
    # Both values now come from one response, so they cannot drift apart the way a hand-copied
    # chart value did.
    configured = load_benchmarks_json('[{"id":"draco","display_name":"X","revision":"stale"}]')
    with _serving(_CATALOG) as client:
        await seed_from_sources(engine_url=ENGINE_URL, configured=configured, client=client)

    assert (await Benchmark.get(id="draco")).revision == "rev-draco"


# --- what happens when the Engine is unreachable at deploy -----------------------------------


async def test_an_unreachable_engine_leaves_an_already_seeded_board_untouched(
    tortoise_db: None,
) -> None:
    # WHY not fail the deploy: re-seeding refreshes a populated board, so blocking a Scoreboard
    # release on an unrelated service's health would cost availability and buy nothing.
    await seed_benchmarks(
        load_benchmarks_json(
            '[{"id":"draco","display_name":"DRACO","description":"Kept","revision":"rev-draco"}]'
        )
    )
    configured = load_benchmarks_json('[{"id":"hle","display_name":"News Hallucinations"}]')

    with _refusing(httpx.ConnectError("down")) as client:
        report = await seed_from_sources(
            engine_url=ENGINE_URL, configured=configured, client=client, retry_delay=0
        )

    assert (await Benchmark.get(id="draco")).description == "Kept"
    assert await Benchmark.filter(id="hle").exists()
    assert report.engine_error is not None
    assert report.bootstrap_failed is False


async def test_an_unreachable_engine_fails_when_no_row_carries_a_revision(
    tortoise_db: None,
) -> None:
    # INVARIANT: only a benchmark the Engine published carries a revision, so "no row has one"
    # means no successful seed has ever run. Exiting zero there would publish a board holding
    # nothing but legacy demo entries and call it a success.
    configured = load_benchmarks_json('[{"id":"hle","display_name":"News Hallucinations"}]')

    with _refusing(httpx.ConnectError("down")) as client:
        report = await seed_from_sources(
            engine_url=ENGINE_URL, configured=configured, client=client, retry_delay=0
        )

    assert report.bootstrap_failed is True


async def test_no_configured_engine_url_seeds_only_the_configured_rows(tortoise_db: None) -> None:
    # WHY: a local or test deployment may run the board without an Engine at all.
    configured = load_benchmarks_json('[{"id":"hle","display_name":"News Hallucinations"}]')

    report = await seed_from_sources(engine_url=None, configured=configured)

    assert [row.id for row in await Benchmark.all()] == ["hle"]
    assert report.engine_error is None
    assert report.bootstrap_failed is False


# --- review findings: the promise must hold when things go wrong too ------------------------


async def test_httpx_is_a_runtime_dependency_not_a_dev_one() -> None:
    # INVARIANT: the seed job runs inside the production image, which is built with
    # `uv sync --frozen --no-dev`. A dev-group-only dependency imported by scoreboard.seed is a
    # ModuleNotFoundError at deploy that no test suite can see, because tests install the dev
    # group. Every import in the shipped package must be declared under [project.dependencies].
    manifest = tomllib.loads(
        (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )
    runtime = {
        requirement.split(">")[0].split("=")[0].split("[")[0].strip()
        for requirement in manifest["project"]["dependencies"]
    }

    assert "httpx" in runtime


async def test_an_unreachable_engine_cannot_let_configuration_overwrite_an_engine_row(
    tortoise_db: None,
) -> None:
    # INVARIANT: this is OME-904 reproduced by its own fix. The shadowing rule needs the
    # catalogue to know what to shadow WITH; when the fetch fails it shadows nothing, and the
    # deploy's own stale draco entry would overwrite the good row with a null description.
    # A row carrying a revision is Engine-owned, and configuration may not overwrite one the
    # Engine did not publish in this same pass.
    await seed_benchmarks(
        load_benchmarks_json(
            '[{"id":"draco","display_name":"DRACO","description":"Good text",'
            '"revision":"rev-draco"}]'
        )
    )
    configured = load_benchmarks_json('[{"id":"draco","display_name":"Stale DRACO"}]')

    with _refusing(httpx.ConnectError("down")) as client:
        report = await seed_from_sources(
            engine_url=ENGINE_URL, configured=configured, client=client, retry_delay=0
        )

    draco = await Benchmark.get(id="draco")
    assert draco.description == "Good text"
    assert draco.display_name == "DRACO"
    assert report.refused == ["draco"]


async def test_configuration_may_never_assert_a_revision_the_engine_did_not_publish(
    tortoise_db: None,
) -> None:
    # INVARIANT: a revision is the Engine's claim about its own benchmark. Configuration
    # asserting one is the hand-copied second copy this ticket deletes, so it is refused and
    # named rather than written.
    configured = load_benchmarks_json(
        '[{"id":"draco","display_name":"Stale DRACO","revision":"stale-rev"}]'
    )

    with _refusing(httpx.ConnectError("down")) as client:
        report = await seed_from_sources(
            engine_url=ENGINE_URL, configured=configured, client=client, retry_delay=0
        )

    assert await Benchmark.filter(id="draco").exists() is False
    assert report.refused == ["draco"]


async def test_the_bootstrap_guard_cannot_be_satisfied_by_this_passs_own_writes(
    tortoise_db: None,
) -> None:
    # INVARIANT: the guard asks "has a successful Engine seed ever run against this database",
    # so it must read the database BEFORE this pass writes to it. Reading afterwards lets the
    # pass count its own rows and call an empty board healthy.
    configured = load_benchmarks_json(
        '[{"id":"draco","display_name":"DRACO","revision":"stale-rev"},'
        '{"id":"hle","display_name":"News Hallucinations"}]'
    )

    with _refusing(httpx.ConnectError("down")) as client:
        report = await seed_from_sources(
            engine_url=ENGINE_URL, configured=configured, client=client, retry_delay=0
        )

    assert report.bootstrap_failed is True


async def test_an_unconfigured_engine_url_names_every_entry_claiming_to_be_an_engine_benchmark(
    tortoise_db: None,
) -> None:
    # WHY: the likeliest misconfiguration is a deploy repo that upgrades the chart without
    # adding engineUrl. Nothing is fetched, so nothing errors, and the board would quietly seed
    # the old list and exit 0 — the original bug with no log line to find it by.
    configured = load_benchmarks_json(
        '[{"id":"draco","display_name":"DRACO","revision":"stale-rev"}]'
    )

    report = await seed_from_sources(engine_url=None, configured=configured)

    assert report.refused == ["draco"]
    assert await Benchmark.filter(id="draco").exists() is False


async def test_one_unusable_entry_does_not_reject_the_whole_catalog() -> None:
    # WHY: rejecting the batch means every untouched benchmark silently keeps its old text
    # because one of them grew a focus line past the board's column width.
    payload = {
        "object": "list",
        "data": [
            {
                "id": "draco",
                "title": "DRACO",
                "description": "Text.",
                "revision": "rev-draco",
                "focus": "x" * 200,
            },
            {"id": "ifeval", "title": "IFEval", "description": "Text.", "revision": "rev-ifeval"},
        ],
    }
    with _serving(payload) as client:
        read = fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)

    assert [row.id for row in read.rows] == ["ifeval"]
    assert read.rejected == ["draco"]


async def test_a_redirect_is_followed_rather_than_reported_as_a_failure() -> None:
    # WHY: an http->https or trailing-slash redirect at the ingress is ordinary. Treating one
    # as an outage means the board never updates again and never says why.
    def _redirect(request: httpx.Request) -> httpx.Response:
        if request.url.scheme == "http":
            return httpx.Response(301, headers={"location": "https://engine.test/v1/benchmarks"})
        return httpx.Response(200, json=_CATALOG)

    with _client(_redirect) as client:
        read = fetch_engine_benchmarks("http://engine.test", client=client)

    assert [row.id for row in read.rows] == ["draco", "ifeval"]


async def test_a_body_that_is_not_valid_utf8_is_reported_as_a_seed_error() -> None:
    # INVARIANT: `.json()` raises UnicodeDecodeError here, not JSONDecodeError. Both are
    # ValueErrors, so an uncaught one used to surface as a command-line usage error — the deploy
    # log blamed the operator's arguments for a mangled Engine response.
    with _client(lambda request: httpx.Response(200, content=b'{"a": "\xff\xfe"}')) as client:
        with pytest.raises(EngineCatalogUnavailable):
            fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)


async def test_a_transient_failure_is_retried_before_the_engine_is_called_unreachable() -> None:
    # WHY: a Helm upgrade that rolls Scoreboard and Engine together can land this single GET in
    # the Engine's restart window. Exiting 0 is right for a populated board, but it also means
    # Kubernetes never retries the Job, so one unlucky second costs a whole release.
    attempts: list[int] = []

    def _flaky(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ConnectError("still starting")
        return httpx.Response(200, json=_CATALOG)

    with _client(_flaky) as client:
        read = fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)

    assert len(attempts) == 3
    assert [row.id for row in read.rows] == ["draco", "ifeval"]


async def test_a_client_error_is_not_retried() -> None:
    # WHY: a 404 does not become a 200 by asking again; retrying only delays the deploy.
    attempts: list[int] = []

    def _missing(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(404)

    with _client(_missing) as client:
        with pytest.raises(EngineCatalogUnavailable, match="404"):
            fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)

    assert len(attempts) == 1


# --- the in-process adapter: a local stack imports the registry instead of fetching it -------


async def test_registry_rows_are_engine_rows_not_configuration(tortoise_db: None) -> None:
    # INVARIANT: a local stack (the pip-installable runtime) runs Engine and board in one venv,
    # so it reads the registry by import rather than over HTTP. Those rows are just as
    # Engine-owned as fetched ones — passing them as `configured` would trip the refusal rule
    # (they carry revisions) and seed an empty local leaderboard.
    engine_rows = load_benchmarks_json(
        '[{"id":"draco","display_name":"DRACO","description":"From the registry",'
        '"revision":"rev-draco","focus":"Research reports with citations"}]'
    )

    report = await seed_from_sources(engine_url=None, engine_rows=engine_rows, configured=[])

    draco = await Benchmark.get(id="draco")
    assert draco.description == "From the registry"
    assert draco.revision == "rev-draco"
    assert draco.focus == "Research reports with citations"
    assert report.refused == []
    assert report.engine_error is None


async def test_supplied_registry_rows_still_win_over_configuration(tortoise_db: None) -> None:
    engine_rows = load_benchmarks_json('[{"id":"draco","display_name":"DRACO"}]')
    configured = load_benchmarks_json('[{"id":"draco","display_name":"Stale"}]')

    report = await seed_from_sources(
        engine_url=None, engine_rows=engine_rows, configured=configured
    )

    assert (await Benchmark.get(id="draco")).display_name == "DRACO"
    assert report.shadowed == ["draco"]


async def test_supplied_registry_rows_are_used_instead_of_fetching(tortoise_db: None) -> None:
    # WHY: the local stack has no Engine URL at all, and must never reach the network to seed.
    def _explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the in-process adapter must not make an HTTP request")

    engine_rows = load_benchmarks_json('[{"id":"draco","display_name":"DRACO"}]')

    with _client(_explode) as client:
        report = await seed_from_sources(
            engine_url=ENGINE_URL, engine_rows=engine_rows, configured=[], client=client
        )

    assert [row.id for row in report.seeded] == ["draco"]


# --- review findings: the catalogue this parser will actually meet ---------------------------


async def test_the_real_engine_response_parses_into_every_board_row() -> None:
    # WHY a recorded fixture: every other test here feeds this parser a payload written in this
    # repo, so they prove the parser agrees with ITSELF. The bug this ticket fixes lived in a
    # deploy-time path no test executed. `engine_catalog.json` is the actual body
    # `rest/benchmarks.py` assembles from the real registry — regenerate it with the header in
    # that file when the Engine's catalogue shape changes.
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures" / "engine_catalog.json").read_text(
            encoding="utf-8"
        )
    )

    with _serving(payload) as client:
        read = fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)

    # WHY not a hardcoded id list: benchmarks get added, and a test that names them turns every
    # new board into a failure here. The invariant is that EVERY published benchmark survives
    # the trip — that is what breaks when the Engine renames or outgrows a field.
    assert read.rejected == []
    assert len(read.rows) == len(payload["data"])
    assert {row.id for row in read.rows} == {entry["id"] for entry in payload["data"]}
    draco = next(row for row in read.rows if row.id == "draco")
    assert draco.display_name == "DRACO"
    assert draco.description is not None
    assert draco.description.startswith("A 100-task DRACO reproduction")
    assert draco.revision
    assert draco.focus == "Research reports with citations"
    # INVARIANT: the Engine publishes keys this board does not store (case_count, href,
    # check_surface). Meeting one must never cost a benchmark its row.
    assert {"case_count", "href", "check_surface"} <= set(payload["data"][0])


async def test_an_auth_proxy_sign_in_page_is_diagnosed_rather_than_just_rejected() -> None:
    # WHY: the obvious hostname to paste into engineUrl is the PUBLIC one, and that host sits
    # behind Cloudflare Access — verified 2026-08-20, it answers 200 with an HTML sign-in page.
    # Every layer then behaves correctly and the feature is silently off, so the error message
    # is the only thing standing between an operator and a long afternoon.
    page = "<!DOCTYPE html><html><head><title>Sign in ・ Cloudflare Access</title></head></html>"
    with _client(
        lambda request: httpx.Response(
            200, text=page, headers={"content-type": "text/html; charset=utf-8"}
        )
    ) as client:
        with pytest.raises(EngineCatalogUnavailable, match="text/html") as raised:
            fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)

    assert "in-cluster" in str(raised.value)


# --- owner decision: a missing description costs text, never the whole benchmark -------------


@pytest.mark.parametrize("prose", ["", "   "])
async def test_a_benchmark_without_prose_still_registers(prose: str) -> None:
    # WHY not reject it: the consequence of rejecting is a benchmark MISSING from the board —
    # no row, and a submission against it refused — which is far worse than a row that reads
    # plain. The Engine already refuses to define a benchmark without a description, so this
    # side is deliberately the lenient one: require it where it is written, tolerate it where
    # it is read.
    payload = {
        "object": "list",
        "data": [{"id": "draco", "title": "DRACO", "description": prose, "revision": "rev"}],
    }
    with _serving(payload) as client:
        read = fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)

    assert read.rejected == []
    assert [row.id for row in read.rows] == ["draco"]
    # INVARIANT: stored as absent, NOT as a placeholder sentence. The reader-facing wording
    # ("No description published.") belongs to the client that renders it, in one place — a
    # placeholder written into the database could never be told apart from real text later.
    assert read.rows[0].description is None


async def test_a_benchmark_with_no_description_field_at_all_still_registers() -> None:
    payload = {
        "object": "list",
        "data": [{"id": "draco", "title": "DRACO", "revision": "rev"}],
    }
    with _serving(payload) as client:
        read = fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)

    assert read.rejected == []
    assert read.rows[0].description is None


async def test_an_entry_missing_its_identity_is_still_rejected() -> None:
    # INVARIANT: leniency stops at the fields that make a row addressable. Without an id, a
    # title or a revision there is nothing to register or rank; those still fail the entry.
    payload = {"object": "list", "data": [{"title": "DRACO", "description": "Text."}]}
    with _serving(payload) as client:
        read = fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)

    assert read.rows == []
    assert read.rejected == ["entry #0"]


# --- OME-894: deployment-owned visibility on an Engine-published benchmark --------------------
# The Engine does not publish a `visibility` — it is a Scoreboard concern, not an Engine one — so
# a published row can only get one from deployment config. Without the merge below, the entry
# challenge (healthbench-worst30, Engine-published) can never be made private, and a board flipped
# by hand is reset to public by the next deploy. Found in review of PR #719.


async def test_configured_visibility_is_merged_into_a_published_row(tortoise_db: None) -> None:
    published = SeedBenchmark(
        id="healthbench-worst30", display_name="HealthBench", revision="rev-1"
    )
    configured = SeedBenchmark(
        id="healthbench-worst30", display_name="ignored", visibility="private"
    )

    report = await seed_from_sources(
        configured=[configured], engine_url=None, engine_rows=[published]
    )

    seeded = {row.id: row for row in report.seeded}
    assert seeded["healthbench-worst30"].visibility == "private"
    # Still shadowed: the Engine remains the authority for TEXT. Only visibility is lifted.
    assert report.shadowed == ["healthbench-worst30"]
    assert seeded["healthbench-worst30"].display_name == "HealthBench"


async def test_a_published_row_without_configured_visibility_keeps_what_is_stored(
    tortoise_db: None,
) -> None:
    # INVARIANT: an omitted visibility means "leave it alone", never "reset to public". This is
    # the guard that stops a routine deploy un-privating a live challenge.
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id="healthbench-worst30",
        display_name="HealthBench",
        revision="rev-1",
        visibility="private",
    )

    published = SeedBenchmark(
        id="healthbench-worst30", display_name="HealthBench", revision="rev-1"
    )
    report = await seed_from_sources(configured=[], engine_url=None, engine_rows=[published])

    assert report.seeded[0].visibility == "private"


async def test_configured_visibility_can_flip_a_board_back_to_public(tortoise_db: None) -> None:
    # Recoverable in both directions: a mis-seeded private board must not be stuck.
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id="healthbench-worst30",
        display_name="HealthBench",
        revision="rev-1",
        visibility="private",
    )

    published = SeedBenchmark(
        id="healthbench-worst30", display_name="HealthBench", revision="rev-1"
    )
    configured = SeedBenchmark(
        id="healthbench-worst30", display_name="ignored", visibility="public"
    )
    report = await seed_from_sources(
        configured=[configured], engine_url=None, engine_rows=[published]
    )

    assert report.seeded[0].visibility == "public"


async def test_visibility_still_applies_when_the_engine_catalog_is_unavailable(
    tortoise_db: None,
) -> None:
    # INVARIANT: visibility is DEPLOYMENT-owned, so it must not depend on the Engine answering.
    # Previously a transient catalogue failure left `published_rows` empty, the configured row was
    # refused for claiming an Engine-owned id, and the job exited 0 — so the deploy meant to make
    # the entry challenge private reported success while leaving every submission exposed.
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id="healthbench-worst30",
        display_name="HealthBench",
        revision="rev-1",
        visibility="public",
    )

    report = await seed_from_sources(
        configured=[
            SeedBenchmark(id="healthbench-worst30", display_name="x", visibility="private")
        ],
        engine_url=ENGINE_URL,
        client=_client(lambda request: httpx.Response(503)),
        retry_delay=0,
    )

    assert report.engine_error is not None
    assert (await store.list_benchmarks())[0].visibility == "private"


async def test_an_unknown_benchmark_gets_no_visibility_row_of_its_own(
    tortoise_db: None,
) -> None:
    # Applying visibility must never CREATE a benchmark. A configured id the board has never seen,
    # during a catalogue outage, is still refused — text and existence stay Engine-owned.
    store = ScoreStore()

    report = await seed_from_sources(
        configured=[
            SeedBenchmark(id="ghost", display_name="x", visibility="private", revision="r")
        ],
        engine_url=ENGINE_URL,
        client=_client(lambda request: httpx.Response(503)),
        retry_delay=0,
    )

    assert report.refused == ["ghost"]
    assert await store.list_benchmarks() == []
