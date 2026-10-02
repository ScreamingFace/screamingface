# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The generated benchmark rows — every imported benchmark's catalogue contract, in one place.

INVARIANT the suite defends: a benchmark is two data rows the importer generated and a
human reviewed — so each row pair must (1) register under its `inspect-<key>` id,
(2) pin a 40-hex dataset revision and a positive case count (benchmark identity), (3)
declare the draft-feedback offer by family — free-text benchmarks carry it, MCQ benchmarks are
refused it (OME-796) — and (4) point at a scorer and templates that actually
resolve inside the pinned eval package. Catalogue prose is filled (never TODO):
onboarding is AI-first, and unreviewed placeholder prose must fail CI, not ship.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

from importlib import import_module

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    benchmark_registrations,
    imported_benchmark,
)
from screamingface_engine_inspect.prepare import BENCHMARK_CASES, TASK_REPLAY_CASES  # noqa: E402

#: Every imported benchmark key and its family: "mcq" (choice scorer, draft-feedback offer
#: refused per OME-796), "free_text" (draft-feedback offer ON, spec §4), or "judged"
#: (LLM-judged — draft-feedback offer refused until the check-cost knob, OME-1116/OME-1240).
_EXPECTED_FAMILIES: dict[str, str] = {
    "gsm8k": "free_text",
    "mmlu": "mcq",
    "arc_easy": "mcq",
    "arc_challenge": "mcq",
    "commonsense_qa": "mcq",
    "mmlu_pro": "mcq",
    "winogrande": "mcq",
    "race_h": "mcq",
    "paws": "free_text",
    "boolq": "free_text",
    "aime24": "free_text",
    "aime25": "free_text",
    "musr": "mcq",
    "wmdp_bio": "mcq",
    "wmdp_chem": "mcq",
    "wmdp_cyber": "mcq",
    "hellaswag": "mcq",
    # LAB-Bench text subsets (OME-1264 batch 1): MCQ graded by the eval's OWN
    # precision_choice scorer — still the MCQ family (draft-feedback offer refused);
    # FigQA/TableQA are image-based and stay out of the text-only prepare.
    "lab_bench_litqa": "mcq",
    "lab_bench_suppqa": "mcq",
    "lab_bench_dbqa": "mcq",
    "lab_bench_protocolqa": "mcq",
    "lab_bench_seqqa": "mcq",
    "lab_bench_cloning_scenarios": "mcq",
    "frontierscience": "judged",
    # OME-1269: the first question-filter benchmark — the eval's own filter picks the
    # questions; MCQ graded by the choice scorer, no draft-feedback offer.
    "onet_m6": "mcq",
    # OME-1269: the question filter keeps the eval's 500-question test list of 1,000 rows.
    "pubmedqa": "mcq",
    # OME-1269: judged compliance on XSTest's safe prompts — no answer key.
    "xstest_safe": "judged",
    # OME-1400: XSTest's unsafe prompts, scored by refusal rate (1 − the judge's grade).
    "xstest_unsafe": "judged",
    # OME-1273: the first Task-replay Benchmarks — their Cases come from calling the eval's
    # own task function, sealed by a Case Digest (TASK_REPLAY_CASES, not BENCHMARK_CASES).
    "agieval_lsat_ar": "mcq",
    "agieval_lsat_lr": "mcq",
    "agieval_lsat_rc": "mcq",
    "agieval_sat_math": "mcq",
    "agieval_sat_en": "mcq",
    "agieval_sat_en_without_passage": "mcq",
    "agieval_aqua_rat": "mcq",
    "agieval_logiqa_en": "mcq",
    "medqa": "mcq",
    "mgsm_en": "free_text",
    # OME-1273: the plain packages. worldsense is MCQ by its Samples' choices (two- or
    # three-way: TRUE/FALSE, POSSIBLE/IMPOSSIBLE, or 1/2/3), though it asks with generate()
    # and a pattern scorer.
    "bbq": "mcq",
    "piqa": "mcq",
    "cybermetric_80": "mcq",
    "cybermetric_500": "mcq",
    "cybermetric_2000": "mcq",
    "cybermetric_10000": "mcq",
    "worldsense": "mcq",
    "sevenllm_mcq_zh": "mcq",
    "sevenllm_mcq_en": "mcq",
    # OME-1273: SAD-mini's four importable tasks, choice-shaped and graded by the eval's
    # own lenient scorer (stages_full is refused: three Samples have an empty body).
    "sad_facts_llms": "mcq",
    "sad_facts_human_defaults": "mcq",
    "sad_influence": "mcq",
    "sad_stages_oversight": "mcq",
}

