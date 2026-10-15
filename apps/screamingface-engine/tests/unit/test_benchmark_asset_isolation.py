"""Benchmark asset isolation — running one benchmark must not require any other benchmark's assets.

INVARIANT under test (OME-999): a Runner world carries EVERY registered benchmark, so a benchmark
whose ``install()`` touches its assets eagerly makes every other benchmark's run require them —
a dev who prepared only GDPval could not evaluate it because DRACO's cases.json was missing.
Install registers lazy providers; a benchmark's assets are read on the first resolution of one
of ITS routes, and a missing asset fails there, named by the benchmark that owns it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from screamingface_engine.benchmarks.builtins import BUILTIN_DEPLOYMENT
from screamingface_engine.benchmarks.medxpert.definition import CASES_ROUTE, MEDXPERT
from url4 import RelExpr, Text, expr, render, src
from url4.core.errors import ResolutionError
from url4.peer.server import Url4Node


async def _resolve_data(node: Url4Node, path: str) -> str:
    expression = expr(
        src(RelExpr(path=path, intent=Text("100")), name="result", weight=0.0),
        intent=Text("$result"),
    )
    return (await node.evaluate(render(expression))).text


def test_every_builtin_benchmark_installs_into_a_world_without_any_assets(tmp_path: Path) -> None:
    # The registry-wide pin: install must never read an asset, for ANY registered benchmark —
    # this is the exact call the Runner makes when creating a world, over an empty root.
    node = Url4Node("test")
    BUILTIN_DEPLOYMENT.benchmarks.install(node, assets_root=tmp_path)


@pytest.mark.asyncio
async def test_an_unprepared_benchmark_fails_at_its_own_route_with_its_own_name(
    tmp_path: Path,
) -> None:
    # WHY: laziness must not soften the failure — MedXpertQA without assets still fails
    # loudly, at its own route, named as MedXpertQA, exactly as the eager path failed.
    # (DRACO, then HealthBench, were the subject until OME-1527 moved each to a local inspect
    # Task; MedXpertQA is the last hand-built Benchmark.)
    node = Url4Node("test")
    MEDXPERT.install(node, tmp_path)
    with pytest.raises(ResolutionError, match="MedXpertQA"):
        await _resolve_data(node, CASES_ROUTE)
