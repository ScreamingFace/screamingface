"""A Benchmark declares where it comes from, and the Engine says whether frontier models
have room left on it (OME-1455, PR 2: the shapes, the rules, the served block).

FEATURE: Benchmark Provenance, Human Baseline, Frontier Score and the derived Benchmark
Saturation verdict on every served catalogue entry.
STORY: as a reader of a Leaderboard page, I learn who wrote the exam, who brought it here,
may I use it, how humans and the best published model score, and whether a win here still
means anything, without leaving the page.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from screamingface_engine.benchmarks import (
    Benchmark,
    BenchmarkDeclaration,
    candidate,
)
from screamingface_engine.benchmarks.provenance import (
    SATURATION_HEADROOM,
    FrontierScore,
    HumanBaseline,
    NotPublished,
    saturation_verdict,
)

_PAPER = "https://arxiv.org/abs/2009.03300"
_INSPECT_EVALS = "https://github.com/UKGovernmentBEIS/inspect_evals"
_HARNESS = f"{_INSPECT_EVALS}/tree/v0.20.0/src/inspect_evals/mmlu"


def _full_provenance() -> dict[str, Any]:
    """Every provenance field filled the way MMLU's row will be after the values PR."""

    return {
        "paper_url": _PAPER,
        "authors": "Hendrycks et al., 2020",
        "citation": (
            "@article{hendrycks2020mmlu, "
            "title={Measuring Massive Multitask Language Understanding}}"
        ),
        "inspect_contributors": ("jjallaire", "domdomegg"),
        "homepage_url": "https://github.com/hendrycks/test",
        "harness_url": _HARNESS,
        "dataset_url": "https://huggingface.co/datasets/cais/mmlu",
        "license": "MIT",
        "license_note": "Dataset card lists no restriction beyond MIT.",
        "content_warning": None,
        "human_baseline": HumanBaseline(score=0.898, source_url=_PAPER),
        "frontier_score": FrontierScore(
            score=0.92, model="example frontier model", source_url=_PAPER, as_of="2026-09"
        ),
        "notebook": "12_inspect_evals_benchmarks",
    }


def _benchmark(origin: str = "inspect_evals", **provenance: Any) -> Benchmark:
    """A structural probe Benchmark with whatever provenance the test hands it."""

    return Benchmark(
        id="example-smoke",
        title="Example Smoke",
        description="One non-comparable structural probe.",
        revision="example-smoke-v1",
        case_count=3,
        build=lambda selected: candidate(
            f"Explain why the sky looks blue. Selected cases: {selected}.",
            web_search=False,
        ),
        declaration=BenchmarkDeclaration(
            failure_policy="coverage_declare",
            interaction="single_shot",
            difficulty="easy",
        ),
        origin=origin,  # type: ignore[arg-type]
        **provenance,
    )


# --- the verdict ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("frontier", "verdict"),
    [
        (FrontierScore(score=0.92, model="m", source_url=_PAPER, as_of="2026-09"), "saturated"),
        (FrontierScore(score=0.90, model="m", source_url=_PAPER, as_of="2026-09"), "saturated"),
        (FrontierScore(score=0.60, model="m", source_url=_PAPER, as_of="2026-09"), "open"),
        (FrontierScore(score=0.899, model="m", source_url=_PAPER, as_of="2026-09"), "open"),
        (None, "unknown"),
        (NotPublished(reason="too new to have a published score"), "unknown"),
    ],
    ids=["0.92", "exactly-at-the-floor", "0.60", "just-under-the-floor", "none", "not-published"],
)
def test_the_verdict_follows_the_headroom_rule(
    frontier: FrontierScore | NotPublished | None, verdict: str
) -> None:
    # INVARIANT: headroom = 1.0 − score; saturated when headroom ≤ SATURATION_HEADROOM.
    # The floor is one named constant (spec §2.2) so a change is a one-line PR.
    assert SATURATION_HEADROOM == 0.10
    assert saturation_verdict(frontier) == verdict


@pytest.mark.parametrize("baseline", [None, HumanBaseline(score=0.95, source_url=_PAPER)])
def test_the_human_baseline_never_moves_the_verdict(baseline: HumanBaseline | None) -> None:
    # WHY: the glossary says human-level ≠ saturated. A frontier score below the human
    # baseline is still "saturated" when headroom is small, and above it is still "open"
    # when headroom is large; the baseline is context, never an input (spec §2.2).
    saturated = _benchmark(
        frontier_score=FrontierScore(score=0.92, model="m", source_url=_PAPER, as_of="2026-09"),
        human_baseline=baseline,
    )
    open_ = _benchmark(
        frontier_score=FrontierScore(score=0.60, model="m", source_url=_PAPER, as_of="2026-09"),
        human_baseline=baseline,
    )

    assert saturated.catalog_entry()["saturation"] == "saturated"
    assert open_.catalog_entry()["saturation"] == "open"


