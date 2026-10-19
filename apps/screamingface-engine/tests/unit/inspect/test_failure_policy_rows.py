"""OME-1642 U1: every Benchmark declares its failure policy, and the table pins it.

INVARIANT: `failure_policy` is a REQUIRED field on the BenchmarkSpec row, placed after
`difficulty` (no default: a policy nobody can see is a policy nobody can approve). The
factory passes the row's value into the BenchmarkDeclaration unchanged. A `withhold` the
reducer cannot honour is refused at registration, by name: F needs a per-metric rule,
E needs a per-row rule.
"""

from __future__ import annotations

import dataclasses

import pytest

from screamingface_engine.benchmarks.medxpert.definition import MEDXPERT
from screamingface_engine_inspect.benchmarks import BENCHMARKS, BenchmarkSpec

# Group A-C (spec §5): a failed Case counts 0 and every selected Case is in the denominator.
_WITHHOLD: frozenset[str] = frozenset(
    {
        "gsm8k",
        "mmlu",
        "arc_easy",
        "arc_challenge",
        "commonsense_qa",
        "paws",
        "boolq",
        "mmlu_pro",
        "winogrande",
        "race_h",
        "aime24",
        "aime25",
        "aime26",
        "musr",
        "wmdp_bio",
        "wmdp_chem",
        "wmdp_cyber",
        "hellaswag",
        "lab_bench_litqa",
        "lab_bench_suppqa",
        "lab_bench_dbqa",
        "lab_bench_protocolqa",
        "lab_bench_seqqa",
        "lab_bench_cloning_scenarios",
        "frontierscience",
        "onet_m6",
        "pubmedqa",
        "agieval_lsat_ar",
        "agieval_lsat_lr",
        "agieval_lsat_rc",
        "agieval_sat_math",
        "agieval_sat_en",
        "agieval_sat_en_without_passage",
        "agieval_aqua_rat",
        "agieval_logiqa_en",
        "medqa",
        "mgsm_en",
        "bbq",
        "piqa",
        "cybermetric_80",
        "cybermetric_500",
        "cybermetric_2000",
        "cybermetric_10000",
        "sevenllm_mcq_zh",
        "sevenllm_mcq_en",
        "worldsense",
        "sad_facts_llms",
        "sad_facts_human_defaults",
        "sad_influence",
        "sad_stages_oversight",
        "sad_stages_full",
        "pre_flight",
        "bbeh",
        "uccb",
        "infinite_bench_math_find",
        "squad",
        "math",
        "musique",
        "gdpval-text",
        "frames_oracle",
        # OME-1602 PR 5/6 rows, added on main after the plan's table: each is a per-Case mean
        # (no whole-run metric, not inverted, a decline is never the right answer) — Group A.
        "truthfulqa_mc1",
        "chembench",
        "stereoset",
        "cyse4_malware_analysis",
        "drop",
    }
)

# Groups D-G (spec §5): a failed Case leaves the score and coverage says so.
_COVERAGE_DECLARE: frozenset[str] = frozenset(
    {
        # D: the reference rule (draco).
        "draco",
        "draco-3pass",
        # E: refusal-measuring rows.
        "xstest_safe",
        "xstest_unsafe",
        "coconot_original",
        "coconot_contrast",
        "fortress_benign",
        "strong_reject",
        "air_bench",
        "cyse4_mitre_frr",
        # F: whole-run metric rows.
        "arc_agi_2",
        "contracteval",
        "healthbench-professional",
        "ifeval",
        "simpleqa",
        "simpleqa_verified",
        # G: open (negative grades).
        "healthbench-worst30",
    }
)

_EXPECTED: dict[str, str] = {
    **{key: "withhold" for key in _WITHHOLD},
    **{key: "coverage_declare" for key in _COVERAGE_DECLARE},
}


def test_failure_policy_is_a_required_row_field_after_difficulty() -> None:
    # WHY pinned by name and position: the plan puts it directly after `difficulty`, the
    # other declared axis with no default (OME-1039, OME-1257).
    names = [field.name for field in dataclasses.fields(BenchmarkSpec)]
    field = dataclasses.fields(BenchmarkSpec)[names.index("failure_policy")]
    assert field.default is dataclasses.MISSING
    assert field.default_factory is dataclasses.MISSING
    assert names.index("failure_policy") == names.index("difficulty") + 1


