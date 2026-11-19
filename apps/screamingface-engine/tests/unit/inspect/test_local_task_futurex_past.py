# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai, huggingface_hub and pyarrow, absent in the
# extra-less typecheck install.
"""FutureX-Past as a LOCAL inspect Task: the loader, the reply reader, levels 1-2 and the roll-up.

What these tests pin, and why (spec docs/spec/2026-11-16-futurex-past-local-task.md):

- the Case: the dataset's own prompt byte for byte, the parsed answer key, and an id that stays
  unique although the dataset reuses ids for recurring questions (§2);
- the reply: the LAST ``\\boxed{}`` is the answer, nested braces allowed; no box, no answer (§3);
- levels 1-2: the official label rules, exact match for one key, set F1 for several (§4.1);
- the headline: the paper's 10/20/30/40 tier weights, renormalised over the levels present (§4.4).

Levels 3-4 and their judge are in ``test_futurex_past_grading.py``. Runs only with the `inspect`
extra installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

import huggingface_hub  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from inspect_ai.dataset import Sample  # noqa: E402
from inspect_ai.scorer import SampleScore, Score  # noqa: E402

from screamingface_engine_inspect.local_tasks.futurex_past import futurex_past as fx  # noqa: E402
from screamingface_engine_inspect.local_tasks.futurex_past import grading as g  # noqa: E402

#: Four rows in the 8299bfa1 schema (``level`` a string, ``std`` present), one per level; the
#: second reuses the first's id on another date, as 21 real ids do.
_ROWS: list[dict[str, Any]] = [
    {
        "id": "6877aaaa",
        "prompt": 'Predict: "Lightning vs. Blues".\n\\boxed{Lightning} or \\boxed{Blues}',
        "end_time": "2026-01-17 00:00:00",
        "level": "1",
        "title": "Lightning vs. Blues",
        "ground_truth": '["Blues"]',
        "std": "",
        "std_reason": "",
    },
    {
        "id": "6877aaaa",
        "prompt": "Pick all that apply.\nA. one\nB. two\nC. three",
        "end_time": "2026/5/5",
        "level": "2",
        "title": "Pick",
        "ground_truth": "['C', 'P']",
        "std": "",
        "std_reason": "",
    },
    {
        "id": "6877bbbb",
        "prompt": "Who ranks 12 to 14?",
        "end_time": "2026-02-05",
        "level": "3",
        "title": "Ranking",
        "ground_truth": "['Ashanti MOORE', 'Jaël BESTUÉ', 'JaMeesia FORD']",
        "std": "",
        "std_reason": "",
    },
    {
        "id": "6877cccc",
        "prompt": "What will the S&P 500 open at?",
        "end_time": "2026-01-26",
        "level": "4",
        "title": "S&P",
        "ground_truth": "[6923.23]",
        "std": "18.46",
        "std_reason": "",
    },
]


def _parquet(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    path: Path = tmp_path / "train-00000-of-00001.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


# ── the Case ─────────────────────────────────────────────────────────────────────────────────


def test_the_pins_are_the_specs_commit_file_and_sha256() -> None:
    assert fx.DATASET == "futurex-ai/Futurex-Past"
    assert fx.DATASET_REVISION == "8299bfa1609dec30f267891a74d76e62902c9d71"
    assert fx.DATASET_FILE == "data/train-00000-of-00001.parquet"
    assert fx.DATASET_SHA256 == "a385ef5e6d9f120afcf495450db702ef1e7575e2c21c77b293fc7cba933336bb"


def test_a_row_is_served_with_its_own_prompt_byte_for_byte() -> None:
    """INVARIANT: FutureX ships a complete prompt with its own answer-format block; adding a
    word would make this a different exam (spec §2). The bytes sit inside the Case Digest."""

    sample: Sample = fx.record_to_sample(_ROWS[0])

    assert sample.input == _ROWS[0]["prompt"]
    assert sample.target == ["Blues"]
    assert sample.metadata == {
        "level": 1,
        "title": "Lightning vs. Blues",
        "end_time": "2026-01-17 00:00:00",
        "ground_truth": ["Blues"],
        "std": "",
    }


def test_a_number_key_keeps_its_type_in_the_metadata_and_is_text_in_the_target() -> None:
    """inspect's Target holds text; the judge rules need the float (spec §4.2), so the typed
    key rides the metadata."""

    sample: Sample = fx.record_to_sample(_ROWS[3])

    assert sample.target == ["6923.23"]
    assert sample.metadata is not None and sample.metadata["ground_truth"] == [6923.23]
    assert sample.metadata["level"] == 4


def test_the_case_id_is_the_studys_item_id_so_recurring_questions_stay_distinct() -> None:
    """The dataset reuses an id when a question recurs on another date (21 ids, 119 rows at
    8299bfa1); ``<id>|<end_time>`` is unique and is the study's own ``item_id``."""

    ids: list[str] = [str(fx.record_to_sample(row).id) for row in _ROWS[:2]]

    assert ids == ["6877aaaa|2026-01-17 00:00:00", "6877aaaa|2026/5/5"]