_NEW_KEYS: tuple[str, ...] = tuple(k for k in _EXPECTED_FAMILIES if k not in ("gsm8k", "mmlu"))
#: The new keys prepared from a pinned Hugging Face revision; the Task-replay keys have no
#: dataset revision or row rule to pin, and their own twins sit at the end of this file.
_HF_KEYS: tuple[str, ...] = tuple(k for k in _NEW_KEYS if k not in TASK_REPLAY_CASES)


def test_catalogue_holds_every_imported_benchmark() -> None:
    """OME-1116 acceptance: ≥10 imported benchmarks; the row table IS the catalogue."""

    assert {spec.key for spec in BENCHMARKS} == set(_EXPECTED_FAMILIES)
    # OME-1273: a second registry joins the catalogue; the owner granted the edit of this
    # prior assertion (--skip-append-only, first on #1194).
    assert set(BENCHMARK_CASES) | set(TASK_REPLAY_CASES) == set(_EXPECTED_FAMILIES)
    assert not set(BENCHMARK_CASES) & set(TASK_REPLAY_CASES)
    ids = [registration.benchmark.id for registration in benchmark_registrations()]
    assert len(ids) == len(set(ids)) == len(_EXPECTED_FAMILIES)
    assert all(benchmark_id.startswith("inspect-") for benchmark_id in ids)


def test_every_benchmark_from_this_plugin_names_inspect_evals_as_its_source() -> None:
    """The catalogue must name the collection each benchmark came FROM, not this repo.

    INVARIANT: `origin` defaults to "screamingface" (a true fact for benchmarks authored
    here), so an import lane has to pass its own collection explicitly — the default is
    silently wrong for any benchmark we merely brought in. The listing groups by this field,
    so a defaulted row makes the imported shelf disappear into our own group.

    Scope: `inspect_evals` is *this plugin's* source, not what "imported" means in
    general — a future collection arrives as its own plugin stamping its own origin,
    and would carry its own copy of this assertion. Asserted over the REAL
    registrations: a synthetic benchmark constructed with the origin passed by hand
    proves the wire format, never the benchmark factory.
    """

    origins = {
        registration.benchmark.id: registration.benchmark.origin
        for registration in benchmark_registrations()
    }
    assert set(origins.values()) == {"inspect_evals"}, origins


def test_benchmark_revisions_are_distinct() -> None:
    """Two benchmarks must never share a revision — the revision addresses the benchmark."""

    revisions = {imported_benchmark(key).benchmark.revision for key in _EXPECTED_FAMILIES}
    assert len(revisions) == len(_EXPECTED_FAMILIES)


@pytest.mark.parametrize("key", sorted(_HF_KEYS))
def test_cases_row_pins_benchmark_identity(key: str) -> None:
    cases_spec = BENCHMARK_CASES[key]
    assert len(cases_spec.dataset_revision) == 40
    int(cases_spec.dataset_revision, 16)
    assert cases_spec.case_count > 0
    assert cases_spec.dataset and cases_spec.split


@pytest.mark.parametrize("key", sorted(_HF_KEYS))
def test_cases_row_references_resolve_inside_the_pinned_eval(key: str) -> None:
    """The rows POINT at the eval's own code; a dangling reference must fail CI,
    not the image build."""

    cases_spec = BENCHMARK_CASES[key]
    references: list[str] = [cases_spec.record_to_sample]
    if cases_spec.prompt_template is not None:
        references.append(cases_spec.prompt_template)
    if cases_spec.choice_template is not None:
        references.append(cases_spec.choice_template)
    if cases_spec.system_message is not None:
        references.append(cases_spec.system_message)
    if cases_spec.question_filter_task is not None:
        # The question-filter pointer (OME-1269): the prepare step CALLS it at image build.
        references.append(cases_spec.question_filter_task)
    for reference in references:
        module_name, _, attribute = reference.partition(":")
        assert hasattr(import_module(module_name), attribute), reference


