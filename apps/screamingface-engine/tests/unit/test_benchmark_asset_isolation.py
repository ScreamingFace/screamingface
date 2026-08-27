"""Board asset isolation — running one benchmark must not require any other board's assets.

INVARIANT under test (OME-999): a Runner world carries EVERY registered board, so a board
whose ``install()`` touches its assets eagerly makes every other board's run require them —
a dev who prepared only GDPval could not evaluate it because DRACO's cases.json was missing.
Install registers lazy providers; a board's assets are read on the first resolution of one
of ITS routes, and a missing asset fails there, named by the board that owns it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.builtins import BUILTIN_DEPLOYMENT
from screamingface_engine.benchmarks.draco.definition import CANONICAL_EXAM, CASES_ROUTE
from screamingface_engine.benchmarks.draco.runtime import install as install_draco
from url4 import RelUrl, Text, expr, render, src
from url4.core.errors import ResolutionError
from url4.peer.server import Url4Node


async def _resolve_data(node: Url4Node, path: str) -> str:
    expression = expr(
        src(RelUrl(path), name="result", weight=0.0),
        intent=Text("$result"),
    )
    return (await node.evaluate(render(expression))).text


def test_every_builtin_board_installs_into_a_world_without_any_assets(tmp_path: Path) -> None:
    # The registry-wide pin: install must never read an asset, for ANY registered board —
    # this is the exact call the Runner makes when creating a world, over an empty root.
    node = Url4Node("test")
    BUILTIN_DEPLOYMENT.benchmarks.install(node, assets_root=tmp_path)


@pytest.mark.asyncio
async def test_an_unprepared_board_fails_at_its_own_route_with_its_own_name(
    tmp_path: Path,
) -> None:
    # WHY: laziness must not soften the failure — DRACO without assets still fails loudly,
    # at DRACO's route, named as DRACO, exactly as the eager path failed.
    node = Url4Node("test")
    install_draco(node, tmp_path, CANONICAL_EXAM)
    with pytest.raises(ResolutionError, match="DRACO cases"):
        await _resolve_data(node, CASES_ROUTE)


@pytest.mark.asyncio
async def test_a_board_reads_its_assets_once_across_resolutions(tmp_path: Path) -> None:
    # Baked assets are immutable for the process lifetime; the memo must serve every later
    # resolution without re-reading, and both resolutions must serve identical bytes.
    (tmp_path / "criteria").mkdir(parents=True)
    (tmp_path / "rubrics").mkdir()
    cases = [{"id": case_id, "input": f"Question {case_id}"} for case_id in range(1, 101)]
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    for case_id in range(1, 101):
        (tmp_path / "criteria" / f"{case_id}.json").write_text(
            '[{"id":"c1","requirement":"Be correct","criterion_type":"positive"}]',
            encoding="utf-8",
        )
        (tmp_path / "rubrics" / f"{case_id}.json").write_text(
            '{"sections":[{"id":"accuracy","criteria":[{"id":"c1","weight":1}]}]}',
            encoding="utf-8",
        )
    node = Url4Node("test")
    install_draco(node, tmp_path, CANONICAL_EXAM)

    reads: list[Path] = []
    original = Path.read_text

    def counting(self: Path, encoding: str | None = None, errors: str | None = None) -> str:
        reads.append(Path(self))
        return original(self, encoding=encoding, errors=errors)

    try:
        Path.read_text = counting  # type: ignore[method-assign]
        first = await _resolve_data(node, CASES_ROUTE)
        second = await _resolve_data(node, CASES_ROUTE)
    finally:
        Path.read_text = original  # type: ignore[method-assign]

    assert first == second
    assert reads.count(tmp_path / "cases.json") == 1
