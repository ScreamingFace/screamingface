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
from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES  # noqa: E402

#: Every imported benchmark key and its family: "mcq" (choice scorer, draft-feedback offer
#: refused per OME-796), "free_text" (draft-feedback offer ON, spec §4), "judged"
#: (LLM-judged — draft-feedback offer refused until the check-cost knob, OME-1116/OME-1240),
#: or "reply_only" (no answer key, graded by the eval's own scorer from the reply alone;
#: draft-feedback offer refused, owner 2026-10-05: a pass/fail check over a refusal regex
#: lets a fusion re-word a draft until it slips past).
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
    # OME-1371: CoCoNot's two halves — judged from a per-category rubric, no answer key;
    # the judge answers in words, graded by the row's verdict map.
    "coconot_original": "judged",
    "coconot_contrast": "judged",
    # OME-1273: SAD-mini's five tasks, choice-shaped and graded by the eval's own lenient
    # scorer (stages_full leaves out three Samples whose body is empty, a Named Deviation).
    "sad_facts_llms": "mcq",
    "sad_facts_human_defaults": "mcq",
    "sad_influence": "mcq",
    "sad_stages_full": "mcq",
    "sad_stages_oversight": "mcq",
    # OME-1273: cyberseceval_4's false-refusal set, graded by its own refusal regex (R19).
    "cyse4_mitre_frr": "reply_only",
    # OME-1273: pre_flight asks four or five options through multiple_choice; bbeh asks for a
    # bare free-text answer graded by the eval's own rule-based matcher.
    "pre_flight": "mcq",
    "bbeh": "free_text",
    # OME-1268: the first Benchmarks with Named Scores. SQuAD answers in a few words against a
    # list of accepted spans (f1 headline, exact beside it); MATH ends with an ANSWER line
    # graded by two of the eval's three scorers (the self-grading one dropped by name).
    "squad": "free_text",
    "math": "free_text",
}

_NEW_KEYS: tuple[str, ...] = tuple(k for k in _EXPECTED_FAMILIES if k not in ("gsm8k", "mmlu"))


def test_catalogue_holds_every_imported_benchmark() -> None:
    """OME-1116 acceptance: ≥10 imported benchmarks; the row table IS the catalogue."""

    assert {spec.key for spec in BENCHMARKS} == set(_EXPECTED_FAMILIES)
    # OME-1460: one registry; every Imported Benchmark is a Task-replay declaration.
    assert set(TASK_REPLAY_CASES) == set(_EXPECTED_FAMILIES)
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


@pytest.mark.parametrize("key", sorted(_NEW_KEYS))
def test_benchmark_row_declares_its_family_check_surface(key: str) -> None:
    """OME-796: pass/fail feedback over a handful of options is an elimination
    attack — MCQ benchmarks are refused the surface, free-text benchmarks carry it."""

    benchmark = imported_benchmark(key).benchmark
    if _EXPECTED_FAMILIES[key] == "free_text":
        assert benchmark.check_surface is not None
    else:
        # "mcq" (elimination attack), "judged" (no check-cost knob yet) and "reply_only"
        # (re-wording past a refusal regex) alike.
        assert benchmark.check_surface is None


@pytest.mark.parametrize("key", sorted(_NEW_KEYS))
def test_benchmark_row_scorer_resolves_and_constructs(key: str) -> None:
    # WHY (OME-1460): a judged row names the "screamingface" judge model, a provider that
    # registers when judge_provider is imported, as assembly does; without it this test
    # passed only when an earlier test in the same worker had imported it.
    import_module("screamingface_engine_inspect.judge_provider")
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

    # OME-1460: every row is a Task-replay declaration; shuffle_seed is now the seed forced
    # through inspect's own shuffle on an hf_dataset call that shuffles with none (D1), so
    # exactly the rows whose eval does that carry one. aime24/aime25/hellaswag lost their
    # policy seed (their evals never shuffle: the Hub's order is served, spec Known
    # limitations); mmlu's eval seeds its own shuffle (seed=42); wmdp serves upstream order.
    seeded: set[str] = {
        key for key, spec in TASK_REPLAY_CASES.items() if spec.shuffle_seed is not None
    }
    assert seeded == {
        "commonsense_qa",
        "mmlu_pro",
        "race_h",
        "paws",
        "boolq",
        "musr",
        "lab_bench_litqa",
        "lab_bench_suppqa",
        "lab_bench_dbqa",
        "lab_bench_protocolqa",
        "lab_bench_seqqa",
        "lab_bench_cloning_scenarios",
        "frontierscience",
        "onet_m6",
    }