def test_the_older_schema_without_std_and_with_an_integer_level_loads() -> None:
    """Commit 3c2e3969 (the study's) has no ``std`` columns and an integer ``level``."""

    row: dict[str, Any] = {
        key: value for key, value in _ROWS[2].items() if key not in ("std", "std_reason")
    }
    sample: Sample = fx.record_to_sample({**row, "level": 3})

    assert sample.metadata is not None
    assert (sample.metadata["level"], sample.metadata["std"]) == (3, None)


@pytest.mark.parametrize(
    ("raw", "parsed"),
    [
        ('["Blues"]', ["Blues"]),
        ("['C', 'P']", ["C", "P"]),
        ("[6923.23]", [6923.23]),
        ("['迟爱', '天官赐福 第三季']", ["迟爱", "天官赐福 第三季"]),
        # NAMED DEVIATION (spec §2): the one key that is not a Python literal. The official
        # harness keeps it as the label "[Yes]", which nothing matches.
        ("[Yes]", ["Yes"]),
    ],
)
def test_the_answer_key_is_parsed_as_a_literal_never_evaluated(raw: str, parsed: list[Any]) -> None:
    assert fx.parse_ground_truth(raw) == parsed


def test_a_file_whose_sha256_is_not_the_pin_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Hub commit pins the file's name; the sha256 pins its bytes (the dataset is
    re-published weekly)."""

    tampered: Path = _parquet(tmp_path, _ROWS)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda **_kwargs: str(tampered))

    with pytest.raises(ValueError, match=f"expected {fx.DATASET_SHA256}"):
        fx.load_futurex_past()


def test_a_pinned_file_loads_in_file_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path: Path = _parquet(tmp_path, _ROWS)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda **_kwargs: str(path))
    import hashlib

    digest: str = hashlib.sha256(path.read_bytes()).hexdigest()

    dataset = fx.load_futurex_past(revision="r", sha256=digest, name="fixture")

    assert [str(sample.id) for sample in dataset] == [
        f"{row['id']}|{row['end_time']}" for row in _ROWS
    ]


def test_two_rows_with_the_same_case_id_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: a Case id addresses one Case; a duplicate would grade one reply twice."""

    path: Path = _parquet(tmp_path, [_ROWS[0], _ROWS[0]])
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda **_kwargs: str(path))
    import hashlib

    digest: str = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="two rows share the Case id 6877aaaa"):
        fx.load_futurex_past(revision="r", sha256=digest, name="fixture")


# ── the reply ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("reply", "box"),
    [
        ("Reasoning...\n\\boxed{Blues}", "Blues"),
        # the LAST box wins: a reasoning reply may show a worked box first
        ("Maybe \\boxed{A}. On reflection \\boxed{B, C}", "B, C"),
        # one level of nested braces (the study's 2026-08-08 fix)
        ("\\boxed{\\text{央视新闻, 新华社, 占豪}}", "\\text{央视新闻, 新华社, 占豪}"),
        ("\\boxed { 42 }", "42"),
        ("No box at all.", None),
        ("", None),
    ],
)
def test_the_answer_is_the_last_boxed_content(reply: str, box: str | None) -> None:
    assert g.last_boxed(reply) == box


@pytest.mark.parametrize(
    ("box", "tokens"),
    [
        ("B, C", ["B", "C"]),
        (" A ,, B ", ["A", "B"]),
        ("Blues", ["Blues"]),
        ("", []),
        (None, []),
    ],
)
def test_the_box_is_split_on_commas_into_stripped_tokens(
    box: str | None, tokens: list[str]
) -> None:
    """The study's ``build_data.py`` split, and the official extractor's for a non-number."""

    assert g.answer_tokens(box) == tokens