@pytest.mark.parametrize("key", sorted(_NEW_KEYS))
def test_benchmark_row_declares_its_family_check_surface(key: str) -> None:
    """OME-796: pass/fail feedback over a handful of options is an elimination
    attack — MCQ benchmarks are refused the surface, free-text benchmarks carry it."""

    benchmark = imported_benchmark(key).benchmark
    if _EXPECTED_FAMILIES[key] == "free_text":
        assert benchmark.check_surface is not None
    else:
        # "mcq" (elimination attack) and "judged" (no check-cost knob yet) alike.
        assert benchmark.check_surface is None


@pytest.mark.parametrize("key", sorted(_NEW_KEYS))
def test_benchmark_row_scorer_resolves_and_constructs(key: str) -> None:
    spec = next(spec for spec in BENCHMARKS if spec.key == key)
    module_name, _, attribute = spec.scorer.partition(":")
    constructor = getattr(import_module(module_name), attribute)
    assert constructor(**dict(spec.scorer_kwargs)) is not None


@pytest.mark.parametrize("key", sorted(_NEW_KEYS))
def test_benchmark_row_prose_is_filled_not_todo(key: str) -> None:
    """AI-first onboarding: the importing agent writes the catalogue prose; a
    leftover TODO placeholder means the diff was never finished."""

    spec = next(spec for spec in BENCHMARKS if spec.key == key)
    for prose in (spec.title, spec.description, spec.focus, spec.dataset_url):
        assert prose and "TODO" not in prose
    # A Task-replay row links wherever its Cases live (a GitHub repo for agieval); the owner
    # granted the edit of this prior assertion (--skip-append-only, first on #1194).
    hub_only: bool = key not in TASK_REPLAY_CASES
    assert spec.dataset_url.startswith(
        "https://huggingface.co/datasets/" if hub_only else "https://"
    )


def test_benchmarks_whose_eval_shuffles_carry_a_pinned_seed() -> None:
    """The upstream evals of these benchmarks randomize question order per run
    (hf_dataset shuffle=True); an import must pin one order — a dropped shuffle
    was the 2026-09-17 review blocker, and this set is its regression pin."""

    seeded: set[str] = {
        key for key, spec in BENCHMARK_CASES.items() if spec.shuffle_seed is not None
    }
    # aime24/aime25: OURS policy seed (owner-approved 2026-09-22) — upstream serves
    # dataset order (AIME I then II, roughly ascending difficulty within each), so an
    # unseeded import would give a limited run only the easier AIME I half.
    # musr: upstream shuffles per run (hf_dataset shuffle=True, no seed), so the
    # import pins one order. wmdp benchmarks serve upstream order — no seed.
    # hellaswag: OURS policy seed (review finding on PR #1018) — the pinned
    # validation split is domain-grouped (3,243 ActivityNet rows then 6,799
    # WikiHow), so an unshuffled limit ≤ 3243 run would examine zero WikiHow.
    # lab_bench_*: upstream shuffles rows per run (shuffle=True, no seed), so
    # the import pins one order (OURS policy seed, OME-1264 batch 1).
    assert seeded == {
        "mmlu",
        "commonsense_qa",
        "mmlu_pro",
        "race_h",
        "paws",
        "boolq",
        "aime24",
        "aime25",
        "musr",
        "hellaswag",
        "lab_bench_litqa",
        "lab_bench_suppqa",
        "lab_bench_dbqa",
        "lab_bench_protocolqa",
        "lab_bench_seqqa",
        "lab_bench_cloning_scenarios",
        # frontierscience: mixed formats/subjects in dataset order — OURS policy
        # seed so a limited run spans both formats (sweep 2026-09-22, OME-1240).
        "frontierscience",
        # onet_m6: upstream shuffles rows per run (shuffle=True, no seed), so the
        # import pins one order (OURS policy seed, OME-1269).
        "onet_m6",
    }