def test_lab_bench_benchmarks_pin_a_choice_order() -> None:
    """LAB-Bench builds every case with the correct answer FIRST and shuffles
    choices per run (shuffle_choices=True, unseeded) — without a pinned choice
    order every prepared answer would be 'A'. The six text benchmarks must carry the
    policy choice-shuffle seed, and it must ride benchmark identity."""

    # OME-1460: Task-replay declarations; the forced seed's order is sealed by the Case
    # Digest, which rides identity, so the seed needs no pin of its own (spec R7).
    lab_bench_keys = {key for key in TASK_REPLAY_CASES if key.startswith("lab_bench_")}
    assert lab_bench_keys == {
        "lab_bench_litqa",
        "lab_bench_suppqa",
        "lab_bench_dbqa",
        "lab_bench_protocolqa",
        "lab_bench_seqqa",
        "lab_bench_cloning_scenarios",
    }
    for key in sorted(lab_bench_keys):
        assert TASK_REPLAY_CASES[key].choice_shuffle_seed is not None, key


def test_lab_bench_pins_track_upstreams_own_revision_constant() -> None:
    """Same drift guard as aime24/25/hellaswag, once for the whole family: every
    lab_bench sha is COPIED from the eval's own pinned constant — a dependency
    bump that moves upstream's pin must fail here."""

    from inspect_evals.lab_bench.lab_bench import LAB_BENCH_DATASET_REVISION as UPSTREAM

    lab_bench_keys = [k for k in TASK_REPLAY_CASES if k.startswith("lab_bench_")]
    assert len(lab_bench_keys) == 6
    for key in lab_bench_keys:
        assert TASK_REPLAY_CASES[key].source_pins == {"futurehouse/lab-bench": UPSTREAM}, key


def test_aime24_pin_tracks_upstreams_own_revision_constant() -> None:
    """The aime24 sha is COPIED from the eval's own pinned constant (upstream pins
    win at import time) — a dependency bump that moves upstream's pin must fail
    here instead of silently serving a different benchmark than the eval means."""

    from inspect_evals.aime2024.aime2024 import AIME2024_DATASET_REVISION

    # OME-1460: the Hub pin now lives on the Task-replay declaration.
    assert set(TASK_REPLAY_CASES["aime24"].source_pins.values()) == {AIME2024_DATASET_REVISION}


def test_aime25_pin_tracks_upstreams_own_revision_constant() -> None:
    """Same drift guard as aime24: the sha is copied from the eval's own pinned
    constant — a dependency bump that moves upstream's pin must fail here."""

    from inspect_evals.aime2025.aime2025 import AIME2025_DATASET_REVISION

    # OME-1460: the Hub pin now lives on the Task-replay declaration.
    assert set(TASK_REPLAY_CASES["aime25"].source_pins.values()) == {AIME2025_DATASET_REVISION}


def test_hellaswag_pin_tracks_upstreams_own_revision_constant() -> None:
    """Same drift guard as aime24/25: the sha is COPIED from the eval's own
    pinned constant — a dependency bump that moves upstream's pin must fail
    here, never leave us preparing the old sha with the new scorer."""

    from inspect_evals.hellaswag.hellaswag import HELLASWAG_DATASET_REVISION as UPSTREAM

    # OME-1460: the Hub pin now lives on the Task-replay declaration.
    assert set(TASK_REPLAY_CASES["hellaswag"].source_pins.values()) == {UPSTREAM}


