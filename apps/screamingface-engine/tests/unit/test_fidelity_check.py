"""The fidelity check says which Fidelity Records can still be trusted today (OME-1471).

FEATURE: a Fidelity Record freezes a verdict at audit time; the catalogue moves. The script
compares each record's fingerprint (our computed Benchmark fingerprint + the pinned harness
link) with today's declaration and prints fresh / stale / no record / orphan record. These tests
drive the pure half (parsing and comparing) with tmp_path records and a hand-built catalogue, so
they run without the inspect extra; the catalogue reader has its own test under tests/unit/inspect.
"""

from __future__ import annotations

import importlib.util
import socket
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_ENGINE: Path = Path(__file__).resolve().parents[2]
_SCRIPT: Path = _ENGINE / "scripts" / "fidelity_check.py"

_IFEVAL_HARNESS = (
    "https://github.com/josejg/instruction_following_eval/tree/"
    "0c495b2f95155e8b10acb919ae283bfb4d5be6e2"
)
_FRONT_MATTER = """---
benchmark: {benchmark}
origin: {origin}
verdict: {verdict}
verdict_reason: "{verdict_reason}"
audited: 2026-11-06
audited_at: 3499efbb8
fingerprint:
  benchmark: {fingerprint}
  harness_url: {harness_url}
references:
  paper: {paper}
  original_harness: {harness_url}
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: {parity_test}
parity_test_reason: "{parity_test_reason}"
---

# body the script never reads
"""


def _module() -> ModuleType:
    """Load the script by path, as `just engine fidelity-check` runs it."""

    spec = importlib.util.spec_from_file_location("fidelity_check", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # WHY: dataclasses resolve `from __future__` annotations through sys.modules; a module
    # loaded by path is not registered there unless we do it.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_record(
    records: Path,
    *,
    benchmark: str = "ifeval",
    origin: str = "screamingface",
    stem: str | None = None,
    verdict: str = "comparable-to-paper",
    verdict_reason: str = "",
    fingerprint: str = "ada07458a23c55ab",
    harness_url: str = _IFEVAL_HARNESS,
    paper: str = "https://arxiv.org/abs/2311.07911v1",
    parity_test: str = "tests/unit/inspect/test_local_task_ifeval_parity.py",
    parity_test_reason: str = "",
    drop_key: str | None = None,
) -> Path:
    """One record file with every key valid unless an argument says otherwise."""

    text: str = _FRONT_MATTER.format(
        benchmark=benchmark,
        origin=origin,
        verdict=verdict,
        verdict_reason=verdict_reason,
        fingerprint=fingerprint,
        harness_url=harness_url,
        paper=paper,
        parity_test=parity_test,
        parity_test_reason=parity_test_reason,
    )
    if drop_key is not None:
        text = "\n".join(line for line in text.splitlines() if not line.startswith(f"{drop_key}:"))
    path: Path = records / f"{stem or benchmark}.md"
    path.write_text(text + "\n")
    return path


@pytest.fixture
def engine_root(tmp_path: Path) -> Path:
    """A fake Engine root holding the one parity test file the default record names."""

    (tmp_path / "tests" / "unit" / "inspect").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "inspect" / "test_local_task_ifeval_parity.py").write_text("")
    (tmp_path / "docs" / "benchmarks-fidelity").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def records(engine_root: Path) -> Path:
    return engine_root / "docs" / "benchmarks-fidelity"


def _declared(module: ModuleType, **overrides: object) -> Mapping[str, object]:
    """Today's catalogue as the script sees it: IFEval exactly as the default record says."""

    values: dict[str, object] = {
        "benchmark": "ifeval",
        "origin": "screamingface",
        "fingerprint": "ada07458a23c55ab",
        "harness_url": _IFEVAL_HARNESS,
    }
    values.update(overrides)
    declared = module.Declared(**values)
    return {str(declared.benchmark): declared}


def _rows(module: ModuleType, records: Path, engine_root: Path, declared: Mapping[str, object]):
    loaded, malformed = module.load_records(records, engine_root)
    assert malformed == []
    return {row.benchmark: row for row in module.compare(loaded, declared)}