# --- what the catalogue serves -------------------------------------------------------------


def test_every_declared_field_reaches_the_catalogue_entry_and_the_resource() -> None:
    benchmark = _benchmark(**_full_provenance())

    entry = benchmark.catalog_entry()
    resource = benchmark.resource(1)

    for served in (entry, resource):
        assert served["paper_url"] == _PAPER
        assert served["authors"] == "Hendrycks et al., 2020"
        citation = served["citation"]
        assert isinstance(citation, str) and citation.startswith("@article{")
        assert served["inspect_contributors"] == ["jjallaire", "domdomegg"]
        assert served["homepage_url"] == "https://github.com/hendrycks/test"
        assert served["harness_url"] == _HARNESS
        assert served["license"] == "MIT"
        assert served["license_note"] == "Dataset card lists no restriction beyond MIT."
        assert served["human_baseline"] == {"score": 0.898, "source_url": _PAPER}
        assert served["frontier_score"] == {
            "score": 0.92,
            "model": "example frontier model",
            "source_url": _PAPER,
            "as_of": "2026-09",
        }
        assert served["notebook"] == "12_inspect_evals_benchmarks"
        assert served["saturation"] == "saturated"
        # content_warning was declared None: absent key, never null.
        assert "content_warning" not in served


def test_a_benchmark_declaring_nothing_serves_only_the_verdict() -> None:
    # INVARIANT: absent provenance is an absent key, never a null (the OME-904 rule), so a
    # seeded row is left untouched rather than blanked. `saturation` is the one key served
    # unconditionally — "unknown" is a verdict, not a gap.
    entry = _benchmark().catalog_entry()

    for key in (
        "paper_url",
        "authors",
        "citation",
        "inspect_contributors",
        "homepage_url",
        "harness_url",
        "license",
        "license_note",
        "content_warning",
        "human_baseline",
        "frontier_score",
        "notebook",
    ):
        assert key not in entry, key
    assert entry["saturation"] == "unknown"


def test_a_not_published_field_is_omitted_on_the_wire() -> None:
    # WHY: the reason is for the declaration's reviewer, not for readers; the pages render a
    # not-published and a missing field the same way, nothing, never a dash (spec §2.3).
    entry = _benchmark(
        paper_url=NotPublished(reason="no paper; the Benchmark was published as a blog post"),
        citation=NotPublished(reason="no paper to cite"),
        license=NotPublished(reason="owner licence decision on OME-1273: unknown"),
        human_baseline=NotPublished(reason="the paper reports no human study"),
        frontier_score=NotPublished(reason="too new to have a published score"),
    ).catalog_entry()

    for key in ("paper_url", "citation", "license", "human_baseline", "frontier_score"):
        assert key not in entry, key
    assert entry["saturation"] == "unknown"


def test_a_content_warning_is_served_when_declared() -> None:
    entry = _benchmark(content_warning="Prompts request harmful instructions.").catalog_entry()

    assert entry["content_warning"] == "Prompts request harmful instructions."


def test_provenance_never_touches_the_revision() -> None:
    # INVARIANT (spec rule 2): a link or a baseline says nothing about which Cases are asked
    # or how they are graded, so no provenance field may move the revision a submission
    # carries. `revision` is caller-computed; this pins that the catalogue echoes it unchanged.
    plain = _benchmark().catalog_entry()
    full = _benchmark(**_full_provenance()).catalog_entry()

    assert plain["revision"] == full["revision"] == "example-smoke-v1"


