"""The provenance rule on a fixture, and the two cross-app key twins (OME-1455, box ⑨).

The strict check over every REGISTERED Benchmark lives in
``tests/unit/inspect/test_benchmark_provenance_conformance.py``, because the imported
Benchmarks register only under the inspect extra and CI runs that directory in the one lane
that installs it. This file holds what the extra-less lane can prove: that the rule itself
names a gap, and that every served provenance key is declared on the two consumers that
cannot import this app — the Scoreboard's seed and the SDK's catalogue decoder.
"""

from __future__ import annotations

import ast
from pathlib import Path

from screamingface_engine.benchmarks import Benchmark, BenchmarkDeclaration, candidate
from screamingface_engine.benchmarks.provenance import (
    PROVENANCE_FIELD_NAMES,
    REQUIRED_PROVENANCE_FIELDS,
    NotPublished,
    provenance_gaps,
)

# parents[3] = apps/, so its parent is the monorepo root (the vocabulary twin's idiom).
_REPO_ROOT = Path(__file__).resolve().parents[3].parent
_SCOREBOARD_SCHEMAS = (
    _REPO_ROOT / "apps" / "scoreboard" / "src" / "scoreboard" / "scores" / "schemas.py"
)
_SDK_CATALOG_CONTRACT = (
    _REPO_ROOT
    / "packages"
    / "screamingface"
    / "src"
    / "screamingface"
    / "_engine"
    / "catalog_contract.py"
)
_SDK_BOOTSTRAP = (
    _REPO_ROOT
    / "packages"
    / "screamingface"
    / "src"
    / "screamingface"
    / "_runtime"
    / "bootstrap.py"
)


def _probe(**provenance: object) -> Benchmark:
    """A fixture Benchmark that is NOT on the allowlist, so the rule applies to it."""

    return Benchmark(
        id="example-probe",
        title="Example Probe",
        description="One non-comparable structural probe.",
        revision="example-probe-v1",
        case_count=1,
        build=lambda selected: candidate("Say hello.", web_search=False),
        declaration=BenchmarkDeclaration(
            failure_policy="coverage_declare", interaction="single_shot", difficulty="easy"
        ),
        **provenance,  # type: ignore[arg-type]
    )


def test_a_benchmark_with_a_silent_gap_is_named_and_a_full_one_is_not() -> None:
    # The rule the registry-wide test applies, checked on a fixture so the assertion is
    # exercised in the extra-less lane too, and while every registered id is grandfathered.
    assert provenance_gaps(_probe()) == list(REQUIRED_PROVENANCE_FIELDS)
    assert (
        provenance_gaps(
            _probe(
                paper_url="https://arxiv.org/abs/2600.00001",
                authors="Probe et al., 2026",
                citation="@misc{probe2026}",
                harness_url="https://github.com/acme/probe/tree/v1.0.0/eval",
                license="MIT",
                human_baseline=NotPublished(reason="no human study"),
                frontier_score=NotPublished(reason="too new"),
                notebook="00_quickstart",
            )
        )
        == []
    )


def _class_fields(tree: ast.Module, class_name: str) -> set[str] | None:
    """The annotated field names of one class, read from its source."""

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                item.target.id
                for item in node.body
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            }
    return None


def _string_tuple(tree: ast.Module, name: str) -> set[str] | None:
    """The string members of one module-level tuple constant, read from its source."""

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and isinstance(node.value, ast.Tuple)
        ):
            return {
                element.value
                for element in node.value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    return None


def test_every_served_provenance_key_is_a_field_the_scoreboard_seeds() -> None:
    """F4: the Scoreboard's seed ignores unknown keys by design, so a served key it does not
    declare is dropped silently, with a deploy that exits 0.

    WHY assert it on this side, by parsing the Scoreboard's source: the two apps have
    separate virtualenvs and neither can import the other; the producer is the side that
    can break the contract, so the producer pins it (the catalogue-vocabulary twin's idiom).
    AIDEV-NOTE: adding a provenance field means adding it to `ProvenanceSchema` in the
    Scoreboard's `scores/schemas.py` in the same pull request — that one class is both the
    seed's reader and the API's response, so there is no second copy to update.
    """

    assert _SCOREBOARD_SCHEMAS.exists(), "Scoreboard scores/schemas.py moved — update the bind"
    tree = ast.parse(_SCOREBOARD_SCHEMAS.read_text(encoding="utf-8"))
    seeded: set[str] | None = _class_fields(tree, "ProvenanceSchema")
    assert seeded is not None, (
        "Scoreboard scores/schemas.py has no ProvenanceSchema model — update the bind"
    )
    served: set[str] = set(PROVENANCE_FIELD_NAMES)
    assert served <= seeded, f"served but not seeded: {sorted(served - seeded)}"


def test_every_served_provenance_key_is_one_the_sdk_decodes_and_only_there() -> None:
    """The SDK's decoder holds the one copy of the key list on that side; the local seed
    twin reads from it rather than keeping a copy of its own.

    WHY: a 14th Engine key that the decoder does not list is never surfaced on
    `Benchmark.provenance` and is silently dropped from a local board — the same F4 hole, on
    the other consumer (review finding on PR 1236).
    AIDEV-NOTE: adding a provenance field means adding it to one of the three key tuples in
    the SDK's `_engine/catalog_contract.py` in the same pull request.
    """

    assert _SDK_CATALOG_CONTRACT.exists(), "SDK catalog_contract.py moved — update the bind"
    tree = ast.parse(_SDK_CATALOG_CONTRACT.read_text(encoding="utf-8"))
    decoded: set[str] = set()
    for name in ("_PROVENANCE_TEXT_KEYS", "_PROVENANCE_HANDLE_KEYS", "_PROVENANCE_SCORE_KEYS"):
        members: set[str] | None = _string_tuple(tree, name)
        assert members is not None, f"SDK {name} not found — update the bind"
        decoded |= members
    assert decoded == set(PROVENANCE_FIELD_NAMES), (
        f"served but not decoded: {sorted(set(PROVENANCE_FIELD_NAMES) - decoded)}; "
        f"decoded but never served: {sorted(decoded - set(PROVENANCE_FIELD_NAMES))}"
    )
    assert _SDK_BOOTSTRAP.exists(), "SDK bootstrap.py moved — update the bind"
    twin = ast.parse(_SDK_BOOTSTRAP.read_text(encoding="utf-8"))
    assert _string_tuple(twin, "_PROVENANCE_SEED_KEYS") is None, (
        "the SDK seed twin keeps its own key list again; it must read the decoder's"
    )