# ── levels 1-2 (official estimate_score_level_1_2) ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "label"),
    [
        (" b ", "B"),
        ("'C'", "C"),
        ("\\boxed{a}", "A"),
        ("\\text{Blues}", "Blues"),
        ("YES", "Yes"),
        ("no", "No"),
        ("Lightning", "Lightning"),
        (6923.23, "6923.23"),
    ],
)
def test_each_label_is_normalised_the_official_way(raw: object, label: str) -> None:
    assert g.normalize_label(raw) == label


@pytest.mark.parametrize(
    ("gold", "predicted", "score"),
    [
        (["Blues"], ["Blues"], 1.0),
        (["Blues"], ["blues"], 0.0),  # case counts for a name; only letters and yes/no fold
        (["B"], ["b"], 1.0),
        (["Yes"], ["yes"], 1.0),
        (["Blues"], ["Blues", "Lightning"], 0.0),  # one key: the whole list must equal it
        (["Blues"], [], 0.0),
        (["C", "P"], ["P", "C"], 1.0),  # several keys: set F1, order free
        (["C", "P"], ["C"], pytest.approx(2 / 3)),
        (["C", "P"], ["C", "P", "Q"], pytest.approx(0.8)),
        (["C", "P"], ["Q"], 0.0),
        (["C", "P"], [], 0.0),
        (["A", "A", "B"], ["A", "B"], 1.0),  # the set, as the official code takes it
    ],
)
def test_levels_one_and_two_score_by_exact_match_or_set_f1(
    gold: list[Any], predicted: list[str], score: float
) -> None:
    assert g.label_score(gold, predicted) == score


# ── the headline: tier-weighted ─────────────────────────────────────────────────────────────


def _headline(scores: list[SampleScore]) -> Any:
    """Run the Task's @metric as inspect does (its ``Metric`` alias still types the argument as
    ``list[Score]``, so the call goes through ``Any``)."""

    compute: Any = fx.futurex_tier_weighted()
    return compute(scores)


def _sample_score(value: float, level: int | None, case: int) -> SampleScore:
    metadata: dict[str, Any] | None = None if level is None else {"level": level}
    return SampleScore(score=Score(value=value), sample_id=case, sample_metadata=metadata)


def test_the_headline_weights_the_four_level_means_10_20_30_40() -> None:
    """run_weekly_leaderboard.py's LEVEL_WEIGHTS over per-level means."""

    scores: list[SampleScore] = [
        _sample_score(1.0, 1, 1),
        _sample_score(0.0, 1, 2),  # level 1 mean 0.5
        _sample_score(1.0, 2, 3),  # level 2 mean 1.0
        _sample_score(0.2, 3, 4),  # level 3 mean 0.2
        _sample_score(0.0, 4, 5),
        _sample_score(0.5, 4, 6),  # level 4 mean 0.25
    ]

    value = _headline(scores)

    assert value == pytest.approx(0.1 * 0.5 + 0.2 * 1.0 + 0.3 * 0.2 + 0.4 * 0.25)


def test_a_missing_level_renormalises_the_weights_over_the_levels_present() -> None:
    """NAMED DEVIATION (spec §4.4): the official code counts an absent level as 0; on a sample
    of the Cases that would punish the sample, so the weights renormalise (the study's rule)."""

    scores: list[SampleScore] = [_sample_score(1.0, 1, 1), _sample_score(0.5, 3, 2)]

    value = _headline(scores)

    assert value == pytest.approx((0.1 * 1.0 + 0.3 * 0.5) / 0.4)


def test_cases_without_a_level_fall_back_to_the_plain_mean() -> None:
    """The no-network lane's stand-in Cases carry no metadata; the metric degrades to the
    mean instead of failing, as ARC-AGI-2's does."""

    scores: list[SampleScore] = [_sample_score(1.0, None, 1), _sample_score(0.0, None, 2)]

    assert _headline(scores) == pytest.approx(0.5)


# ── the Task ─────────────────────────────────────────────────────────────────────────────────