# --- the rules the validator enforces ------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("paper_url", "arxiv.org/abs/2009.03300", "paper_url"),
        ("paper_url", "ftp://arxiv.org/abs/2009.03300", "paper_url"),
        ("authors", "", "authors"),
        ("authors", "   ", "authors"),
        ("authors", "x" * 256, "authors"),
        ("citation", "", "citation"),
        ("inspect_contributors", (), "inspect_contributors"),
        ("inspect_contributors", ("-jjallaire",), "inspect_contributors"),
        ("inspect_contributors", ("jj--allaire",), "inspect_contributors"),
        ("inspect_contributors", ("jjallaire-",), "inspect_contributors"),
        ("inspect_contributors", ("j" * 40,), "inspect_contributors"),
        ("inspect_contributors", ("jj allaire",), "inspect_contributors"),
        ("inspect_contributors", ("https://github.com/jjallaire",), "inspect_contributors"),
        ("homepage_url", "hendrycks.github.io/test", "homepage_url"),
        ("harness_url", _INSPECT_EVALS, "harness_url"),
        ("harness_url", f"{_INSPECT_EVALS}/tree/main/src/inspect_evals/mmlu", "harness_url"),
        ("harness_url", f"{_INSPECT_EVALS}/tree/master/src", "harness_url"),
        ("harness_url", f"{_INSPECT_EVALS}/blob/main/README.md", "harness_url"),
        (
            "harness_url",
            "https://github.com/ScreamingFace/screamingface/tree/0e28fe49c",
            "harness_url",
        ),
        ("harness_url", "github.com/josejg/instruction_following_eval/tree/0c495b2", "harness_url"),
        ("license", "", "license"),
        ("license", "x" * 65, "license"),
        ("license_note", "x" * 256, "license_note"),
        ("content_warning", "", "content_warning"),
        ("content_warning", "x" * 256, "content_warning"),
        ("notebook", "", "notebook"),
        ("notebook", "12_inspect_evals_benchmarks.ipynb", "notebook"),
        ("notebook", "examples/12_inspect_evals_benchmarks", "notebook"),
    ],
    ids=lambda value: value if isinstance(value, str) and len(value) < 50 else None,
)
def test_a_malformed_provenance_field_is_refused_at_authoring_time(
    field: str, value: object, message: str
) -> None:
    # WHY refuse here: this definition is the ONE place these facts are written (the OME-904
    # rule), so a broken link, a handle that is not a GitHub username, or a harness link that
    # will move under a reader is caught where it is typed, not on a public page.
    provenance: dict[str, Any] = {field: value}
    with pytest.raises(ValueError, match=message):
        _benchmark(**provenance)


@pytest.mark.parametrize(
    "url",
    [
        _HARNESS,
        "https://github.com/josejg/instruction_following_eval/tree/0c495b2abcdef0123456/ifeval",
        "https://github.com/perplexity-ai/draco/blob/1a2b3c4d5e6f7a8b9c0d/README.md",
        "https://github.com/olivialiu121/ContractEval/commit/f2de744abc1234",
        "https://example.org/harness@v1.2.3",
    ],
)
def test_a_harness_link_pinned_to_a_commit_or_tag_is_accepted(url: str) -> None:
    # INVARIANT (F7): a reader who clicks the harness link must land on the code that produced
    # the paper's numbers, so the link carries a commit sha or a version tag.
    assert _benchmark(harness_url=url).harness_url == url


