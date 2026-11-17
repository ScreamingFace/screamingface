# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai, absent in the extra-less typecheck install.
"""``futurex_past_study``: FutureX-Past scored the crowd-wisdom study's way, for replication.

What these tests pin, and why (spec docs/spec/2026-11-16-futurex-past-local-task.md §10):

- the scorer is the study's ``committee_kit/metrics.py``, byte for byte below our header;
- the data is commit 3c2e3969, the latest that holds all 100 of the study's questions, and the
  100 Case positions the README publishes are exactly the study's ``item_id``s;
- the study's stored answers, scored here, give the study's own numbers to the last bit,
  including the fused-medoids committee's 0.302 (the paper's Table III).

The fixture ``tests/fixtures/futurex_past_study/replication.json`` was generated from the study
package by ``make_replication_fixture.py`` beside it; its expected scores are the study kit's.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.scorer import SampleScore, Score  # noqa: E402

import screamingface_engine_inspect.local_tasks.futurex_past.vendor as vendor  # noqa: E402
from screamingface_engine_inspect.local_tasks.futurex_past import (  # noqa: E402
    futurex_past_study as study,
)
from screamingface_engine_inspect.local_tasks.futurex_past.futurex_past import (  # noqa: E402
    parse_ground_truth,
)

_FIXTURE: Path = (
    Path(__file__).resolve().parents[2] / "fixtures" / "futurex_past_study" / "replication.json"
)
_VENDORED: Path = Path(vendor.__file__).parent / "study_metrics.py"

#: sha256 of the study's ``metrics.py`` code AFTER its module docstring (whole file 2c94cb74…).
_STUDY_CODE_SHA256: str = "b9a81867c34e6b76f581456809afc2b99024e18358e08a64bb18f23303676176"


def _fixture() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


# ── the vendored scorer ──────────────────────────────────────────────────────────────────────


def test_the_vendored_file_is_the_studys_code_below_our_header() -> None:
    """INVARIANT: a tidy-up of the copy would move every score off the study's with every
    other gate green; this hash is what notices."""

    source: bytes = _VENDORED.read_bytes()
    first: ast.stmt = ast.parse(source).body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
    assert first.end_lineno is not None
    code: bytes = b"".join(source.splitlines(keepends=True)[first.end_lineno :])

    assert hashlib.sha256(code).hexdigest() == _STUDY_CODE_SHA256
    assert _STUDY_CODE_SHA256 in (vendor.__doc__ or "")


# ── the data ─────────────────────────────────────────────────────────────────────────────────


def test_the_pins_are_the_study_commit_file_and_sha256() -> None:
    assert study.STUDY_REVISION == "3c2e39690de35eb1fcc621251f56343c72bae8c4"
    assert study.STUDY_SHA256 == "55ecf4f11909d412d515eeeab5b5891012adde4ff4353d35204179728704ad50"


def test_the_published_100_positions_are_exactly_the_studys_questions() -> None:
    """The README's ``cases=[...]`` list: position k (1-based, file order at 3c2e3969) is the
    study's item, for all 100."""

    dataset: dict[str, Any] = _fixture()["dataset_3c2e3969"]

    assert sorted(entry["position"] for entry in dataset.values()) == list(study.STUDY_CASES)
    assert len(study.STUDY_CASES) == len(set(study.STUDY_CASES)) == 100


def test_the_datasets_key_at_3c2e3969_is_the_studys_key_after_normalisation() -> None:
    """The study froze its gold from this commit; parsed here and normalised the study's way,
    every one of the 100 keys equals the study's."""

    fixture: dict[str, Any] = _fixture()
    for item, entry in fixture["dataset_3c2e3969"].items():
        ours: list[str] = [study.normalise(t) for t in parse_ground_truth(entry["ground_truth"])]
        theirs: list[str] = [study.normalise(t) for t in fixture["gold"][item]["ground_truth"]]
        assert ours == theirs, item
        assert int(entry["level"]) == fixture["gold"][item]["level"], item


# ── the score ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("level", "gold", "tokens", "score"),
    [
        (1, ["Blues"], ["blues"], 1.0),  # the study case-folds both sides
        (1, ["Blues"], ["Blues", "Lightning"], 0.0),
        (2, ["C", "P"], ["c"], pytest.approx(2 / 3)),
        (3, ["A  B", "C"], ["a b", "c"], 1.0),  # whitespace collapsed
        (3, ["x", "y", "z"], ["y", "x"], pytest.approx(0.8 * 2 / 3)),
        (4, [6923.23], ["6923.23"], 1.0),  # numbers compare as text, no sigma
        (4, [6923.23], ["6923.2"], 0.0),
        (4, ["x"], [], 0.0),  # no box: an abstention
    ],
)
def test_each_case_is_scored_by_the_studys_item_score_after_normalisation(
    level: int, gold: list[Any], tokens: list[str], score: float
) -> None:
    assert study.study_item_score(level, gold, tokens) == score


def _headline(scores: list[SampleScore]) -> Any:
    """Run the Task's @metric as inspect does (its ``Metric`` alias still types the argument as
    ``list[Score]``, so the call goes through ``Any``)."""

    compute: Any = study.study_tier_weighted()
    return compute(scores)


def _sample_scores(answers: dict[str, Any], gold: dict[str, Any]) -> list[SampleScore]:
    """One SampleScore per study item, as the Engine would hand them to the metric."""

    return [
        SampleScore(
            score=Score(
                value=study.study_item_score(
                    gold[item]["level"], gold[item]["ground_truth"], tokens or []
                )
            ),
            sample_id=item,
            sample_metadata={"level": gold[item]["level"]},
        )
        for item, tokens in answers.items()
    ]


@pytest.mark.parametrize(
    "entry", ["claude-haiku-4.5", "claude-opus-4.6", "claude-sonnet-4.6", "fused-medoids"]
)
def test_the_studys_stored_answers_reproduce_the_studys_scores_exactly(entry: str) -> None:
    """The replication contract: same answers in, the study's number out, to 0.0 tolerance."""

    fixture: dict[str, Any] = _fixture()

    value: Any = _headline(_sample_scores(fixture["answers"][entry], fixture["gold"]))

    assert value == fixture["expected"][entry]


def test_the_fused_medoids_committee_scores_the_papers_0_302() -> None:
    fixture: dict[str, Any] = _fixture()

    value: Any = _headline(_sample_scores(fixture["answers"]["fused-medoids"], fixture["gold"]))

    assert round(float(value), 3) == 0.302


# ── the Task ─────────────────────────────────────────────────────────────────────────────────


def test_the_task_has_one_judge_free_scorer_under_the_studys_tier_weights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._util.registry import registry_info
    from inspect_ai.dataset import Sample

    one: Sample = Sample(id="x|2026-08-01", input="Q?", target=["A"], metadata={"level": 1})
    monkeypatch.setattr(study, "load_futurex_past", lambda **_kwargs: [one])

    task = study.futurex_past_study()

    [scorer] = task.scorer or []
    assert registry_info(scorer).name.endswith("futurex_study_score")
    assert [registry_info(metric).name.split("/")[-1] for metric in task.metrics or []] == [
        "study_tier_weighted"
    ]