def test_the_task_generates_once_and_scores_with_one_scorer_under_the_tier_weights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    samples: list[Sample] = [fx.record_to_sample(row) for row in _ROWS]
    monkeypatch.setattr(fx, "load_futurex_past", lambda **_kwargs: samples)

    from inspect_ai._util.registry import registry_info

    task = fx.futurex_past()

    [scorer] = task.scorer or []
    assert registry_info(scorer).name.endswith("futurex_score")
    assert [registry_info(metric).name.split("/")[-1] for metric in task.metrics or []] == [
        "futurex_tier_weighted"
    ]
    assert task.epochs in (None, 1)


# ── the rows, and grading through the Engine's real per-Case hook ───────────────────────────

_JUDGE_ROUTE: str = "/openrouter/openai/gpt-5.4"
_JUDGE_PARAMS: list[tuple[str, str]] = [
    ("temperature", "0"),
    ("max_tokens", "4096"),
    ("web_search", "false"),
]


def test_the_rows_serve_both_case_sets_and_pin_the_house_judge_on_futurex_past_only() -> None:
    from screamingface_engine.benchmarks.provenance import provenance_gaps
    from screamingface_engine_inspect.benchmarks import BENCHMARKS, imported_benchmark
    from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES

    official = imported_benchmark("futurex_past")
    study = imported_benchmark("futurex_past_study")
    spec = next(row for row in BENCHMARKS if row.key == "futurex_past")

    assert (official.benchmark.case_count, study.benchmark.case_count) == (2036, 1118)
    assert official.benchmark.origin == study.benchmark.origin == "external"
    assert official.benchmark.contributors == study.benchmark.contributors == ("yimingliao-blad",)
    assert provenance_gaps(official.benchmark) == provenance_gaps(study.benchmark) == []
    assert spec.judge is not None and spec.judge.model == _JUDGE_ROUTE.removeprefix("/")
    assert list(spec.judge.params) == _JUDGE_PARAMS
    assert spec.scorer_kwargs == {"judge_model": "screamingface" + _JUDGE_ROUTE}
    assert study.judge is None
    assert official.benchmark.check_surface is None and study.benchmark.check_surface is None
    for key in ("futurex_past", "futurex_past_study"):
        assert TASK_REPLAY_CASES[key].keep_sample_metadata is True


class _ScriptedJudge:
    """A fake node fetch standing in for the gateway judge: answers by the purpose its prompt
    shows (router, match), and keeps every call's (path, params, messages). It simulates the
    judge's replies only."""

    def __init__(self, replies: dict[str, str]) -> None:
        self.replies: dict[str, str] = replies
        self.calls: list[tuple[str, list[tuple[str, str]], list[dict[str, str]]]] = []

    async def __call__(self, target: str) -> str:
        import json

        from url4.wire.subrequest import decode_subrequest_http, extract_expression_params

        path, _, query = target.partition("?")
        params, q = extract_expression_params(query)
        assert q is not None
        context, _ = decode_subrequest_http(q)
        messages: list[dict[str, str]] = json.loads(context)["messages"]
        self.calls.append((path, list(params.items()), messages))
        prompt: str = messages[-1]["content"]
        purpose: str = "route" if prompt.startswith("You choose how") else "match"
        return self.replies[purpose]


async def _grade(key: str, row: dict[str, Any], reply: str) -> Any:
    """Grade one real row through the Benchmark's own per-Case grading hook."""

    import json

    from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import GradeRequest
    from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload
    from screamingface_engine_inspect.benchmarks import imported_benchmark
    from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES, prepared_case

    sample: Sample = fx.record_to_sample(row)
    case = prepared_case(sample, 1, str(sample.input), TASK_REPLAY_CASES[key])
    hook = imported_benchmark(key).aggregation().grade_case
    return await hook(
        GradeRequest(
            case_id=1,
            input=TextPayload(text=str(sample.input)),
            answer=TextPayload(text=reply),
            row={"case": {"status": "answered"}},
            material=json.loads(json.dumps(case["grading_material"])),
        )
    )