def test_a_record_matching_todays_declaration_is_fresh(records: Path, engine_root: Path) -> None:
    module = _module()
    _write_record(records)

    rows = _rows(module, records, engine_root, _declared(module))

    assert rows["ifeval"].status == "fresh"
    assert rows["ifeval"].moved == ()
    assert rows["ifeval"].verdict == "comparable-to-paper"
    assert rows["ifeval"].parity == "yes"


def test_a_moved_fingerprint_makes_the_record_stale_and_names_both_values(
    records: Path, engine_root: Path
) -> None:
    """INVARIANT: a verdict is never shown as current when the exam it judged has changed."""

    module = _module()
    _write_record(records)

    rows = _rows(module, records, engine_root, _declared(module, fingerprint="1f3e9c0d2b4a6e8f"))

    assert rows["ifeval"].status == "stale"
    assert rows["ifeval"].moved == ("fingerprint ada07458a23c55ab → 1f3e9c0d2b4a6e8f",)


def test_a_moved_harness_link_makes_the_record_stale_and_names_both_urls(
    records: Path, engine_root: Path
) -> None:
    module = _module()
    _write_record(records)
    new_url = "https://github.com/josejg/instruction_following_eval/tree/abcdef1234567"

    rows = _rows(module, records, engine_root, _declared(module, harness_url=new_url))

    assert rows["ifeval"].status == "stale"
    assert rows["ifeval"].moved == (f"harness_url {_IFEVAL_HARNESS} → {new_url}",)


def test_both_values_moving_lists_both(records: Path, engine_root: Path) -> None:
    module = _module()
    _write_record(records)
    new_url = "https://github.com/josejg/instruction_following_eval/tree/abcdef1234567"

    rows = _rows(
        module,
        records,
        engine_root,
        _declared(module, fingerprint="1f3e9c0d2b4a6e8f", harness_url=new_url),
    )

    assert len(rows["ifeval"].moved) == 2
    assert rows["ifeval"].moved[0].startswith("fingerprint ")
    assert rows["ifeval"].moved[1].startswith("harness_url ")


def test_a_benchmark_without_a_record_is_listed_as_no_record(
    records: Path, engine_root: Path
) -> None:
    module = _module()

    rows = _rows(module, records, engine_root, _declared(module))

    assert rows["ifeval"].status == "no record"
    assert rows["ifeval"].verdict == ""
    assert rows["ifeval"].parity == ""


def test_a_record_for_an_unknown_benchmark_is_an_orphan(records: Path, engine_root: Path) -> None:
    """A renamed or retired Benchmark must not leave a ghost verdict behind."""

    module = _module()
    _write_record(records, benchmark="inspect-gone")

    rows = _rows(module, records, engine_root, _declared(module))

    assert rows["inspect-gone"].status == "orphan record"
    assert rows["ifeval"].status == "no record"


def test_rows_come_out_sorted_by_benchmark_id(records: Path, engine_root: Path) -> None:
    module = _module()
    _write_record(records, benchmark="zeta")
    declared = dict(_declared(module))
    declared["alpha"] = module.Declared(
        benchmark="alpha", origin="inspect_evals", fingerprint="0" * 16, harness_url=None
    )

    loaded, _ = module.load_records(records, engine_root)
    ordered = [row.benchmark for row in module.compare(loaded, declared)]

    assert ordered == ["alpha", "ifeval", "zeta"]


def test_parity_none_with_a_reason_is_reported_as_none(records: Path, engine_root: Path) -> None:
    module = _module()
    _write_record(records, parity_test="none", parity_test_reason="judge-graded")

    rows = _rows(module, records, engine_root, _declared(module))

    assert rows["ifeval"].parity == "none: judge-graded"