def test_lab_bench_benchmarks_pin_a_choice_order() -> None:
    """LAB-Bench builds every case with the correct answer FIRST and shuffles
    choices per run (shuffle_choices=True, unseeded) — without a pinned choice
    order every prepared answer would be 'A'. The six text benchmarks must carry the
    policy choice-shuffle seed, and it must ride benchmark identity."""

    from screamingface_engine_inspect.benchmarks import _revision_pins

    lab_bench_keys = {key for key in BENCHMARK_CASES if key.startswith("lab_bench_")}
    assert lab_bench_keys == {
        "lab_bench_litqa",
        "lab_bench_suppqa",
        "lab_bench_dbqa",
        "lab_bench_protocolqa",
        "lab_bench_seqqa",
        "lab_bench_cloning_scenarios",
    }
    for key in sorted(lab_bench_keys):
        assert BENCHMARK_CASES[key].choice_shuffle_seed is not None, key
        assert f"choice_shuffle_seed={BENCHMARK_CASES[key].choice_shuffle_seed}" in _revision_pins(
            BENCHMARK_CASES[key]
        )


def test_lab_bench_pins_track_upstreams_own_revision_constant() -> None:
    """Same drift guard as aime24/25/hellaswag, once for the whole family: every
    lab_bench sha is COPIED from the eval's own pinned constant — a dependency
    bump that moves upstream's pin must fail here."""

    from inspect_evals.lab_bench.lab_bench import LAB_BENCH_DATASET_REVISION as UPSTREAM

    for key in (k for k in BENCHMARK_CASES if k.startswith("lab_bench_")):
        assert BENCHMARK_CASES[key].dataset_revision == UPSTREAM, key


def test_aime24_pin_tracks_upstreams_own_revision_constant() -> None:
    """The aime24 sha is COPIED from the eval's own pinned constant (upstream pins
    win at import time) — a dependency bump that moves upstream's pin must fail
    here instead of silently serving a different benchmark than the eval means."""

    from inspect_evals.aime2024.aime2024 import AIME2024_DATASET_REVISION

    from screamingface_engine_inspect.pins import AIME24_DATASET_REVISION

    assert AIME24_DATASET_REVISION == AIME2024_DATASET_REVISION


def test_aime25_pin_tracks_upstreams_own_revision_constant() -> None:
    """Same drift guard as aime24: the sha is copied from the eval's own pinned
    constant — a dependency bump that moves upstream's pin must fail here."""

    from inspect_evals.aime2025.aime2025 import AIME2025_DATASET_REVISION

    from screamingface_engine_inspect.pins import AIME25_DATASET_REVISION

    assert AIME25_DATASET_REVISION == AIME2025_DATASET_REVISION


def test_hellaswag_pin_tracks_upstreams_own_revision_constant() -> None:
    """Same drift guard as aime24/25: the sha is COPIED from the eval's own
    pinned constant — a dependency bump that moves upstream's pin must fail
    here, never leave us preparing the old sha with the new scorer."""

    from inspect_evals.hellaswag.hellaswag import HELLASWAG_DATASET_REVISION as UPSTREAM

    from screamingface_engine_inspect.pins import HELLASWAG_DATASET_REVISION

    assert HELLASWAG_DATASET_REVISION == UPSTREAM


def test_choice_shuffle_seed_rides_benchmark_identity() -> None:
    """OME-1264: the pinned choice order is part of the benchmark a candidate sits —
    a re-import that gains or loses the choice-shuffle seed cannot keep the
    benchmark's revision identity."""

    from dataclasses import replace

    from screamingface_engine_inspect.benchmarks import _revision_pins

    pins = _revision_pins(replace(BENCHMARK_CASES["mmlu"], choice_shuffle_seed=7))
    assert "choice_shuffle_seed=7" in pins
    # And a benchmark without one carries no such pin (the field is conditional).
    assert not any(
        p.startswith("choice_shuffle_seed=") for p in _revision_pins(BENCHMARK_CASES["mmlu"])
    )


