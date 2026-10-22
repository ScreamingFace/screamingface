"""OME-1039: the declared grading contract every Benchmark must register.

INVARIANT: `failure_policy` and `interaction` are explicit, required, per-benchmark
parameters — never a shared-grading-level default. A policy nobody can see from the manifest is a
policy nobody can approve, and a default that flips silently changes published-score
semantics for every benchmark at once.
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.definition import (
    Benchmark,
    BenchmarkDeclaration,
    candidate,
)

DECLARATION = BenchmarkDeclaration(
    failure_policy="coverage_declare",
    interaction="single_shot",
    difficulty="easy",
)


def _benchmark_values() -> dict[str, object]:
    return {
        "id": "example-smoke",
        "title": "Example Smoke",
        "description": "One non-comparable structural probe.",
        "revision": "example-smoke-v1",
        "case_count": 3,
        "build": lambda selected: candidate(
            f"Explain why the sky looks blue. Selected cases: {selected}.",
            web_search=False,
        ),
        "declaration": DECLARATION,
    }


def test_benchmark_without_a_declaration_cannot_be_constructed() -> None:
    # STORY: as an auditor who must approve eval code before it runs, a benchmark that
    # never declared its failure policy must fail registration before any paid request.
    values = _benchmark_values()
    del values["declaration"]
    with pytest.raises(TypeError):
        Benchmark(**values)  # type: ignore[arg-type]


def test_declaration_refuses_an_unknown_failure_policy_by_name() -> None:
    with pytest.raises(ValueError, match="failure_policy"):
        BenchmarkDeclaration(
            failure_policy="drop-silently",  # type: ignore[arg-type]
            interaction="single_shot",
            difficulty="easy",
        )


def test_declaration_refuses_an_unknown_interaction_by_name() -> None:
    # WHY: a new interaction shape arrives as a DECLARED value, never as a silent acceptance —
    # the contract refuses the unknown one before any paid request.
    #
    # AIDEV-NOTE: this test used to name `multi_turn` as its unknown value. OME-1126 (MedXpertQA)
    # added it as a real value: that benchmark invokes the Candidate twice per Case (reason, then
    # commit against a bare trigger), so it could not register while `single_shot` was the only
    # option. The guard itself is unchanged in strength — it still proves an unknown value is
    # refused by name. Agentic/tool-environment shapes remain unknown until a benchmark needs them.
    with pytest.raises(ValueError, match="interaction"):
        BenchmarkDeclaration(
            failure_policy="withhold",
            interaction="agentic_tool_use",  # type: ignore[arg-type]
            difficulty="easy",
        )


def test_declaration_accepts_the_declared_multi_turn_shape() -> None:
    # The positive half of the guard above: a value only becomes acceptable by being declared.
    declaration = BenchmarkDeclaration(
        failure_policy="coverage_declare",
        interaction="multi_turn",
        difficulty="hard",
    )
    assert declaration.as_block()["interaction"] == "multi_turn"


def test_declaration_refuses_an_unknown_difficulty_by_name() -> None:
    # WHY: the catalogue GROUPS on this value (OME-1257) — an unknown tier would render as
    # its own orphan shelf, so the contract refuses it at registration, like its siblings.
    with pytest.raises(ValueError, match="difficulty"):
        BenchmarkDeclaration(
            failure_policy="coverage_declare",
            interaction="single_shot",
            difficulty="impossible",  # type: ignore[arg-type]
        )


def test_declaration_requires_difficulty_with_no_default() -> None:
    # INVARIANT: a defaulted tier is a tier nobody assigned — every benchmark's difficulty is a
    # reviewed judgment call, so the field is required exactly like its two siblings (OME-1257).
    with pytest.raises(TypeError):
        BenchmarkDeclaration(  # type: ignore[call-arg]
            failure_policy="coverage_declare",
            interaction="single_shot",
        )


def test_declaration_requires_every_field_with_no_defaults() -> None:
    # INVARIANT: no value on this record may fall back to a default — a defaulted
    # policy is exactly the hidden-default failure OME-1039 exists to prevent.
    with pytest.raises(TypeError):
        BenchmarkDeclaration(failure_policy="withhold")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        BenchmarkDeclaration(interaction="single_shot")  # type: ignore[call-arg]


def test_wrong_declaration_type_is_refused() -> None:
    values = _benchmark_values()
    values["declaration"] = {"failure_policy": "withhold", "interaction": "single_shot"}
    with pytest.raises(TypeError):
        Benchmark(**values)  # type: ignore[arg-type]


def test_catalog_entry_names_every_declared_value() -> None:
    entry = Benchmark(**_benchmark_values()).catalog_entry()  # type: ignore[arg-type]
    assert entry["failure_policy"] == "coverage_declare"
    assert entry["interaction"] == "single_shot"
    # OME-1257: the tier rides the same declaration block, so every catalogue row
    # carries it without a serving change.
    assert entry["difficulty"] == "easy"


def test_resource_names_every_declared_value() -> None:
    resource = Benchmark(**_benchmark_values()).resource(limit=1)  # type: ignore[arg-type]
    assert resource["failure_policy"] == "coverage_declare"
    assert resource["interaction"] == "single_shot"
    assert resource["difficulty"] == "easy"


def test_every_builtin_benchmark_declares_its_actual_policy() -> None:
    # INVARIANT: the declaration tells the truth about the code. Every benchmark reduces through the
    # shared `finalize_candidate_result`, which hands the scorer the Cases the declared policy
    # counts and publishes coverage: `coverage_declare` scores exactly the gradeable subset;
    # `withhold` (OME-1642) scores every selected Case, a failed Case adding 0. A benchmark may
    # only declare `withhold` when its scorer is a mean of Case grades (never a whole-run metric
    # or an inverted grade), and may only declare an interaction it actually performs.
    #
    # AIDEV-NOTE: an explicit per-benchmark table rather than a blanket assertion. A new benchmark
    # must add its row deliberately, and a benchmark that CHANGES its declaration trips here — which
    # a loop over "all single_shot" could not catch once a second shape existed (OME-1126).
    expected = {
        # OME-1257 third element: the hand-assigned difficulty tier. The rationale for
        # each assignment lives as a comment at the benchmark's own declaration site; this
        # table pins the reviewed outcome so a silent tier change trips loudly.
        # MedXpertQA invokes the Candidate twice per Case: turn 1 reasons, turn 2 commits against
        # a bare trigger. Its ungradeable Cases still go to the shared finalizer, which counts
        # each as 0 in the mean (OME-1642), hence withhold.
        "medxpert": ("withhold", "multi_turn", "hard"),
    }
    # Plugin-contributed benchmarks (OME-1115) are present only when their extra is
    # installed; their rows are still explicit, so a new imported benchmark — or a changed
    # declaration — trips here exactly like a home-grown one.
    expected_plugin = {
        "inspect-gsm8k": ("withhold", "single_shot", "easy"),
        "inspect-mmlu": ("withhold", "single_shot", "medium"),
        # OME-1116 milestone C: the eight generated benchmarks, every one single-shot
        # through the shared row machine.
        "inspect-arc_easy": ("withhold", "single_shot", "easy"),
        "inspect-arc_challenge": ("withhold", "single_shot", "medium"),
        "inspect-commonsense_qa": ("withhold", "single_shot", "easy"),
        "inspect-mmlu_pro": ("withhold", "single_shot", "medium"),
        "inspect-winogrande": ("withhold", "single_shot", "easy"),
        "inspect-race_h": ("withhold", "single_shot", "easy"),
        "inspect-paws": ("withhold", "single_shot", "easy"),
        "inspect-boolq": ("withhold", "single_shot", "easy"),
        # OME-1240: the judged proof benchmark — frontier-research material, hard tier.
        "inspect-frontierscience": ("withhold", "single_shot", "hard"),
        # OME-1238 landed these two mid-stack; tiers assigned in the OME-1257 rebase.
        "inspect-aime24": ("withhold", "single_shot", "medium"),
        "inspect-aime25": ("withhold", "single_shot", "medium"),
        # OME-1253 batch 1 landed mid-stack too; tiers assigned in the same rebase.
        "inspect-musr": ("withhold", "single_shot", "medium"),
        "inspect-wmdp_bio": ("withhold", "single_shot", "medium"),
        "inspect-wmdp_chem": ("withhold", "single_shot", "medium"),
        "inspect-wmdp_cyber": ("withhold", "single_shot", "medium"),
        "inspect-hellaswag": ("withhold", "single_shot", "easy"),
        # OME-1264 batch 1: the six text LAB-Bench subsets — expert biology
        # research MCQ, all hard, all single-shot through the shared row machine.
        "inspect-lab_bench_litqa": ("withhold", "single_shot", "hard"),
        "inspect-lab_bench_suppqa": ("withhold", "single_shot", "hard"),
        "inspect-lab_bench_dbqa": ("withhold", "single_shot", "hard"),
        "inspect-lab_bench_protocolqa": ("withhold", "single_shot", "hard"),
        "inspect-lab_bench_seqqa": ("withhold", "single_shot", "hard"),
        "inspect-lab_bench_cloning_scenarios": ("withhold", "single_shot", "hard"),
        # OME-1269: Thai grade-12 national benchmark MCQ, the first question-filter benchmark.
        "inspect-onet_m6": ("withhold", "single_shot", "medium"),
        # OME-1269: biomedical yes/no/maybe MCQ over a given abstract (question filter).
        "inspect-pubmedqa": ("withhold", "single_shot", "medium"),
        # OME-1269: over-refusal of harmless prompts, LLM-judged (gated dataset).
        "inspect-xstest_safe": ("coverage_declare", "single_shot", "easy"),
        # OME-1400: refusal of mild unsafe prompts, LLM-judged, scored by refusal rate.
        "inspect-xstest_unsafe": ("coverage_declare", "single_shot", "easy"),
        # OME-1273: the first Task-replay Benchmarks — AGIEval's English MCQ exams, MedQA
        # and MGSM's English set; tiers as their rows argue them.
        "inspect-agieval_lsat_ar": ("withhold", "single_shot", "hard"),
        "inspect-agieval_lsat_lr": ("withhold", "single_shot", "medium"),
        "inspect-agieval_lsat_rc": ("withhold", "single_shot", "medium"),
        "inspect-agieval_sat_math": ("withhold", "single_shot", "easy"),
        "inspect-agieval_sat_en": ("withhold", "single_shot", "easy"),
        "inspect-agieval_sat_en_without_passage": ("withhold", "single_shot", "hard"),
        "inspect-agieval_aqua_rat": ("withhold", "single_shot", "medium"),
        "inspect-agieval_logiqa_en": ("withhold", "single_shot", "hard"),
        "inspect-medqa": ("withhold", "single_shot", "medium"),
        "inspect-mgsm_en": ("withhold", "single_shot", "easy"),
        # OME-1273: the plain Task-replay packages.
        "inspect-bbq": ("withhold", "single_shot", "medium"),
        "inspect-piqa": ("withhold", "single_shot", "easy"),
        "inspect-cybermetric_80": ("withhold", "single_shot", "easy"),
        "inspect-cybermetric_500": ("withhold", "single_shot", "easy"),
        "inspect-cybermetric_2000": ("withhold", "single_shot", "easy"),
        "inspect-cybermetric_10000": ("withhold", "single_shot", "easy"),
        "worldsense": ("withhold", "single_shot", "hard"),
        "inspect-sevenllm_mcq_zh": ("withhold", "single_shot", "medium"),
        "inspect-sevenllm_mcq_en": ("withhold", "single_shot", "medium"),
        # OME-1371: CoCoNot — declining what it should (noncompliance rate), and answering
        # look-alike harmless requests; both LLM-judged from a per-category rubric.
        "inspect-coconot_original": ("coverage_declare", "single_shot", "medium"),
        "inspect-coconot_contrast": ("coverage_declare", "single_shot", "easy"),
        # OME-1273: SAD-mini; tiers as their rows argue them from the eval's own report.
        "inspect-sad_facts_llms": ("withhold", "single_shot", "medium"),
        "inspect-sad_facts_human_defaults": ("withhold", "single_shot", "easy"),
        "inspect-sad_influence": ("withhold", "single_shot", "medium"),
        "inspect-sad_stages_full": ("withhold", "single_shot", "hard"),
        "inspect-sad_stages_oversight": ("withhold", "single_shot", "hard"),
        # OME-1273: over-refusal of harmless security coding requests; frontier models
        # accept nearly all of them in the eval's own report.
        "inspect-cyse4_mitre_frr": ("coverage_declare", "single_shot", "easy"),
        # OME-1273: pre_flight and bbeh; tiers as their rows argue them from the evals' own
        # reports.
        "inspect-pre_flight": ("withhold", "single_shot", "medium"),
        "inspect-bbeh": ("withhold", "single_shot", "hard"),
        # OME-1268: SQuAD 2.0 is saturated material (frontier models above 90 F1); MATH still
        # separates reasoning from non-reasoning models (70s vs above 90 on exact match).
        "inspect-squad": ("withhold", "single_shot", "medium"),
        # OME-1602 PR 6: DROP, graded through the eval's own answer reader.
        "inspect-drop": ("withhold", "single_shot", "medium"),
        # OME-1602: the remaining single-turn imports whose decisions were all made. aime26 is
        # its siblings' tier; the refusal Benchmarks are easy for aligned frontier models; the
        # SimpleQA pair, UCCB, Math.Find and AIR-Bench still separate them. infinite_bench and
        # air_bench are local Tasks (built from inspect_evals' own), so they keep their bare key.
        "inspect-aime26": ("withhold", "single_shot", "medium"),
        "inspect-simpleqa": ("coverage_declare", "single_shot", "medium"),
        "inspect-simpleqa_verified": ("coverage_declare", "single_shot", "medium"),
        "inspect-fortress_benign": ("coverage_declare", "single_shot", "easy"),
        "inspect-strong_reject": ("coverage_declare", "single_shot", "easy"),
        "inspect-uccb": ("withhold", "single_shot", "medium"),
        "infinite_bench_math_find": ("withhold", "single_shot", "medium"),
        "air_bench": ("coverage_declare", "single_shot", "medium"),
        # OME-1696: BIG-Bench Hard, a local Task built from inspect_evals' own (bare key);
        # frontier models pass 0.9 with chain of thought but not at ceiling, like MMLU.
        "bbh": ("withhold", "single_shot", "medium"),
        # OME-1696: MedMCQA, a local Task we wrote (bare key); professional-exam medicine
        # like medqa.
        "medmcqa": ("withhold", "single_shot", "medium"),
        # OME-1602 PR 5: the multi-letter-key imports; StereoSet's coherence score is near its
        # ceiling, the malware questions are hard for every model the paper ran.
        "inspect-truthfulqa_mc1": ("withhold", "single_shot", "medium"),
        "inspect-chembench": ("withhold", "single_shot", "medium"),
        "stereoset": ("withhold", "single_shot", "easy"),
        "inspect-cyse4_malware_analysis": ("withhold", "single_shot", "hard"),
        "inspect-cyse4_threat_intelligence": ("withhold", "single_shot", "medium"),
        # OME-1513: a local Task keeps its bare key as its id — nothing came from inspect_evals.
        "musique": ("withhold", "single_shot", "hard"),
        # OME-1476: the second local Task, and the first published Benchmark with Attempts.
        "arc_agi_2": ("coverage_declare", "single_shot", "hard"),
        # OME-1527: ContractEval moved from its hand-built folder to a local Task, keeping its
        # id and declaration. It answers each Case once; a reply quoting the wrong sentences is
        # GRADED (0.0, and it keeps its cell in the confusion matrix), so only never-graded
        # Cases reach the shared finalizer — coverage_declare.
        "contracteval": ("coverage_declare", "single_shot", "medium"),
        # OME-1527: GDPval-text moved the same way, keeping its id and declaration. A judged
        # Case whose judge never gives a verdict fails by name and counts 0 in the mean
        # (OME-1642) — withhold.
        "gdpval-text": ("withhold", "single_shot", "hard"),
        # OME-1527: draco and draco-3pass moved the same way, keeping their ids and
        # declarations. A Case with no valid judge verdict in any pass fails by name, so only
        # graded Cases reach the mean — coverage_declare.
        "draco": ("coverage_declare", "single_shot", "hard"),
        "draco-3pass": ("coverage_declare", "single_shot", "hard"),
        # OME-1527: healthbench-worst30 and healthbench-professional moved the same way, keeping
        # their ids and declarations. A Case whose judge never gives a verdict fails by name, so
        # only graded Cases reach the mean (or professional's clip of it) — coverage_declare.
        "healthbench-worst30": ("coverage_declare", "single_shot", "hard"),
        "healthbench-professional": ("coverage_declare", "single_shot", "hard"),
        # OME-1527: ifeval moved the same way, keeping its id, declaration and tier. A Case the
        # Candidate failed never reaches the checker, so only graded Cases reach the tally —
        # coverage_declare.
        "ifeval": ("coverage_declare", "single_shot", "medium"),
        # OME-1481: FRAMES with its gold articles given, a local Task. A Case whose judge
        # never decides, or whose prompt overflows the Candidate's window, fails by name and
        # counts 0 in the mean (OME-1642) — withhold.
        "frames_oracle": ("withhold", "single_shot", "medium"),
        "inspect-math": ("withhold", "single_shot", "medium"),
    }
    actual = {
        benchmark.id: (
            benchmark.declaration.failure_policy,
            benchmark.declaration.interaction,
            benchmark.declaration.difficulty,
        )
        for benchmark in BUILTIN_BENCHMARKS
    }
    # WHY by the spec rows and not by the "inspect-" prefix (OME-1513): a local Task's id is
    # its bare key, so the prefix no longer tells plugin rows from core ones; the rows do.
    # WHY the rows and not benchmark_registrations(): assembling a row reads inspect-ai's
    # installed version for the revision pin, and this lane runs without the extra in CI.
    from screamingface_engine_inspect.benchmarks import BENCHMARKS
    from screamingface_engine_inspect.single_shot import imported_benchmark_id

    plugin_ids = {imported_benchmark_id(spec.key, spec.origin) for spec in BENCHMARKS}
    plugin_actual = {benchmark: row for benchmark, row in actual.items() if benchmark in plugin_ids}
    core_actual = {
        benchmark: row for benchmark, row in actual.items() if benchmark not in plugin_actual
    }
    assert core_actual == expected
    # Every registered imported benchmark must have its explicit row (subset, not equality:
    # which plugin benchmarks are present depends on the installed extra and, mid-stack, on
    # how many benchmark PRs have landed).
    assert plugin_actual == {benchmark: expected_plugin[benchmark] for benchmark in plugin_actual}


def test_each_benchmark_aggregate_reduces_through_the_shared_finalizer() -> None:
    # WHY: the failure-policy pins above are only TRUE while every benchmark funnels its
    # cases through the shared finalizer (score over the Cases the declared policy counts +
    # published coverage). This asserts the mechanism, not just the literal: a benchmark that stops
    # importing the shared finalize_candidate_result (hand-rolling its own reduction,
    # or shadowing the name) trips here and must revisit its declaration.
    # AIDEV-NOTE: import identity, not call-path proof — the e2e goldens' coverage rung
    # proves the call path; full closure lands when the shared grading code itself consumes
    # failure_policy (`OME-1097`+) and the policy stops being prose entirely.
    from screamingface_engine.benchmarks import aggregation
    from screamingface_engine.benchmarks.shared_grading import benchmark_aggregation

    # The shared BenchmarkAggregation path (OME-1097) reduces through the shared finalizer —
    # same mechanism, one hop up. No hand-built Benchmark uses it any more: healthbench,
    # ifeval (folded in OME-1101) and draco (OME-1100) are local inspect Tasks since OME-1527.
    assert benchmark_aggregation.finalize_candidate_result is aggregation.finalize_candidate_result