def test_a_parity_path_that_does_not_exist_is_missing_and_fails_the_run(
    records: Path, engine_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The parity column is only honest if the file it names is really there."""

    module = _module()
    _write_record(records, parity_test="tests/unit/test_deleted_parity.py")

    code: int = module.main(
        ["--records", str(records), "--engine-root", str(engine_root)],
        declared=_declared(module),
    )

    assert code == 1
    assert "MISSING tests/unit/test_deleted_parity.py" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("kwargs", "named_key"),
    [
        ({"drop_key": "verdict"}, "verdict"),
        ({"verdict": "comparable"}, "verdict"),
        ({"stem": "ifeval-copy"}, "benchmark"),
        ({"verdict": "unverified"}, "verdict_reason"),
        ({"parity_test": "none"}, "parity_test_reason"),
        ({"fingerprint": "ADA07458A23C55AB"}, "fingerprint.benchmark"),
        ({"paper": "https://arxiv.org/abs/2311.07911"}, "references.paper"),
        ({"origin": "hand-built"}, "origin"),
        ({"verdict": "comparable-to-inspect"}, "comparable-to-inspect"),
    ],
    ids=[
        "missing-key",
        "unknown-verdict",
        "stem-differs-from-benchmark",
        "unverified-without-reason",
        "parity-none-without-reason",
        "fingerprint-not-lower-hex",
        "unpinned-reference-url",
        "unknown-origin",
        "comparable-to-inspect-on-a-screamingface-benchmark",
    ],
)
def test_a_malformed_record_is_named_with_file_and_key_and_never_reads_as_fresh(
    records: Path,
    engine_root: Path,
    capsys: pytest.CaptureFixture[str],
    kwargs: dict[str, Any],
    named_key: str,
) -> None:
    """INVARIANT: a broken record cannot pass for a good one."""

    module = _module()
    path: Path = _write_record(records, **kwargs)

    loaded, malformed = module.load_records(records, engine_root)
    code: int = module.main(
        ["--records", str(records), "--engine-root", str(engine_root)],
        declared=_declared(module),
    )

    assert loaded == {}
    assert len(malformed) == 1
    assert path.name in malformed[0] and named_key in malformed[0]
    assert code == 1
    out: str = capsys.readouterr().out
    assert "fresh" not in out.split("ifeval", 1)[-1].splitlines()[0]


def test_the_template_and_the_readme_are_not_records(records: Path, engine_root: Path) -> None:
    module = _module()
    (records / "TEMPLATE.md").write_text("---\nbenchmark: <id>\n---\n")
    (records / "README.md").write_text("# Fidelity Records\n")
    _write_record(records)

    loaded, malformed = module.load_records(records, engine_root)

    assert malformed == []
    assert set(loaded) == {"ifeval"}


def test_the_check_opens_no_socket(
    records: Path, engine_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: offline by construction, so it runs in any checkout with no token."""

    module = _module()
    _write_record(records)

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the fidelity check must not open a socket")

    monkeypatch.setattr(socket, "socket", _refuse)
    code: int = module.main(
        ["--records", str(records), "--engine-root", str(engine_root)],
        declared=_declared(module),
    )

    assert code == 0


def test_markdown_output_is_a_github_table_with_a_count_line(
    records: Path, engine_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()
    _write_record(records)

    code: int = module.main(
        ["--records", str(records), "--engine-root", str(engine_root), "--markdown"],
        declared=_declared(module),
    )

    out: str = capsys.readouterr().out
    assert code == 0
    assert out.splitlines()[0].startswith("| benchmark | status |")
    assert "| ifeval | fresh |" in out
    assert "1 fresh" in out and "0 stale" in out and "0 no record" in out


def test_a_record_whose_origin_differs_from_the_declaration_is_stale(
    records: Path, engine_root: Path
) -> None:
    """The verdict vocabulary depends on origin (comparable-to-inspect is Imported-only), so a
    record written for one origin is not current for a Benchmark that now declares the other."""

    module = _module()
    _write_record(records)

    rows = _rows(module, records, engine_root, _declared(module, origin="inspect_evals"))

    assert rows["ifeval"].status == "stale"
    assert rows["ifeval"].moved == ("origin screamingface → inspect_evals",)


def test_comparable_to_inspect_is_accepted_on_an_imported_benchmark(
    records: Path, engine_root: Path
) -> None:
    module = _module()
    _write_record(
        records,
        benchmark="inspect-gsm8k",
        origin="inspect_evals",
        verdict="comparable-to-inspect",
        parity_test="none",
        parity_test_reason="not written yet",
    )

    loaded, malformed = module.load_records(records, engine_root)

    assert malformed == []
    assert loaded["inspect-gsm8k"].verdict == "comparable-to-inspect"