@pytest.mark.asyncio
async def test_a_level_1_case_grades_by_rule_with_no_judge(no_network: None) -> None:
    right = await _grade("futurex_past", _ROWS[0], "The Blues are stronger.\n\\boxed{Blues}")
    wrong = await _grade("futurex_past", _ROWS[0], "\\boxed{Lightning}")
    boxless = await _grade("futurex_past", _ROWS[0], "Blues")

    assert [right.score, wrong.score, boxless.score] == [1.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_the_study_twin_case_folds_where_the_official_rule_does_not(
    no_network: None,
) -> None:
    """Level 1, key "Blues", reply "blues": the study's ``normalise`` matches it, Futurex-Eval's
    label rule (which folds only letters and yes/no) does not."""

    official = await _grade("futurex_past", _ROWS[0], "\\boxed{blues}")
    study = await _grade("futurex_past_study", _ROWS[0], "\\boxed{blues}")

    assert (official.score, study.score) == (0.0, 1.0)


@pytest.mark.asyncio
async def test_a_level_3_case_asks_the_pinned_judge_to_route_then_to_match() -> None:
    from screamingface_engine.request_scope import RequestScope, request_scope
    from screamingface_engine_inspect.benchmarks import imported_benchmark
    from screamingface_engine_inspect.judge_provider import JudgeTransport, bound_judge_transport

    row: dict[str, Any] = {**_ROWS[2], "ground_truth": "['Beijing']"}
    judge = _ScriptedJudge(
        {"route": '{"metric": "legacy_type_b", "reason": "a name"}', "match": "\\boxed{Yes}"}
    )
    spec = imported_benchmark("futurex_past").judge
    assert spec is not None
    transport = JudgeTransport(
        fetch=judge, params=spec.params, benchmark_id="futurex_past", seed_per_pass=False
    )
    with request_scope(RequestScope(origin="run")), bound_judge_transport(transport):
        outcome = await _grade("futurex_past", row, "\\boxed{北京}")

    assert (outcome.score, outcome.failure_code) == (1.0, None)
    assert [path for path, _, _ in judge.calls] == [_JUDGE_ROUTE, _JUDGE_ROUTE]
    assert all(params == _JUDGE_PARAMS for _, params, _ in judge.calls)
    [route_messages, match_messages] = [messages for _, _, messages in judge.calls]
    assert route_messages == [
        {"role": "user", "content": g.router_prompt(row["prompt"], ["Beijing"])}
    ]
    assert match_messages == [{"role": "user", "content": g.match_prompt("北京", "Beijing")}]


# ── review findings ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_text_wrapped_box_of_options_is_unwrapped_before_the_split(
    no_network: None,
) -> None:
    """``\\boxed{\\text{C, P}}`` is the options C and P (sf-code-review, fidelity U1)."""

    outcome = await _grade("futurex_past", _ROWS[1], "\\boxed{\\text{C, P}}")

    assert outcome.score == 1.0


def test_a_router_that_never_parses_still_counts_its_redraws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback route keeps the evidence of the redraws it spent (sf-code-review)."""

    import asyncio

    from screamingface_engine_inspect.judge_redraw import JudgeReplyUnparseable

    async def never(*_args: Any, **_kwargs: Any) -> Any:
        raise JudgeReplyUnparseable("no route", redraws=2)

    monkeypatch.setattr(fx, "judge_until_parsed", never)
    redraws: list[int] = []
    ask = fx._asker(object(), 7, redraws)  # pyright: ignore[reportPrivateUsage, reportArgumentType]

    async def route() -> str:
        return await ask("route?", g.parse_route, "route")

    with pytest.raises(JudgeReplyUnparseable):
        asyncio.run(route())
    assert redraws == [2]


def test_a_case_without_a_level_beside_leveled_cases_leaves_the_headline() -> None:
    """INVARIANT: the plain-mean fallback is for stand-in runs where no Case carries a level. In
    a real run, a Case whose Candidate abstained and whose grading then failed reaches the metric
    as a bare 0.0 with no metadata (``single_shot._metric_sample``); it cannot be placed in a
    level, so it is left out of the per-level means instead of switching the formula."""

    scores: list[SampleScore] = [_sample_score(1.0, 1, 1), _sample_score(0.0, None, 2)]

    assert _headline(scores) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_options_wrapped_one_by_one_are_read_at_level_2(no_network: None) -> None:
    """``\\boxed{\\text{C}, \\text{P}}`` is the options C and P (fidelity audit U7)."""

    outcome = await _grade("futurex_past", _ROWS[1], "\\boxed{\\text{C}, \\text{P}}")

    assert outcome.score == 1.0
