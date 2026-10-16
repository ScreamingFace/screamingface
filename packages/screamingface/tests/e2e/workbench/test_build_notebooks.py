from __future__ import annotations

from typing import Any

import nbformat
import pytest
from harness._gating import GOLDENS_DIR
from harness.goldens import GoldenReport, build_candidate, load_golden

from workbench.build_notebooks import (
    NOTEBOOK_DIR,
    build,
    main,
    render_golden_candidate,
    serialize,
)


@pytest.mark.parametrize("path", sorted(GOLDENS_DIR.glob("*.golden.json")), ids=lambda p: p.name)
def test_rendered_golden_recipe_equals_the_harness_builder(path) -> None:
    golden = load_golden(path)
    namespace: dict[str, Any] = {}
    exec("import screamingface as sf\n" + render_golden_candidate(golden), namespace)
    assert namespace["candidate"] == build_candidate(golden)


def test_committed_notebooks_match_the_builder_and_are_output_free() -> None:
    built = build()
    assert "quickstart" in built
    for stem, nb in built.items():
        committed = (NOTEBOOK_DIR / f"{stem}.ipynb").read_text(encoding="utf-8")
        assert committed == serialize(nb), f"{stem}.ipynb is stale; run build_notebooks.py"
        for cell in nbformat.reads(committed, as_version=4).cells:
            assert not cell.get("outputs"), f"{stem}.ipynb has committed outputs"


def test_every_notebook_has_parameters_result_and_target_metadata() -> None:
    for stem, nb in build().items():
        tags = [t for c in nb.cells for t in c.metadata.get("tags", [])]
        assert "parameters" in tags and "workbench-result" in tags, stem
        assert nb.metadata["workbench"]["targets"], stem
        assert nb.metadata["workbench"]["required_result"] == ["trace_ids"], stem


def test_every_code_cell_compiles() -> None:
    for stem, nb in build().items():
        for i, cell in enumerate(nb.cells):
            if cell.cell_type == "code":
                compile(cell.source, f"{stem}[{i}]", "exec")


def test_rebuild_is_byte_identical() -> None:
    first = {stem: serialize(nb) for stem, nb in build().items()}
    second = {stem: serialize(nb) for stem, nb in build().items()}
    assert first == second


def test_check_mode_passes_on_committed_notebooks_and_fails_on_drift(tmp_path) -> None:
    assert main(["--check"]) == 0
    for stem in build():
        (tmp_path / f"{stem}.ipynb").write_text("stale", encoding="utf-8")
    assert main(["--check", "--out", str(tmp_path)]) == 1
    assert main(["--out", str(tmp_path)]) == 0
    assert main(["--check", "--out", str(tmp_path)]) == 0


def test_model_golden_and_long_strings_round_trip() -> None:
    ifeval = load_golden(GOLDENS_DIR / "ifeval.golden.json").model_dump(by_alias=True)
    for field in ("member_specs", "judge_spec", "max_rounds"):
        ifeval.pop(field)
    golden = GoldenReport.model_validate(
        ifeval | {"kind": "model", "models": ["openrouter/microsoft/phi-4"]}
    )
    namespace: dict[str, Any] = {}
    exec("import screamingface as sf\n" + render_golden_candidate(golden), namespace)
    assert namespace["candidate"] == build_candidate(golden)

    prompt = "line one\nline\ttwo  " + "word " * 40 + "x" * 90
    looped = load_golden(GOLDENS_DIR / "ifeval.golden.json")
    spec = looped.member_specs[0].model_copy(update={"prompt": prompt})
    long = looped.model_copy(update={"member_specs": (spec, looped.member_specs[1])})
    namespace = {}
    exec("import screamingface as sf\n" + render_golden_candidate(long), namespace)
    assert namespace["candidate"].members[0].prompt == prompt


def test_the_result_cell_runs_before_any_assertion() -> None:
    """Review Focus 1: a failing assert must still leave trace ids in the bundle, so the
    ``workbench-result`` cell runs before every cell that asserts."""
    for stem, nb in build().items():
        code = [c for c in nb.cells if c.cell_type == "code"]
        at = next(i for i, c in enumerate(code) if "workbench-result" in c.metadata.get("tags", []))
        assert not [c for c in code[:at] if "assert " in c.source], stem
        assert any("assert " in c.source for c in code[at + 1 :]), stem


def test_quickstart_reports_right_after_evaluate() -> None:
    cells = [c for c in build()["quickstart"].cells if c.cell_type == "code"]
    at = next(i for i, c in enumerate(cells) if "workbench-result" in c.metadata.get("tags", []))
    assert "client.evaluate(" in cells[at - 1].source


def _quickstart_code(tag: str | None = None, contains: str | None = None) -> str:
    for cell in build()["quickstart"].cells:
        if cell.cell_type != "code":
            continue
        if tag and tag in cell.metadata.get("tags", []):
            return cell.source
        if contains and contains in cell.source:
            return cell.source
    raise AssertionError(f"no quickstart cell with tag={tag} contains={contains}")


def test_quickstart_always_passes_an_explicit_scoreboard() -> None:
    """Spec §3.1: scoreboard_url is always explicit, never the SDK's hosted default."""
    client_cell = _quickstart_code(contains="sf.Client(")
    assert client_cell.count("sf.Client(") == 1
    assert "sf.Client(engine_url=ENGINE_URL, scoreboard_url=SCOREBOARD_URL)" in client_cell
    namespace: dict[str, Any] = {}
    exec(_quickstart_code(tag="parameters"), namespace)
    assert namespace["SCOREBOARD_URL"].startswith("http://127.0.0.1:")


def test_quickstart_refuses_a_missing_scoreboard() -> None:
    namespace: dict[str, Any] = {}
    exec(_quickstart_code(tag="parameters"), namespace)
    namespace["SCOREBOARD_URL"] = None
    with pytest.raises(ValueError, match="SCOREBOARD_URL"):
        exec(_quickstart_code(contains="sf.Client("), namespace)