def test_every_row_declares_the_policy_of_the_table() -> None:
    # INVARIANT: 77 imported rows, each with exactly the policy the table names. A new row or a
    # changed policy trips here, deliberately.
    assert len(BENCHMARKS) == 82
    assert len(_WITHHOLD) == 65
    assert len(_COVERAGE_DECLARE) == 17
    actual = {spec.key: spec.failure_policy for spec in BENCHMARKS}
    assert actual == _EXPECTED


def test_medxpert_declares_withhold() -> None:
    assert MEDXPERT.declaration.failure_policy == "withhold"


def test_factory_passes_the_row_policy_into_the_declaration() -> None:
    # WHY importorskip: assembling a row reads inspect-ai's installed version for its revision
    # pin, so this check runs only in the inspect lane.
    pytest.importorskip("inspect_ai")
    pytest.importorskip("inspect_evals")
    from screamingface_engine_inspect.benchmarks import imported_benchmark

    for key in ("gsm8k", "xstest_safe", "healthbench-worst30"):
        declaration = imported_benchmark(key).benchmark.declaration
        assert declaration.failure_policy == _EXPECTED[key], key


def test_withhold_refuses_a_whole_run_metric_by_name() -> None:
    # WHY: F rows need a per-metric rule; a withhold over a whole-run metric has none.
    pytest.importorskip("inspect_ai")
    pytest.importorskip("inspect_evals")
    from screamingface_engine_inspect.single_shot import single_shot_benchmark

    with pytest.raises(
        ValueError,
        match=r"inspect-policy-probe-metric: failure_policy withhold "
        r"cannot score a whole-run metric",
    ):
        single_shot_benchmark(
            benchmark_key="policy-probe-metric",
            title="Probe",
            description="One non-comparable structural probe.",
            focus="Probing",
            dataset_url="https://example.com/probe",
            case_count=3,
            revision_pins=("dataset", "rev-a", "split=test"),
            scorer_factory=lambda: None,
            prepare=lambda out: {},
            install=lambda node, assets: None,
            with_check_surface=False,
            difficulty="easy",
            failure_policy="withhold",
            whole_run_metric_factory=lambda: None,
        )


def test_withhold_refuses_an_inverted_grade_by_name() -> None:
    # WHY: an E row's failed Case is the behaviour the Benchmark rewards; a withhold would
    # punish it. The E rows keep coverage_declare until each gets its own rule.
    pytest.importorskip("inspect_ai")
    pytest.importorskip("inspect_evals")
    from screamingface_engine_inspect.single_shot import single_shot_benchmark

    with pytest.raises(
        ValueError,
        match=r"inspect-policy-probe-inverted: failure_policy withhold "
        r"cannot score an inverted grade",
    ):
        single_shot_benchmark(
            benchmark_key="policy-probe-inverted",
            title="Probe",
            description="One non-comparable structural probe.",
            focus="Probing",
            dataset_url="https://example.com/probe",
            case_count=3,
            revision_pins=("dataset", "rev-a", "split=test"),
            scorer_factory=lambda: None,
            prepare=lambda out: {},
            install=lambda node, assets: None,
            with_check_surface=False,
            difficulty="easy",
            failure_policy="withhold",
            inverted_grade=True,
        )


def test_the_renderer_writes_the_policy_as_a_todo_that_registration_refuses() -> None:
    # WHY: an unreviewed imported row must not ship with a policy the owner never chose. The
    # literal TODO is refused by name at registration, so the rendered row must carry it.
    pytest.importorskip("inspect_ai")
    from test_task_replay_rows import _benchmark, _imported

    from screamingface_engine_inspect.task_replay_rows import render_task_replay_rows

    rows = render_task_replay_rows("agieval_lsat_ar", _imported(), "TODO")
    assert 'failure_policy="TODO"' in rows.benchmark
    assert _benchmark(rows).failure_policy == "TODO"