def test_inspect_contributors_belong_only_to_an_imported_benchmark() -> None:
    # WHY: the field credits whoever ported the eval into inspect; a Benchmark written in this
    # repo has no such people, so a value here is a copy-paste error, not a fact.
    with pytest.raises(ValueError, match="inspect_contributors"):
        _benchmark(origin="screamingface", inspect_contributors=("jjallaire",))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"score": 1.2, "source_url": _PAPER}, "score"),
        ({"score": -0.1, "source_url": _PAPER}, "score"),
        ({"score": 0.9, "source_url": "arxiv.org/abs/x"}, "source_url"),
    ],
)
def test_a_malformed_human_baseline_is_refused(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        HumanBaseline(**kwargs)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"score": 1.01, "model": "m", "source_url": _PAPER, "as_of": "2026-09"}, "score"),
        ({"score": 0.9, "model": "", "source_url": _PAPER, "as_of": "2026-09"}, "model"),
        ({"score": 0.9, "model": "m", "source_url": "x", "as_of": "2026-09"}, "source_url"),
        ({"score": 0.9, "model": "m", "source_url": _PAPER, "as_of": "2026-9"}, "as_of"),
        ({"score": 0.9, "model": "m", "source_url": _PAPER, "as_of": "Sept 2026"}, "as_of"),
        ({"score": 0.9, "model": "m", "source_url": _PAPER, "as_of": "2026-13"}, "as_of"),
    ],
)
def test_a_malformed_frontier_score_is_refused(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        FrontierScore(**kwargs)


@pytest.mark.parametrize("reason", ["", "   "])
def test_a_not_published_declaration_needs_a_reason(reason: str) -> None:
    # WHY: `NotPublished` is the one way to pass the conformance test without a value, so a
    # blank reason would be a silent gap wearing a badge.
    with pytest.raises(ValueError, match="reason"):
        NotPublished(reason=reason)


def test_a_frontier_score_typed_as_the_baseline_is_refused_and_the_reverse() -> None:
    # WHY: the two records share a shape family, so a swapped declaration would register
    # clean, serve "unknown" and omit the key — a silent gap with no error (PR 1236 review).
    frontier = FrontierScore(score=0.9, model="m", source_url=_PAPER, as_of="2026-09")
    baseline = HumanBaseline(score=0.9, source_url=_PAPER)
    with pytest.raises(TypeError, match="human_baseline must be a HumanBaseline"):
        _benchmark(**cast(dict[str, Any], {"human_baseline": frontier}))
    with pytest.raises(TypeError, match="frontier_score must be a FrontierScore"):
        _benchmark(**cast(dict[str, Any], {"frontier_score": baseline}))


@pytest.mark.parametrize("field", ["authors", "harness_url", "notebook"])
def test_fields_that_always_exist_do_not_accept_not_published(field: str) -> None:
    # WHY: every Benchmark has an author line, upstream code and a notebook, so "none
    # published" is never true for these (spec §2.1).
    with pytest.raises((ValueError, TypeError), match=field):
        _benchmark(**cast(dict[str, Any], {field: NotPublished(reason="n/a")}))


# --- the factories thread provenance through verbatim ---------------------------------------


def test_the_draco_factory_passes_provenance_through_and_keeps_its_revision() -> None:
    # WHY the factory and not `Benchmark` directly: a hand-built Benchmark's one authoring
    # site is its definition module's factory call, so a field the factory drops on the
    # floor is a field no DRACO board can ever declare (the OME-1257 difficulty precedent).
    from screamingface_engine.benchmarks.draco.definition import DRACO
    from screamingface_engine.benchmarks.draco.variant import draco_benchmark

    _, benchmark = draco_benchmark(
        id="draco",
        title="DRACO",
        description="probe",
        judge_passes=5,
        protocol_revision="five-pass-reproduction-v1",
        difficulty="hard",
        paper_url="https://arxiv.org/abs/2600.00001",
        harness_url="https://github.com/perplexity-ai/draco/tree/1a2b3c4d5e6f/eval",
        notebook="06_draco",
    )

    assert benchmark.paper_url == "https://arxiv.org/abs/2600.00001"
    assert benchmark.catalog_entry()["notebook"] == "06_draco"
    assert benchmark.revision == DRACO.revision


def test_the_healthbench_and_gdpval_factories_pass_provenance_through() -> None:
    from screamingface_engine.benchmarks.gdpval.definition import TEXT_CASE_IDS
    from screamingface_engine.benchmarks.gdpval.scoring import mean
    from screamingface_engine.benchmarks.gdpval.subset import subset_sha as gdpval_sha
    from screamingface_engine.benchmarks.gdpval.variant import gdpval_benchmark
    from screamingface_engine.benchmarks.healthbench.scoring import unclipped_mean
    from screamingface_engine.benchmarks.healthbench.subset import WORST30_CASE_IDS
    from screamingface_engine.benchmarks.healthbench.subset import subset_sha as hb_sha
    from screamingface_engine.benchmarks.healthbench.variant import healthbench_benchmark

    _, healthbench = healthbench_benchmark(
        id="healthbench-worst30",
        title="HB",
        description="probe",
        case_ids=WORST30_CASE_IDS,
        protocol_revision="worst30-per-item-v2",
        scoring="unclipped-mean-v1",
        mean=unclipped_mean,
        selection_sha=hb_sha(),
        difficulty="hard",
        license="MIT",
        human_baseline=HumanBaseline(score=0.5, source_url=_PAPER),
    )
    _, gdpval = gdpval_benchmark(
        id="gdpval-text",
        title="GDPval",
        description="probe",
        case_ids=TEXT_CASE_IDS,
        protocol_revision="text-per-item-v1",
        scoring="rubric-mean-v1",
        mean=mean,
        selection_sha=gdpval_sha(),
        difficulty="hard",
        frontier_score=FrontierScore(score=0.5, model="m", source_url=_PAPER, as_of="2026-09"),
    )

    assert healthbench.catalog_entry()["license"] == "MIT"
    assert healthbench.catalog_entry()["human_baseline"] == {"score": 0.5, "source_url": _PAPER}
    assert gdpval.catalog_entry()["saturation"] == "open"


# --- a literal TODO is refused by name, like difficulty="TODO" --------------------------------


@pytest.mark.parametrize(
    "provenance",
    [
        {"inspect_contributors": ("TODO",)},
        {"license": "TODO"},
        {"paper_url": NotPublished(reason="TODO")},
        {"frontier_score": NotPublished(reason="todo")},
    ],
    ids=["handle", "licence-text", "reason", "reason-lowercase"],
)
def test_a_literal_todo_left_by_the_importer_is_refused_at_registration(
    provenance: dict[str, Any],
) -> None:
    # WHY: the importer writes TODO where only a human can fill the value (the best published
    # score, a content warning). "TODO" is a valid GitHub handle and a non-blank reason, so
    # without this rule an unreviewed row would register clean.
    with pytest.raises(ValueError, match="TODO"):
        _benchmark(**provenance)