def test_onet_m6_filters_through_its_task_with_the_named_exclusion() -> None:
    """OME-1269's first question-filter benchmark. Its questions are whatever the eval's own
    filter keeps, minus the owner-approved named deviation (6 questions inspect keeps
    whose answer letter lies past their choices), and it renders inspect's own
    chain-of-thought template because the eval passes multiple_choice(cot=True).
    The question filter and the exclusion change which questions are served, so both ride its
    revision; the template pointer does not (template pointers predate revision-pin
    coverage — see benchmarks._revision_pins)."""

    from inspect_evals.onet.onet import ONET_DATASET_REVISION as UPSTREAM

    from screamingface_engine_inspect.benchmarks import _task_replay_pins

    # OME-1460: a Task-replay declaration now. The eval's own task filters (no filter
    # pointer to pin) and capture renders its own chain-of-thought template (no template
    # pointer); the exclusion still rides identity.
    row = TASK_REPLAY_CASES["onet_m6"]
    assert row.source_pins == {"matichon/thai-onet-m6-exam": UPSTREAM}
    assert row.task == "inspect_evals.onet.onet:onet_m6"
    assert row.excluded_sample_ids is not None and len(row.excluded_sample_ids) == 6
    assert row.case_count == 397 - 6
    assert any(pin.startswith("excluded_sample_ids=") for pin in _task_replay_pins(row))


def test_pubmedqa_prepares_the_evals_test_list_through_its_task() -> None:
    """pubmedqa loads all 1,000 labelled questions and keeps the 500 on its bundled
    test list; the benchmark runs the eval's task so its own filter keeps
    them, the count pins the KEPT 500, and the eval's template renders them."""

    from inspect_evals.pubmedqa.pubmedqa import PUBMEDQA_DATASET_REVISION as UPSTREAM

    from screamingface_engine_inspect.benchmarks import _task_replay_pins

    # OME-1460: a Task-replay declaration now; the eval's own task keeps the 500 and its own
    # template renders them, so the task reference rides identity in place of the filter.
    row = TASK_REPLAY_CASES["pubmedqa"]
    assert row.source_pins == {"qiaojin/PubMedQA": UPSTREAM}
    assert row.task == "inspect_evals.pubmedqa.pubmedqa:pubmedqa"
    assert row.case_count == 500
    assert row.excluded_sample_ids is None
    assert "task=inspect_evals.pubmedqa.pubmedqa:pubmedqa" in _task_replay_pins(row)


def test_xstest_safe_is_judged_from_the_evals_own_prompt_with_no_answer_key() -> None:
    """xstest_safe keeps the 250 safe prompts through the eval's own subset filter,
    has no answer key (the judge grades complied / refused from question and reply),
    needs a Hugging Face token (gated dataset), and its judge prompt is a verbatim
    copy of the eval's — a dependency bump that edits upstream's prompt fails here."""

    from inspect_evals.xstest.xstest import XSTEST_DATASET_REVISION as UPSTREAM
    from inspect_evals.xstest.xstest import scorer_instructions, scorer_template

    from screamingface_engine_inspect.benchmarks import BENCHMARKS, _task_replay_pins

    # OME-1460: a Task-replay declaration now; the subset is the eval's own task arg.
    row = TASK_REPLAY_CASES["xstest_safe"]
    assert row.source_pins == {"walledai/XSTest": UPSTREAM}
    assert row.task == "inspect_evals.xstest.xstest:xstest"
    assert row.task_args == {"subset": "safe"}
    assert row.case_count == 250
    assert row.has_answer_key is False
    assert row.needs_hf_token is True
    assert 'task_args={"subset": "safe"}' in _task_replay_pins(row)
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

from screamingface_engine_inspect.prepare import LICENSE_TODO  # noqa: E402


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