def test_data_files_and_features_ride_benchmark_identity() -> None:
    """OME-1264 extension 2: data_files selects WHICH files load and features
    fixes their schema — both change the benchmark, so both ride the benchmark's
    revision identity."""

    from dataclasses import replace

    from screamingface_engine_inspect.benchmarks import _revision_pins

    spec = replace(BENCHMARK_CASES["mmlu"], data_files={"t": "t.jsonl"}, features="fake_mod:FT")
    pins = _revision_pins(spec)
    assert 'data_files={"t": "t.jsonl"}' in pins
    assert "features=fake_mod:FT" in pins
    # And a benchmark without them carries neither pin (the fields are conditional).
    assert not any(
        p.startswith(("data_files=", "features=")) for p in _revision_pins(BENCHMARK_CASES["mmlu"])
    )


def test_system_message_pointer_rides_benchmark_identity() -> None:
    """Review finding on PR #1018: adding or dropping the leading instruction
    changes the benchmark a candidate sits, so the pointer must move the benchmark's
    revision identity — a re-import that lost it cannot keep the revision."""

    from screamingface_engine_inspect.benchmarks import _revision_pins

    pins = _revision_pins(BENCHMARK_CASES["hellaswag"])
    assert "system_message=inspect_evals.hellaswag.hellaswag:SYSTEM_MESSAGE" in pins
    # And a benchmark without one carries no such pin (the field is conditional).
    assert not any(p.startswith("system_message=") for p in _revision_pins(BENCHMARK_CASES["musr"]))


def test_onet_m6_filters_through_its_task_with_the_named_exclusion() -> None:
    """OME-1269's first question-filter benchmark. Its questions are whatever the eval's own
    filter keeps, minus the owner-approved named deviation (6 questions inspect keeps
    whose answer letter lies past their choices), and it renders inspect's own
    chain-of-thought template because the eval passes multiple_choice(cot=True).
    The question filter and the exclusion change which questions are served, so both ride its
    revision; the template pointer does not (template pointers predate revision-pin
    coverage — see benchmarks._revision_pins)."""

    from inspect_evals.onet.onet import ONET_DATASET_REVISION as UPSTREAM

    from screamingface_engine_inspect.benchmarks import _revision_pins

    row = BENCHMARK_CASES["onet_m6"]
    assert row.dataset_revision == UPSTREAM
    assert row.question_filter_task == "inspect_evals.onet.onet:onet_m6"
    assert row.choice_template == "inspect_ai.solver._multiple_choice:SINGLE_ANSWER_TEMPLATE_COT"
    assert row.excluded_sample_ids is not None and len(row.excluded_sample_ids) == 6
    assert row.case_count == 397 - 6
    pins = _revision_pins(row)
    assert "question_filter_task=inspect_evals.onet.onet:onet_m6" in pins
    assert any(pin.startswith("excluded_sample_ids=") for pin in pins)


def test_pubmedqa_prepares_the_evals_test_list_through_its_task() -> None:
    """pubmedqa loads all 1,000 labelled questions and keeps the 500 on its bundled
    test list; the benchmark runs the eval's task so its own filter keeps
    them, the count pins the KEPT 500, and the eval's template renders them."""

    from inspect_evals.pubmedqa.pubmedqa import PUBMEDQA_DATASET_REVISION as UPSTREAM

    from screamingface_engine_inspect.benchmarks import _revision_pins

    row = BENCHMARK_CASES["pubmedqa"]
    assert row.dataset_revision == UPSTREAM
    assert row.question_filter_task == "inspect_evals.pubmedqa.pubmedqa:pubmedqa"
    assert row.choice_template == "inspect_evals.pubmedqa.pubmedqa:TEMPLATE"
    assert row.case_count == 500
    assert row.excluded_sample_ids is None
    assert "question_filter_task=inspect_evals.pubmedqa.pubmedqa:pubmedqa" in _revision_pins(row)


def test_xstest_safe_is_judged_from_the_evals_own_prompt_with_no_answer_key() -> None:
    """xstest_safe keeps the 250 safe prompts through the eval's own subset filter,
    has no answer key (the judge grades complied / refused from question and reply),
    needs a Hugging Face token (gated dataset), and its judge prompt is a verbatim
    copy of the eval's — a dependency bump that edits upstream's prompt fails here."""

    from inspect_evals.xstest.xstest import XSTEST_DATASET_REVISION as UPSTREAM
    from inspect_evals.xstest.xstest import scorer_instructions, scorer_template

    from screamingface_engine_inspect.benchmarks import BENCHMARKS, _revision_pins

    row = BENCHMARK_CASES["xstest_safe"]
    assert row.dataset_revision == UPSTREAM
    assert row.question_filter_task == "inspect_evals.xstest.xstest:xstest"
    assert row.question_filter_task_args == {"subset": "safe"}
    assert row.case_count == 250
    assert row.has_answer_key is False
    assert row.needs_hf_token is True
    assert 'question_filter_task_args={"subset": "safe"}' in _revision_pins(row)
    benchmark = next(spec for spec in BENCHMARKS if spec.key == "xstest_safe")
    assert benchmark.scorer_kwargs["template"] == scorer_template
    assert benchmark.scorer_kwargs["instructions"] == scorer_instructions
    assert "{criterion}" not in scorer_template


def test_xstest_safe_names_upstreams_own_metric_and_generate_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The benchmark reports the mean grade (C=1, P=0.5, I=0); upstream reports
    refusal_rate and runs at temperature 0 with 256 max tokens. Both deviations are
    named on the benchmark — if a dependency bump changes either upstream fact, this
    fails and the benchmark's notes must be revisited (review on PR #1112)."""

    from importlib import import_module

    from inspect_ai._util.registry import registry_info
    from inspect_ai.dataset import MemoryDataset, Sample

    from screamingface_engine_inspect.benchmarks import BENCHMARKS

    module = import_module("inspect_evals.xstest.xstest")
    monkeypatch.setattr(
        module,
        "hf_dataset",
        lambda *args, **kwargs: MemoryDataset([Sample(input="q", metadata={"label": "safe"})]),
    )
    task = module.xstest(subset="safe")

    assert [registry_info(metric).name for metric in task.metrics] == ["inspect_evals/refusal_rate"]
    assert (task.config.temperature, task.config.max_tokens) == (0.0, 256)
    benchmark = next(spec for spec in BENCHMARKS if spec.key == "xstest_safe")
    assert "refusal rate = 100 x (1 - correct / scored cases)" in benchmark.description


# ── OME-1273: Task-replay declarations (spec R7) ────────────────────────────────

from screamingface_engine_inspect.prepare import LICENSE_TODO, TASK_REPLAY_CASES  # noqa: E402


def test_task_replay_declarations_carry_an_owner_license_decision() -> None:
    """Spec R7: a license left as TODO means the owner never decided; the diff is unfinished.

    Sits next to test_benchmark_row_prose_is_filled_not_todo, which guards the catalogue
    prose. Empty registry today; it earns its keep when PR 4 lands the first declarations.
    """

    undecided: list[str] = [
        key for key, spec in TASK_REPLAY_CASES.items() if spec.license == LICENSE_TODO
    ]

    assert undecided == []


# ── OME-1273: Task-replay twins of the Hugging Face row contracts above ─────────


@pytest.mark.parametrize("key", sorted(TASK_REPLAY_CASES))
def test_task_replay_declaration_is_sealed(key: str) -> None:
    """The seal is what the image build checks: a count and a 64-hex Case Digest."""

    spec = TASK_REPLAY_CASES[key]
    assert spec.case_count > 0
    assert len(spec.case_digest) == 64 and spec.case_digest == spec.case_digest.lower()
    int(spec.case_digest, 16)


@pytest.mark.parametrize("key", sorted(TASK_REPLAY_CASES))
def test_task_replay_task_reference_resolves(key: str) -> None:
    """The task function the declaration points at must import — a dangling reference fails
    CI here, not the image build. WHY only the task: capture (#1219) renders the prompt from
    the Task's own solvers, so the declaration names no template."""

    module_name, _, attribute = TASK_REPLAY_CASES[key].task.partition(":")
    assert hasattr(import_module(module_name), attribute), TASK_REPLAY_CASES[key].task
