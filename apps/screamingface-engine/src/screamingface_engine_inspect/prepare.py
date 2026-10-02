# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on, and with the extra installed
# these imports type-check normally.
"""Prepare the imported benchmarks' assets: public prompts and private Grading Material.

Run at IMAGE BUILD time, never at run time (OME-925): a Job's rootfs is read-only and
holds no HuggingFace credential, so every artifact exists before a run starts. HF
downloads happen here once; upstream gating or drift cannot change a published benchmark.

Emits, per benchmark::

    <out>/cases.json         [{"id", "case_id", "input"}] — ALL a client sees
    <out>/targets/<id>.json  {"target": ..., "choices": [...]?} — private; read by the
                             aggregate (the scorer adapter's grading material) and the
                             draft-feedback offer

ONE generic pipeline serves every imported single-shot benchmark; a benchmark is a
:class:`CasesSpec` DATA entry in :data:`BENCHMARK_CASES` — dataset pins plus two dotted
references into the eval's own code (its ``record_to_sample`` row rule, its prompt
template). Row conversion and prompt formatting are inspect's own functions, CALLED,
never reimplemented, so an imported benchmark's content is exactly what the eval publishes.
Importing eval #3 means adding one spec entry, zero new functions.

INVARIANT — the Sample coming back from the eval's ``record_to_sample`` crosses ONE
validated boundary (:func:`_validated_answer_key`): a malformed row fails the whole prepare
by case number, never prepares a half-keyed or unkeyed benchmark.

INVARIANT — ``cases.json`` carries NO Grading Material. The client receives ids and
prompts; the answer key stays in the image.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

from screamingface_engine.benchmarks.deployment import BenchmarkAssetPreparationError
from screamingface_engine_inspect.pins import (
    AIME24_CASE_COUNT,
    AIME24_CONFIG,
    AIME24_DATASET,
    AIME24_DATASET_REVISION,
    AIME24_SHUFFLE_SEED,
    AIME24_SPLIT,
    AIME25_CASE_COUNT,
    AIME25_CONFIG,
    AIME25_DATASET,
    AIME25_DATASET_REVISION,
    AIME25_SHUFFLE_SEED,
    AIME25_SPLIT,
    ARC_CHALLENGE_CASE_COUNT,
    ARC_CHALLENGE_CONFIG,
    ARC_CHALLENGE_DATASET,
    ARC_CHALLENGE_DATASET_REVISION,
    ARC_CHALLENGE_SPLIT,
    ARC_EASY_CASE_COUNT,
    ARC_EASY_CONFIG,
    ARC_EASY_DATASET,
    ARC_EASY_DATASET_REVISION,
    ARC_EASY_SPLIT,
    BOOLQ_CASE_COUNT,
    BOOLQ_CONFIG,
    BOOLQ_DATASET,
    BOOLQ_DATASET_REVISION,
    BOOLQ_SHUFFLE_SEED,
    BOOLQ_SPLIT,
    COMMONSENSE_QA_CASE_COUNT,
    COMMONSENSE_QA_CONFIG,
    COMMONSENSE_QA_DATASET,
    COMMONSENSE_QA_DATASET_REVISION,
    COMMONSENSE_QA_SHUFFLE_SEED,
    COMMONSENSE_QA_SPLIT,
    FRONTIERSCIENCE_CASE_COUNT,
    FRONTIERSCIENCE_CONFIG,
    FRONTIERSCIENCE_DATASET,
    FRONTIERSCIENCE_DATASET_REVISION,
    FRONTIERSCIENCE_SHUFFLE_SEED,
    FRONTIERSCIENCE_SPLIT,
    GSM8K_CASE_COUNT,
    GSM8K_DATA_DIR,
    GSM8K_DATASET,
    GSM8K_DATASET_REVISION,
    GSM8K_SPLIT,
    HELLASWAG_CASE_COUNT,
    HELLASWAG_CONFIG,
    HELLASWAG_DATASET,
    HELLASWAG_DATASET_REVISION,
    HELLASWAG_SHUFFLE_SEED,
    HELLASWAG_SPLIT,
    LAB_BENCH_CLONING_SCENARIOS_CASE_COUNT,
    LAB_BENCH_CLONING_SCENARIOS_CHOICE_SHUFFLE_SEED,
    LAB_BENCH_CLONING_SCENARIOS_CONFIG,
    LAB_BENCH_CLONING_SCENARIOS_DATASET,
    LAB_BENCH_CLONING_SCENARIOS_DATASET_REVISION,
    LAB_BENCH_CLONING_SCENARIOS_SHUFFLE_SEED,
    LAB_BENCH_CLONING_SCENARIOS_SPLIT,
    LAB_BENCH_DBQA_CASE_COUNT,
    LAB_BENCH_DBQA_CHOICE_SHUFFLE_SEED,
    LAB_BENCH_DBQA_CONFIG,
    LAB_BENCH_DBQA_DATASET,
    LAB_BENCH_DBQA_DATASET_REVISION,
    LAB_BENCH_DBQA_SHUFFLE_SEED,
    LAB_BENCH_DBQA_SPLIT,
    LAB_BENCH_LITQA_CASE_COUNT,
    LAB_BENCH_LITQA_CHOICE_SHUFFLE_SEED,
    LAB_BENCH_LITQA_CONFIG,
    LAB_BENCH_LITQA_DATASET,
    LAB_BENCH_LITQA_DATASET_REVISION,
    LAB_BENCH_LITQA_SHUFFLE_SEED,
    LAB_BENCH_LITQA_SPLIT,
    LAB_BENCH_PROTOCOLQA_CASE_COUNT,
    LAB_BENCH_PROTOCOLQA_CHOICE_SHUFFLE_SEED,
    LAB_BENCH_PROTOCOLQA_CONFIG,
    LAB_BENCH_PROTOCOLQA_DATASET,
    LAB_BENCH_PROTOCOLQA_DATASET_REVISION,
    LAB_BENCH_PROTOCOLQA_SHUFFLE_SEED,
    LAB_BENCH_PROTOCOLQA_SPLIT,
    LAB_BENCH_SEQQA_CASE_COUNT,
    LAB_BENCH_SEQQA_CHOICE_SHUFFLE_SEED,
    LAB_BENCH_SEQQA_CONFIG,
    LAB_BENCH_SEQQA_DATASET,
    LAB_BENCH_SEQQA_DATASET_REVISION,
    LAB_BENCH_SEQQA_SHUFFLE_SEED,
    LAB_BENCH_SEQQA_SPLIT,
    LAB_BENCH_SUPPQA_CASE_COUNT,
    LAB_BENCH_SUPPQA_CHOICE_SHUFFLE_SEED,
    LAB_BENCH_SUPPQA_CONFIG,
    LAB_BENCH_SUPPQA_DATASET,
    LAB_BENCH_SUPPQA_DATASET_REVISION,
    LAB_BENCH_SUPPQA_SHUFFLE_SEED,
    LAB_BENCH_SUPPQA_SPLIT,
    MMLU_CASE_COUNT,
    MMLU_CONFIG,
    MMLU_DATASET,
    MMLU_DATASET_REVISION,
    MMLU_PRO_CASE_COUNT,
    MMLU_PRO_CONFIG,
    MMLU_PRO_DATASET,
    MMLU_PRO_DATASET_REVISION,
    MMLU_PRO_SHUFFLE_SEED,
    MMLU_PRO_SPLIT,
    MMLU_SHUFFLE_SEED,
    MMLU_SPLIT,
    MUSR_CASE_COUNT,
    MUSR_CONFIG,
    MUSR_DATASET,
    MUSR_DATASET_REVISION,
    MUSR_SHUFFLE_SEED,
    MUSR_SPLIT,
    ONET_M6_CASE_COUNT,
    ONET_M6_CONFIG,
    ONET_M6_DATASET,
    ONET_M6_DATASET_REVISION,
    ONET_M6_EXCLUDED_SAMPLE_IDS,
    ONET_M6_SHUFFLE_SEED,
    ONET_M6_SPLIT,
    PAWS_CASE_COUNT,
    PAWS_CONFIG,
    PAWS_DATASET,
    PAWS_DATASET_REVISION,
    PAWS_SHUFFLE_SEED,
    PAWS_SPLIT,
    PUBMEDQA_CASE_COUNT,
    PUBMEDQA_CONFIG,
    PUBMEDQA_DATASET,
    PUBMEDQA_DATASET_REVISION,
    PUBMEDQA_SPLIT,
    RACE_H_CASE_COUNT,
    RACE_H_CONFIG,
    RACE_H_DATASET,
    RACE_H_DATASET_REVISION,
    RACE_H_SHUFFLE_SEED,
    RACE_H_SPLIT,
    WINOGRANDE_CASE_COUNT,
    WINOGRANDE_CONFIG,
    WINOGRANDE_DATASET,
    WINOGRANDE_DATASET_REVISION,
    WINOGRANDE_SPLIT,
    WMDP_BIO_CASE_COUNT,
    WMDP_BIO_CONFIG,
    WMDP_BIO_DATASET,
    WMDP_BIO_DATASET_REVISION,
    WMDP_BIO_SPLIT,
    WMDP_CHEM_CASE_COUNT,
    WMDP_CHEM_CONFIG,
    WMDP_CHEM_DATASET,
    WMDP_CHEM_DATASET_REVISION,
    WMDP_CHEM_SPLIT,
    WMDP_CYBER_CASE_COUNT,
    WMDP_CYBER_CONFIG,
    WMDP_CYBER_DATASET,
    WMDP_CYBER_DATASET_REVISION,
    WMDP_CYBER_SPLIT,
    XSTEST_SAFE_CASE_COUNT,
    XSTEST_SAFE_CONFIG,
    XSTEST_SAFE_DATASET,
    XSTEST_SAFE_DATASET_REVISION,
    XSTEST_SAFE_SPLIT,
    XSTEST_UNSAFE_CASE_COUNT,
    XSTEST_UNSAFE_CONFIG,
    XSTEST_UNSAFE_DATASET,
    XSTEST_UNSAFE_DATASET_REVISION,
    XSTEST_UNSAFE_SPLIT,
)

if TYPE_CHECKING:
    from inspect_ai.dataset import Sample


class PrepareError(BenchmarkAssetPreparationError):
    """The build refuses to prepare these assets. Always says which row and why."""


@dataclass(frozen=True)
class CasesSpec:
    """One imported benchmark's prepare, as pure data — pins plus pointers into the eval.

    ``record_to_sample`` and ``prompt_template`` are dotted ``"module:attr"``
    references into the eval's own package, resolved lazily at prepare time (the
    ``inspect`` extra is a build-environment dependency).
    """

    dataset: str
    config: str
    split: str
    dataset_revision: str
    case_count: int
    record_to_sample: str
    prompt_template: str | None = None
    #: The eval's own multiple_choice template, when it overrides inspect's default
    #: SINGLE_ANSWER render (mmlu_pro, winogrande, race_h) — same dotted-reference
    #: convention as ``prompt_template``, resolved lazily at prepare time.
    choice_template: str | None = None
    #: The eval's system instruction, delivered as the LEADING TEXT of the
    #: candidate input at prepare time — a benchmark cannot address a candidate's
    #: system role (the contracteval named-deviation pattern), so the
    #: instruction rides ahead of the render. Same dotted-reference convention
    #: as ``prompt_template``.
    system_message: str | None = None
    shuffle_seed: int | None = None
    #: Pins one per-case CHOICE order for an eval whose hf_dataset call shuffles
    #: choices (shuffle_choices) — applied via inspect's own
    #: ``MemoryDataset.shuffle_choices`` over THIS PREPARATION'S pinned row order. The
    #: pinned order is benchmark identity (it rides the benchmark's revision pins); it is
    #: NOT the order inspect would produce for the same seeds when a row shuffle
    #: is also active, because the prepare step's row shuffle is not HF's algorithm —
    #: the importer refuses that combination whenever upstream seeded either
    #: shuffle (review blocker on PR #1031). OME-1264.
    choice_shuffle_seed: int | None = None
    #: hf_dataset's data_files selection (a dict of str to str, infinite_bench's
    #: {"passkey": "passkey.jsonl"}), forwarded verbatim to
    #: ``datasets.load_dataset`` — it selects WHICH files load, so it rides the
    #: benchmark's revision pins. OME-1264 extension 2.
    data_files: dict[str, str] | None = None
    #: The eval's Features schema as a dotted POINTER at its own module constant
    #: (infinite_bench's ``constants:ft``) — same convention as
    #: ``record_to_sample``; resolved at prepare time and required to be a
    #: ``datasets.Features``. Rides the benchmark's revision pins too.
    features: str | None = None
    #: OME-1240 opt-in: prepare each Sample's metadata into its private Grading
    #: Material record — needed by metadata-dispatching scorers (frontierscience's
    #: format field).
    #: Default False keeps every published benchmark's prepared assets byte-identical
    #: (prepared cases are immutable at their revision); flipping it moves the revision.
    keep_sample_metadata: bool = False
    #: OME-1269 question filter: the eval's own task function (same dotted-reference
    #: convention), for an eval that DROPS questions after loading — a
    #: ``.filter()`` inside the task (pubmedqa keeps its 500 test ids of 1,000
    #: rows). The prepare step hands that function this benchmark's pinned Samples in place
    #: of its hf_dataset load and keeps exactly what its Task holds, so the
    #: eval's filter runs and is never copied. ``case_count`` is then the KEPT
    #: count. None (every benchmark before OME-1269) skips the step entirely.
    question_filter_task: str | None = None
    #: Arguments forwarded to ``task`` (xstest's {"subset": "safe"}) — they can
    #: change which questions the filter keeps, so they ride benchmark identity too.
    question_filter_task_args: dict[str, Any] | None = None
    #: A NAMED DEVIATION from inspect: sample ids (``str(Sample.id)``) the prepare step
    #: leaves out even though inspect keeps them — for questions that cannot be
    #: graded as published (onet_m6: an answer letter past the last choice).
    #: Every id must be present, or the prepare step refuses (upstream moved under the
    #: deviation); ``case_count`` is the count left after the exclusion. The row
    #: says why beside the ids, and the ids ride benchmark identity (OME-1269).
    excluded_sample_ids: tuple[str, ...] | None = None
    #: False for a judged benchmark whose judge grades from the question and the reply
    #: alone (xstest: complied / refused), so the dataset has no answer key to store.
    #: The prepare step then accepts an empty answer key; every other benchmark keeps
    #: refusing one, because there an empty key is a broken row. Assembly refuses the opt-in on a
    #: benchmark without a judge, or whose judge prompt reads the key (OME-1269, OME-1371).
    has_answer_key: bool = True
    #: The dataset sits behind a Hugging Face gate, so downloading it needs a token
    #: from an account that accepted its terms (xstest). Without one the prepare step stops by
    #: name, unless SCREAMINGFACE_SKIP_BENCHMARKS_NEEDING_HF_TOKEN=1 (PR builds, which get no
    #: secret) skips the benchmark with a warning. Access, not benchmark identity: no pin.
    needs_hf_token: bool = False


#: The build-time switch that lets a PR build skip gated benchmarks instead of failing.
SKIP_BENCHMARKS_NEEDING_HF_TOKEN_ENV = "SCREAMINGFACE_SKIP_BENCHMARKS_NEEDING_HF_TOKEN"

#: Written into a skipped gated bundle, so the runtime can say WHY the benchmark has no
#: questions instead of a bare "cases are unavailable" (review on PR #1112).
SKIPPED_MARKER = "SKIPPED"

#: One prepared Case as the writer writes it: the public ``case`` row of ``cases.json``
#: and its private ``grading_material`` record (``targets/<id>.json``).
type PreparedCase = dict[str, dict[str, Any]]


#: The license value the importer writes when it cannot read a cleared one; a test refuses
#: a Task-replay declaration that still carries it (spec R7). The owner decides each license.
LICENSE_TODO: str = "TODO"


@dataclass(frozen=True)
class TaskReplayCasesSpec:
    """One Task-replay Imported Benchmark's Case Preparation, as pure data (OME-1273).

    The Cases come from calling the eval's own task function (``task``, a ``"module:attr"``
    reference, called with ``task_args``); building its Task loads the dataset, and each
    Sample is rendered by capture (:mod:`screamingface_engine_inspect.capture`): the Task's
    own solvers run up to their first ``generate``, which records the prompt instead of
    calling a model. No evaluation runs: no ``eval()``, scorer, model or Judge. No dataset
    pin applies, so ``case_count`` and ``case_digest`` are CAPTURED at import and Case
    Preparation serves nothing unless both match. WHY no template fields: the eval's own
    solvers render the prompt, so nothing here could describe it better than they do.
    """

    task: str
    case_count: int
    case_digest: str
    task_args: dict[str, Any] | None = None
    keep_sample_metadata: bool = False
    has_answer_key: bool = True
    #: The dataset license, from the Hugging Face card when the one Case Source has one and
    #: it is on the cleared list, otherwise the owner's decision replacing LICENSE_TODO in
    #: the diff (spec R6, R7).
    license: str = LICENSE_TODO


def case_digest(prepared: Sequence[PreparedCase]) -> str:
    """Fingerprint the prepared Cases: the sha256 of exactly what the writer writes (OME-1273).

    Think of it as a seal on the envelope of Cases: any change to any Case's id, input or
    Grading Material, or to their order, breaks the seal. The Cases first go through a JSON
    round trip (what result.json does to them), then canonical JSON (sorted keys, no
    whitespace, UTF-8 without escapes) keeps the seal independent of dict order.

    Example: the two Cases in ``test_case_digest.py`` seal to ``765b3955…``; changing one
    target from "4" to "5" gives a different digest.

    Args:
        prepared: the prepared Cases in the order they are served.

    Returns:
        64 lowercase hex characters.
    """

    # INVARIANT: the digest means one thing wherever it is computed. WHY the round trip
    # first: JSON turns integer keys into strings, which sort differently (2 < 10, but
    # "10" < "2"), so the child's Cases and the parent's copy read back from result.json
    # would otherwise seal to different digests.
    as_json: list[Any] = json.loads(json.dumps(list(prepared), ensure_ascii=False))
    canonical: str = json.dumps(as_json, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


#: Every imported benchmark's prepare. Importing another eval = one more entry here
#: (plus its pins) — never a new function.
BENCHMARK_CASES: dict[str, CasesSpec] = {
    "gsm8k": CasesSpec(
        dataset=GSM8K_DATASET,
        config=GSM8K_DATA_DIR,
        split=GSM8K_SPLIT,
        dataset_revision=GSM8K_DATASET_REVISION,
        case_count=GSM8K_CASE_COUNT,
        # The eval's task: solver=[prompt_template(MATH_PROMPT_TEMPLATE), generate()],
        # dataset sample_fields=record_to_sample (target = the "####" tail).
        record_to_sample="inspect_evals.gsm8k.gsm8k:record_to_sample",
        prompt_template="inspect_evals.gsm8k.gsm8k:MATH_PROMPT_TEMPLATE",
    ),
    "mmlu": CasesSpec(
        dataset=MMLU_DATASET,
        config=MMLU_CONFIG,
        split=MMLU_SPLIT,
        dataset_revision=MMLU_DATASET_REVISION,
        case_count=MMLU_CASE_COUNT,
        # mmlu_0_shot's dataset: sample_fields=record_to_sample_mmlu (choices +
        # letter target); the prompt is the multiple_choice solver's default render.
        record_to_sample="inspect_evals.mmlu.mmlu:record_to_sample_mmlu",
        # WHY the shuffle: the HF split is subject-grouped, so a limit=N run over
        # raw order would examine one subject; the seed rides the revision hash.
        shuffle_seed=MMLU_SHUFFLE_SEED,
    ),
    "arc_easy": CasesSpec(
        dataset=ARC_EASY_DATASET,
        config=ARC_EASY_CONFIG,
        split=ARC_EASY_SPLIT,
        dataset_revision=ARC_EASY_DATASET_REVISION,
        case_count=ARC_EASY_CASE_COUNT,
        # arc_easy's dataset: sample_fields=record_to_sample (letters or numbered
        # answerKeys normalized to letters); prompt = the default MCQ render.
        # Verified by a full offline prepare, 2026-09-17.
        record_to_sample="inspect_evals.arc.arc:record_to_sample",
    ),
    "arc_challenge": CasesSpec(
        dataset=ARC_CHALLENGE_DATASET,
        config=ARC_CHALLENGE_CONFIG,
        split=ARC_CHALLENGE_SPLIT,
        dataset_revision=ARC_CHALLENGE_DATASET_REVISION,
        case_count=ARC_CHALLENGE_CASE_COUNT,
        # Same eval module as arc_easy — only the HF config differs.
        # Verified by a full offline prepare, 2026-09-17.
        record_to_sample="inspect_evals.arc.arc:record_to_sample",
    ),
    "commonsense_qa": CasesSpec(
        dataset=COMMONSENSE_QA_DATASET,
        config=COMMONSENSE_QA_CONFIG,
        split=COMMONSENSE_QA_SPLIT,
        dataset_revision=COMMONSENSE_QA_DATASET_REVISION,
        case_count=COMMONSENSE_QA_CASE_COUNT,
        # commonsense_qa's dataset: sample_fields=record_to_sample (5 choices,
        # letter target); prompt = the default MCQ render. Verified by a full
        # offline prepare, 2026-09-17.
        record_to_sample="inspect_evals.commonsense_qa.commonsense_qa:record_to_sample",
        # WHY the seed: the upstream eval shuffles this benchmark's order per run
        # (hf_dataset shuffle=True, no seed) — the import pins one order as
        # benchmark identity (review round 2026-09-17).
        shuffle_seed=COMMONSENSE_QA_SHUFFLE_SEED,
    ),
    "paws": CasesSpec(
        dataset=PAWS_DATASET,
        config=PAWS_CONFIG,
        split=PAWS_SPLIT,
        dataset_revision=PAWS_DATASET_REVISION,
        case_count=PAWS_CASE_COUNT,
        # paws' task: solver=[prompt_template(TEMPLATE), generate()]; target is
        # Yes/No from the label. Verified by a full offline prepare, 2026-09-17.
        record_to_sample="inspect_evals.paws.paws:record_to_sample",
        prompt_template="inspect_evals.paws.paws:TEMPLATE",
        # WHY the seed: the upstream eval shuffles this benchmark's order per run
        # (hf_dataset shuffle=True, no seed) — the import pins one order as
        # benchmark identity (review round 2026-09-17).
        shuffle_seed=PAWS_SHUFFLE_SEED,
    ),
    "boolq": CasesSpec(
        dataset=BOOLQ_DATASET,
        config=BOOLQ_CONFIG,
        split=BOOLQ_SPLIT,
        dataset_revision=BOOLQ_DATASET_REVISION,
        case_count=BOOLQ_CASE_COUNT,
        # boolq's dataset: sample_fields=record_to_sample (passage folded into
        # the question, Yes/No target); raw-input render (no template).
        # Verified by a full offline prepare, 2026-09-17.
        record_to_sample="inspect_evals.boolq.boolq:record_to_sample",
        # WHY the seed: the upstream eval shuffles this benchmark's order per run
        # (hf_dataset shuffle=True, no seed) — the import pins one order as
        # benchmark identity (review round 2026-09-17).
        shuffle_seed=BOOLQ_SHUFFLE_SEED,
    ),
    "mmlu_pro": CasesSpec(
        dataset=MMLU_PRO_DATASET,
        config=MMLU_PRO_CONFIG,
        split=MMLU_PRO_SPLIT,
        dataset_revision=MMLU_PRO_DATASET_REVISION,
        case_count=MMLU_PRO_CASE_COUNT,
        # mmlu_pro's dataset: sample_fields=record_to_sample (10 options); the
        # prompt renders through the eval's own CoT template below. Verified by
        # a full offline prepare, 2026-09-17.
        record_to_sample="inspect_evals.mmlu_pro.mmlu_pro:record_to_sample",
        choice_template="inspect_evals.mmlu_pro.mmlu_pro:USER_PROMPT_TEMPLATE",
        # WHY the shuffle: the HF split is category-grouped (first 100 rows are
        # one discipline), so a limit=N run over raw order would examine one
        # discipline; the seed rides the revision hash.
        shuffle_seed=MMLU_PRO_SHUFFLE_SEED,
    ),
    "winogrande": CasesSpec(
        dataset=WINOGRANDE_DATASET,
        config=WINOGRANDE_CONFIG,
        split=WINOGRANDE_SPLIT,
        dataset_revision=WINOGRANDE_DATASET_REVISION,
        case_count=WINOGRANDE_CASE_COUNT,
        # winogrande's dataset (fewshot=0): sample_fields=record_to_sample
        # ([BLANK] sentence, two options); renders through the eval's own
        # template below. Verified by a full offline prepare, 2026-09-17.
        record_to_sample="inspect_evals.winogrande.winogrande:record_to_sample",
        choice_template="inspect_evals.winogrande.winogrande:USER_PROMPT_TEMPLATE",
    ),
    "race_h": CasesSpec(
        dataset=RACE_H_DATASET,
        config=RACE_H_CONFIG,
        split=RACE_H_SPLIT,
        dataset_revision=RACE_H_DATASET_REVISION,
        case_count=RACE_H_CASE_COUNT,
        # race_h's dataset: sample_fields=record_to_sample (passage + question
        # folded into input); renders through the eval's own template below.
        # Verified by a full offline prepare, 2026-09-17.
        record_to_sample="inspect_evals.race_h.race_h:record_to_sample",
        choice_template="inspect_evals.race_h.race_h:TEMPLATE",
        # WHY the shuffle: questions arrive in per-passage runs, so a small
        # limit=N run would see few passages; the seed rides the revision hash.
        shuffle_seed=RACE_H_SHUFFLE_SEED,
    ),
    "aime24": CasesSpec(
        dataset=AIME24_DATASET,
        config=AIME24_CONFIG,
        split=AIME24_SPLIT,
        dataset_revision=AIME24_DATASET_REVISION,
        case_count=AIME24_CASE_COUNT,
        # Generated from
        #   inspect_evals.aime2024.aime2024:aime2024;
        # verify against the eval's task.
        record_to_sample="inspect_evals.aime2024.aime2024:record_to_sample",
        prompt_template="inspect_evals.utils.aime_common:USER_PROMPT_TEMPLATE",
        shuffle_seed=AIME24_SHUFFLE_SEED,
    ),
    "aime25": CasesSpec(
        dataset=AIME25_DATASET,
        config=AIME25_CONFIG,
        split=AIME25_SPLIT,
        dataset_revision=AIME25_DATASET_REVISION,
        case_count=AIME25_CASE_COUNT,
        # Generated from
        #   inspect_evals.aime2025.aime2025:aime2025;
        # verify against the eval's task.
        record_to_sample="inspect_evals.aime2025.aime2025:record_to_sample",
        prompt_template="inspect_evals.utils.aime_common:USER_PROMPT_TEMPLATE",
        shuffle_seed=AIME25_SHUFFLE_SEED,
    ),
    "musr": CasesSpec(
        dataset=MUSR_DATASET,
        config=MUSR_CONFIG,
        split=MUSR_SPLIT,
        dataset_revision=MUSR_DATASET_REVISION,
        case_count=MUSR_CASE_COUNT,
        # Generated from
        #   inspect_evals.musr.musr:musr;
        # verify against the eval's task.
        record_to_sample="inspect_evals.musr.musr:record_to_sample",
        choice_template="inspect_evals.musr.musr:REGULAR_PROMPT",
        shuffle_seed=MUSR_SHUFFLE_SEED,
        # WHY the unbaked system_message is benign (review flag resolved): the
        # eval's SYSTEM_PROMPT is the generic "You are a helpful assistant that
        # will answer the questions given by the user." — boilerplate with no
        # benchmark content. Every format instruction rides REGULAR_PROMPT, which IS
        # the prepared choice_template, so the prepared prompt matches the eval's
        # rendered user turn.
    ),
    "wmdp_bio": CasesSpec(
        dataset=WMDP_BIO_DATASET,
        config=WMDP_BIO_CONFIG,
        split=WMDP_BIO_SPLIT,
        dataset_revision=WMDP_BIO_DATASET_REVISION,
        case_count=WMDP_BIO_CASE_COUNT,
        # Generated from
        #   inspect_evals.wmdp.wmdp:wmdp_bio;
        # verify against the eval's task.
        # WHY the eval's post-load filter_duplicate_ids is benign: a no-op at
        # this pinned revision (verified 1273/1273 unique stable ids), so the
        # prepare's unfiltered rows are the same benchmark.
        record_to_sample="inspect_evals.wmdp.wmdp:record_to_sample",
    ),
    "wmdp_chem": CasesSpec(
        dataset=WMDP_CHEM_DATASET,
        config=WMDP_CHEM_CONFIG,
        split=WMDP_CHEM_SPLIT,
        dataset_revision=WMDP_CHEM_DATASET_REVISION,
        case_count=WMDP_CHEM_CASE_COUNT,
        # Generated from
        #   inspect_evals.wmdp.wmdp:wmdp_chem;
        # verify against the eval's task.
        # WHY the eval's post-load filter_duplicate_ids is benign: a no-op at
        # this pinned revision (verified 408/408 unique stable ids), so the
        # prepare's unfiltered rows are the same benchmark.
        record_to_sample="inspect_evals.wmdp.wmdp:record_to_sample",
    ),
    "wmdp_cyber": CasesSpec(
        dataset=WMDP_CYBER_DATASET,
        config=WMDP_CYBER_CONFIG,
        split=WMDP_CYBER_SPLIT,
        dataset_revision=WMDP_CYBER_DATASET_REVISION,
        case_count=WMDP_CYBER_CASE_COUNT,
        # Generated from
        #   inspect_evals.wmdp.wmdp:wmdp_cyber;
        # verify against the eval's task.
        # WHY the eval's post-load filter_duplicate_ids is benign: a no-op at
        # this pinned revision (verified 1987/1987 unique stable ids), so the
        # prepare's unfiltered rows are the same benchmark.
        record_to_sample="inspect_evals.wmdp.wmdp:record_to_sample",
    ),
    "hellaswag": CasesSpec(
        dataset=HELLASWAG_DATASET,
        config=HELLASWAG_CONFIG,
        split=HELLASWAG_SPLIT,
        dataset_revision=HELLASWAG_DATASET_REVISION,
        case_count=HELLASWAG_CASE_COUNT,
        # Generated from
        #   inspect_evals.hellaswag.hellaswag:hellaswag;
        # verify against the eval's task.
        record_to_sample="inspect_evals.hellaswag.hellaswag:record_to_sample",
        # Named deviation: the eval sends this as a SYSTEM message; the
        # prepare delivers it as leading input text (a benchmark cannot
        # address a candidate's system role).
        system_message="inspect_evals.hellaswag.hellaswag:SYSTEM_MESSAGE",
        # WHY the seed: the split is domain-grouped (ActivityNet then
        # WikiHow) — see the pin's comment; OURS by policy.
        shuffle_seed=HELLASWAG_SHUFFLE_SEED,
    ),
    "lab_bench_litqa": CasesSpec(
        dataset=LAB_BENCH_LITQA_DATASET,
        config=LAB_BENCH_LITQA_CONFIG,
        split=LAB_BENCH_LITQA_SPLIT,
        dataset_revision=LAB_BENCH_LITQA_DATASET_REVISION,
        case_count=LAB_BENCH_LITQA_CASE_COUNT,
        # Generated from
        #   inspect_evals.lab_bench.lab_bench:lab_bench_litqa;
        # verify against the eval's task.
        record_to_sample="inspect_evals.lab_bench.record_to_sample_helpers:record_to_sample_base",
        choice_template="inspect_evals.lab_bench.lab_bench:MULTIPLE_CHOICE_TEMPLATE",
        shuffle_seed=LAB_BENCH_LITQA_SHUFFLE_SEED,
        choice_shuffle_seed=LAB_BENCH_LITQA_CHOICE_SHUFFLE_SEED,
    ),
    "lab_bench_suppqa": CasesSpec(
        dataset=LAB_BENCH_SUPPQA_DATASET,
        config=LAB_BENCH_SUPPQA_CONFIG,
        split=LAB_BENCH_SUPPQA_SPLIT,
        dataset_revision=LAB_BENCH_SUPPQA_DATASET_REVISION,
        case_count=LAB_BENCH_SUPPQA_CASE_COUNT,
        # Generated from
        #   inspect_evals.lab_bench.lab_bench:lab_bench_suppqa;
        # verify against the eval's task.
        record_to_sample="inspect_evals.lab_bench.record_to_sample_helpers:record_to_sample_suppqa",
        choice_template="inspect_evals.lab_bench.lab_bench:MULTIPLE_CHOICE_TEMPLATE",
        shuffle_seed=LAB_BENCH_SUPPQA_SHUFFLE_SEED,
        choice_shuffle_seed=LAB_BENCH_SUPPQA_CHOICE_SHUFFLE_SEED,
    ),
    "lab_bench_dbqa": CasesSpec(
        dataset=LAB_BENCH_DBQA_DATASET,
        config=LAB_BENCH_DBQA_CONFIG,
        split=LAB_BENCH_DBQA_SPLIT,
        dataset_revision=LAB_BENCH_DBQA_DATASET_REVISION,
        case_count=LAB_BENCH_DBQA_CASE_COUNT,
        # Generated from
        #   inspect_evals.lab_bench.lab_bench:lab_bench_dbqa;
        # verify against the eval's task.
        record_to_sample="inspect_evals.lab_bench.record_to_sample_helpers:record_to_sample_base",
        choice_template="inspect_evals.lab_bench.lab_bench:MULTIPLE_CHOICE_TEMPLATE",
        shuffle_seed=LAB_BENCH_DBQA_SHUFFLE_SEED,
        choice_shuffle_seed=LAB_BENCH_DBQA_CHOICE_SHUFFLE_SEED,
    ),
    "lab_bench_protocolqa": CasesSpec(
        dataset=LAB_BENCH_PROTOCOLQA_DATASET,
        config=LAB_BENCH_PROTOCOLQA_CONFIG,
        split=LAB_BENCH_PROTOCOLQA_SPLIT,
        dataset_revision=LAB_BENCH_PROTOCOLQA_DATASET_REVISION,
        case_count=LAB_BENCH_PROTOCOLQA_CASE_COUNT,
        # Generated from
        #   inspect_evals.lab_bench.lab_bench:lab_bench_protocolqa;
        # verify against the eval's task.
        record_to_sample="inspect_evals.lab_bench.record_to_sample_helpers:record_to_sample_protocolqa",
        choice_template="inspect_evals.lab_bench.lab_bench:MULTIPLE_CHOICE_TEMPLATE",
        shuffle_seed=LAB_BENCH_PROTOCOLQA_SHUFFLE_SEED,
        choice_shuffle_seed=LAB_BENCH_PROTOCOLQA_CHOICE_SHUFFLE_SEED,
    ),
    "lab_bench_seqqa": CasesSpec(
        dataset=LAB_BENCH_SEQQA_DATASET,
        config=LAB_BENCH_SEQQA_CONFIG,
        split=LAB_BENCH_SEQQA_SPLIT,
        dataset_revision=LAB_BENCH_SEQQA_DATASET_REVISION,
        case_count=LAB_BENCH_SEQQA_CASE_COUNT,
        # Generated from
        #   inspect_evals.lab_bench.lab_bench:lab_bench_seqqa;
        # verify against the eval's task.
        record_to_sample="inspect_evals.lab_bench.record_to_sample_helpers:record_to_sample_base",
        choice_template="inspect_evals.lab_bench.lab_bench:MULTIPLE_CHOICE_TEMPLATE",
        shuffle_seed=LAB_BENCH_SEQQA_SHUFFLE_SEED,
        choice_shuffle_seed=LAB_BENCH_SEQQA_CHOICE_SHUFFLE_SEED,
    ),
    "lab_bench_cloning_scenarios": CasesSpec(
        dataset=LAB_BENCH_CLONING_SCENARIOS_DATASET,
        config=LAB_BENCH_CLONING_SCENARIOS_CONFIG,
        split=LAB_BENCH_CLONING_SCENARIOS_SPLIT,
        dataset_revision=LAB_BENCH_CLONING_SCENARIOS_DATASET_REVISION,
        case_count=LAB_BENCH_CLONING_SCENARIOS_CASE_COUNT,
        # Generated from
        #   inspect_evals.lab_bench.lab_bench:lab_bench_cloning_scenarios;
        # verify against the eval's task.
        record_to_sample="inspect_evals.lab_bench.record_to_sample_helpers:record_to_sample_base",
        choice_template="inspect_evals.lab_bench.lab_bench:MULTIPLE_CHOICE_TEMPLATE",
        shuffle_seed=LAB_BENCH_CLONING_SCENARIOS_SHUFFLE_SEED,
        choice_shuffle_seed=LAB_BENCH_CLONING_SCENARIOS_CHOICE_SHUFFLE_SEED,
    ),
    "frontierscience": CasesSpec(
        dataset=FRONTIERSCIENCE_DATASET,
        config=FRONTIERSCIENCE_CONFIG,
        split=FRONTIERSCIENCE_SPLIT,
        dataset_revision=FRONTIERSCIENCE_DATASET_REVISION,
        case_count=FRONTIERSCIENCE_CASE_COUNT,
        # Generated from
        #   inspect_evals.frontierscience.frontierscience:frontierscience;
        # verify against the eval's task.
        record_to_sample="inspect_evals.frontierscience.frontierscience:record_to_sample",
        # The scorer dispatches each case to its format's judge prompt via the
        # Sample's metadata (format/subject) — prepare it into the private Grading
        # Material record.
        keep_sample_metadata=True,
        shuffle_seed=FRONTIERSCIENCE_SHUFFLE_SEED,
    ),
    "onet_m6": CasesSpec(
        dataset=ONET_M6_DATASET,
        config=ONET_M6_CONFIG,
        split=ONET_M6_SPLIT,
        dataset_revision=ONET_M6_DATASET_REVISION,
        case_count=ONET_M6_CASE_COUNT,
        # Generated from
        #   inspect_evals.onet.onet:onet_m6;
        # verify against the eval's task.
        record_to_sample="inspect_evals.onet.onet:record_to_sample",
        choice_template="inspect_ai.solver._multiple_choice:SINGLE_ANSWER_TEMPLATE_COT",
        # Named deviation: the eval sends this as a SYSTEM message; the
        # prepare delivers it as leading input text (a benchmark cannot
        # address a candidate's system role).
        system_message="inspect_evals.onet.onet:SYSTEM_MESSAGE",
        shuffle_seed=ONET_M6_SHUFFLE_SEED,
        # The eval drops questions after loading; the prepare step runs its task over
        # the pinned Samples and keeps exactly what it keeps (OME-1269).
        question_filter_task="inspect_evals.onet.onet:onet_m6",
        # Named deviation: six malformed questions inspect keeps (see the pin).
        excluded_sample_ids=ONET_M6_EXCLUDED_SAMPLE_IDS,
    ),
    "pubmedqa": CasesSpec(
        dataset=PUBMEDQA_DATASET,
        config=PUBMEDQA_CONFIG,
        split=PUBMEDQA_SPLIT,
        dataset_revision=PUBMEDQA_DATASET_REVISION,
        case_count=PUBMEDQA_CASE_COUNT,
        # Generated from
        #   inspect_evals.pubmedqa.pubmedqa:pubmedqa;
        # verify against the eval's task.
        record_to_sample="inspect_evals.pubmedqa.pubmedqa:record_to_sample",
        choice_template="inspect_evals.pubmedqa.pubmedqa:TEMPLATE",
        # The eval drops questions after loading; the prepare step runs its task over
        # the pinned Samples and keeps exactly what it keeps (OME-1269).
        question_filter_task="inspect_evals.pubmedqa.pubmedqa:pubmedqa",
    ),
    "xstest_safe": CasesSpec(
        dataset=XSTEST_SAFE_DATASET,
        config=XSTEST_SAFE_CONFIG,
        split=XSTEST_SAFE_SPLIT,
        dataset_revision=XSTEST_SAFE_DATASET_REVISION,
        case_count=XSTEST_SAFE_CASE_COUNT,
        # Generated from
        #   inspect_evals.xstest.xstest:xstest;
        # verify against the eval's task.
        record_to_sample="inspect_evals.xstest.xstest:record_to_sample",
        # The eval drops questions after loading; the prepare step runs its task over
        # the pinned Samples and keeps exactly what it keeps (OME-1269).
        question_filter_task="inspect_evals.xstest.xstest:xstest",
        question_filter_task_args={"subset": "safe"},
        # Gated on the Hub: the prepare step needs HF_TOKEN from an account that
        # accepted the dataset's terms (OME-1269).
        needs_hf_token=True,
        # The judge grades complied / refused from the question and the reply;
        # the dataset has no answer key (xstest's row rule sets no target).
        has_answer_key=False,
        # WHY the unbaked system_message is benign (musr precedent): the eval's
        # system message is the generic "You are a helpful assistant." — no benchmark
        # content, and the grading prompt never sees it.
    ),
    "xstest_unsafe": CasesSpec(
        dataset=XSTEST_UNSAFE_DATASET,
        config=XSTEST_UNSAFE_CONFIG,
        split=XSTEST_UNSAFE_SPLIT,
        dataset_revision=XSTEST_UNSAFE_DATASET_REVISION,
        case_count=XSTEST_UNSAFE_CASE_COUNT,
        # Generated from
        #   inspect_evals.xstest.xstest:xstest;
        # verify against the eval's task.
        record_to_sample="inspect_evals.xstest.xstest:record_to_sample",
        # The eval drops questions after loading; the prepare step runs its task over
        # the pinned questions and keeps exactly what it keeps (OME-1269).
        question_filter_task="inspect_evals.xstest.xstest:xstest",
        question_filter_task_args={"subset": "unsafe"},
        # Gated on the Hub: the prepare step needs HF_TOKEN from an account that
        # accepted the dataset's terms (OME-1269).
        needs_hf_token=True,
        # The judge grades complied / refused from the question and the reply;
        # the dataset has no answer key (xstest's row rule sets no target).
        has_answer_key=False,
        # WHY the unbaked system_message is benign (musr precedent): the eval's
        # system message is the generic "You are a helpful assistant." — no benchmark
        # content, and the grading prompt never sees it.
    ),
    # --- importer: generated CasesSpec rows land above this line ---
}


#: Every Task-replay Imported Benchmark's Case Preparation, keyed like BENCHMARK_CASES.
#: Empty until OME-1273's import PRs add agieval, medqa and mgsm.
TASK_REPLAY_CASES: dict[str, TaskReplayCasesSpec] = {
    # agieval_lsat_ar — imported by Task replay on 2026-10-02 from
    #   inspect_evals.agieval.agieval:agie_lsat_ar.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://raw.githubusercontent.com/ruixiangcui/AGIEval/84ab72d94318290aad2e4ec820d535a95a1f7552/data/v1_1/lsat-ar.jsonl
    #     pin commit 84ab72d94318290aad2e4ec820d535a95a1f7552
    "agieval_lsat_ar": TaskReplayCasesSpec(
        task="inspect_evals.agieval.agieval:agie_lsat_ar",
        case_count=230,
        case_digest="5f77e982829b4ce7a4fbb72abfd54d6cdf84e27fd73c470a7950e59abf599233",
        # License: owner decision 2026-10-01: MIT, ruixiangcui/AGIEval LICENSE; no dataset card.
        license="mit",
    ),
    # agieval_lsat_lr — imported by Task replay on 2026-10-02 from
    #   inspect_evals.agieval.agieval:agie_lsat_lr.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://raw.githubusercontent.com/ruixiangcui/AGIEval/84ab72d94318290aad2e4ec820d535a95a1f7552/data/v1_1/lsat-lr.jsonl
    #     pin commit 84ab72d94318290aad2e4ec820d535a95a1f7552
    "agieval_lsat_lr": TaskReplayCasesSpec(
        task="inspect_evals.agieval.agieval:agie_lsat_lr",
        case_count=510,
        case_digest="104db4473e5e86e7addb6f683f7c50cb279094ad2091ff270da1618d7cd6a42d",
        # License: owner decision 2026-10-01: MIT, ruixiangcui/AGIEval LICENSE; no dataset card.
        license="mit",
    ),
    # agieval_lsat_rc — imported by Task replay on 2026-10-02 from
    #   inspect_evals.agieval.agieval:agie_lsat_rc.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://raw.githubusercontent.com/ruixiangcui/AGIEval/84ab72d94318290aad2e4ec820d535a95a1f7552/data/v1_1/lsat-rc.jsonl
    #     pin commit 84ab72d94318290aad2e4ec820d535a95a1f7552
    "agieval_lsat_rc": TaskReplayCasesSpec(
        task="inspect_evals.agieval.agieval:agie_lsat_rc",
        case_count=269,
        case_digest="984f6070d532200fd9e92d1e0b91ce42c7dec1f6b72ab5316ec1cfe9ab2e8ddb",
        # License: owner decision 2026-10-01: MIT, ruixiangcui/AGIEval LICENSE; no dataset card.
        license="mit",
    ),
    # agieval_sat_math — imported by Task replay on 2026-10-02 from
    #   inspect_evals.agieval.agieval:agie_sat_math.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://raw.githubusercontent.com/ruixiangcui/AGIEval/84ab72d94318290aad2e4ec820d535a95a1f7552/data/v1_1/sat-math.jsonl
    #     pin commit 84ab72d94318290aad2e4ec820d535a95a1f7552
    "agieval_sat_math": TaskReplayCasesSpec(
        task="inspect_evals.agieval.agieval:agie_sat_math",
        case_count=220,
        case_digest="54ac8e2293cf2ac8e62d62383bfe8a9f8fa5dfdb4249f6eb603c5b4aef88b84d",
        # License: owner decision 2026-10-01: MIT, ruixiangcui/AGIEval LICENSE; no dataset card.
        license="mit",
    ),
    # agieval_sat_en — imported by Task replay on 2026-10-02 from
    #   inspect_evals.agieval.agieval:agie_sat_en.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://raw.githubusercontent.com/ruixiangcui/AGIEval/84ab72d94318290aad2e4ec820d535a95a1f7552/data/v1_1/sat-en.jsonl
    #     pin commit 84ab72d94318290aad2e4ec820d535a95a1f7552
    "agieval_sat_en": TaskReplayCasesSpec(
        task="inspect_evals.agieval.agieval:agie_sat_en",
        case_count=206,
        case_digest="02045f612ebb038734920b2007dbd49d200b801ec36c8b811d3c84ca773444ce",
        # License: owner decision 2026-10-01: MIT, ruixiangcui/AGIEval LICENSE; no dataset card.
        license="mit",
    ),
    # agieval_sat_en_without_passage — imported by Task replay on 2026-10-02 from
    #   inspect_evals.agieval.agieval:agie_sat_en_without_passage.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://raw.githubusercontent.com/ruixiangcui/AGIEval/84ab72d94318290aad2e4ec820d535a95a1f7552/data/v1_1/sat-en-without-passage.jsonl
    #     pin commit 84ab72d94318290aad2e4ec820d535a95a1f7552
    "agieval_sat_en_without_passage": TaskReplayCasesSpec(
        task="inspect_evals.agieval.agieval:agie_sat_en_without_passage",
        case_count=206,
        case_digest="fe8910e4238399ac39b277bc3beaaee5d89328f91e0dd375b94bf7ee091e218d",
        # License: owner decision 2026-10-01: MIT, ruixiangcui/AGIEval LICENSE; no dataset card.
        license="mit",
    ),
    # agieval_aqua_rat — imported by Task replay on 2026-10-02 from
    #   inspect_evals.agieval.agieval:agie_aqua_rat.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://raw.githubusercontent.com/ruixiangcui/AGIEval/84ab72d94318290aad2e4ec820d535a95a1f7552/data/v1_1/aqua-rat.jsonl
    #     pin commit 84ab72d94318290aad2e4ec820d535a95a1f7552
    "agieval_aqua_rat": TaskReplayCasesSpec(
        task="inspect_evals.agieval.agieval:agie_aqua_rat",
        case_count=254,
        case_digest="64dce3527cc1ef47977165c9f042992180d301352ec9d33e78cb1be18a612b6b",
        # License: owner decision 2026-10-01: MIT, ruixiangcui/AGIEval LICENSE; no dataset card.
        license="mit",
    ),
    # agieval_logiqa_en — imported by Task replay on 2026-10-02 from
    #   inspect_evals.agieval.agieval:agie_logiqa_en.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://raw.githubusercontent.com/ruixiangcui/AGIEval/84ab72d94318290aad2e4ec820d535a95a1f7552/data/v1_1/logiqa-en.jsonl
    #     pin commit 84ab72d94318290aad2e4ec820d535a95a1f7552
    "agieval_logiqa_en": TaskReplayCasesSpec(
        task="inspect_evals.agieval.agieval:agie_logiqa_en",
        case_count=651,
        case_digest="7c80ae3ee57808416fbfb3a5e7d78e8c99f4c5afbc46367bad967c1b9f90d781",
        # License: owner decision 2026-10-01: MIT, ruixiangcui/AGIEval LICENSE; no dataset card.
        license="mit",
    ),
    # medqa — imported by Task replay on 2026-10-02 from
    #   inspect_evals.medqa.medqa:medqa.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face bigbio/med_qa
    #     pin revision ddef95d268cdad413693d634279a9a679d468469
    "medqa": TaskReplayCasesSpec(
        task="inspect_evals.medqa.medqa:medqa",
        case_count=1273,
        case_digest="ea4634b0825292d91881c0e76dd571a023ad9e8fd037116b5ce908100b2b7944",
        # License: owner decision 2026-10-01: MIT, jind11/MedQA LICENSE; the bigbio card says
        #  unknown.
        license="mit",
    ),
    # mgsm_en — imported by Task replay on 2026-10-02 from
    #   inspect_evals.mgsm.mgsm:mgsm.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://openaipublic.blob.core.windows.net/simple-evals/mgsm_en.tsv
    #     pin sha256 50021d0f28cc957edcb44e7806425b1c7fbd648ddcb9e0a8ec689d10e57d40fa
    "mgsm_en": TaskReplayCasesSpec(
        task="inspect_evals.mgsm.mgsm:mgsm",
        task_args={"languages": ["en"]},
        case_count=250,
        case_digest="3f34b5110fc11408e435c1b6113c7f698e3c3b5d14ce604592644d4059e9320e",
        # License: owner decision 2026-10-01: CC-BY-4.0, google-research/url-nlp mgsm/LICENSE.
        license="cc-by-4.0",
    ),
    # bbq — imported by Task replay on 2026-10-02 from
    #   inspect_evals.bbq.bbq:bbq.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face heegyu/bbq
    #     pin revision 5d6faae52070aa5eb71b46d1c0723d3ba7930209
    "bbq": TaskReplayCasesSpec(
        task="inspect_evals.bbq.bbq:bbq",
        case_count=58492,
        case_digest="8d7652ea42145db0b27d6ddbedfd81bc5fd4733bb4e78658218b15c0c8a5d28b",
        license="cc-by-4.0",
    ),
    # piqa — imported by Task replay on 2026-10-02 from
    #   inspect_evals.piqa.piqa:piqa.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face ybisk/piqa
    #     pin revision 2e8ac2dffd59bac8c3c6714948f4c551a0848bb0
    #   url https://storage.googleapis.com/ai2-mosaic/public/physicaliqa/physicaliqa-train-dev.zip
    #     pin unpinned (no upstream hash: the Case Digest is the only pin)
    #   url https://yonatanbisk.com/piqa/data/tests.jsonl
    #     pin unpinned (no upstream hash: the Case Digest is the only pin)
    "piqa": TaskReplayCasesSpec(
        task="inspect_evals.piqa.piqa:piqa",
        case_count=1838,
        case_digest="bc3ae6040b20a2eabe8976f96d58ac8ffae08bc821c73021c2d5b4289eca8958",
        # License: owner decision 2026-10-01: no license found; the ybisk/piqa card says unknown and
        #  the original repo is gone.
        license="unknown",
    ),
    # cybermetric_80 — imported by Task replay on 2026-10-02 from
    #   inspect_evals.cybermetric.cybermetric:cybermetric_80.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://raw.githubusercontent.com/cybermetric/CyberMetric/205262cdf5022ba890e792efd176fb19d42913fa/CyberMetric-80-v1.json
    #     pin sha256 1624aeecc54761198bff4828442ce4a10de6cb87c9da3298088b34ae11e15ba0
    "cybermetric_80": TaskReplayCasesSpec(
        task="inspect_evals.cybermetric.cybermetric:cybermetric_80",
        case_count=80,
        case_digest="25fa5f98d03ae8aef3e381589b0fc2e6d0130d900c6d14e67766ec9816f73e56",
        # License: owner decision 2026-10-01: cybermetric/CyberMetric carries no license file.
        license="unknown",
    ),
    # cybermetric_500 — imported by Task replay on 2026-10-02 from
    #   inspect_evals.cybermetric.cybermetric:cybermetric_500.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://raw.githubusercontent.com/cybermetric/CyberMetric/205262cdf5022ba890e792efd176fb19d42913fa/CyberMetric-500-v1.json
    #     pin sha256 036747c989da9f38f39a6b33fa2d5ab14147c928df0274217bbecab20be88faa
    "cybermetric_500": TaskReplayCasesSpec(
        task="inspect_evals.cybermetric.cybermetric:cybermetric_500",
        case_count=500,
        case_digest="df8bfe73bc077e26d148a85200c4598dcd93e837cc1aec0459c6f27702b81fa8",
        # License: owner decision 2026-10-01: cybermetric/CyberMetric carries no license file.
        license="unknown",
    ),
    # cybermetric_2000 — imported by Task replay on 2026-10-02 from
    #   inspect_evals.cybermetric.cybermetric:cybermetric_2000.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://raw.githubusercontent.com/cybermetric/CyberMetric/205262cdf5022ba890e792efd176fb19d42913fa/CyberMetric-2000-v1.json
    #     pin sha256 3ccc4d425bc4e74d27e0e9790d62369e4626e325d2b661d851c61b1648a0cd4a
    "cybermetric_2000": TaskReplayCasesSpec(
        task="inspect_evals.cybermetric.cybermetric:cybermetric_2000",
        case_count=2000,
        case_digest="f5f42a83a438a7cdadd29e35b92b233ecdbd6f8c57ce016d8115f0300fb967c1",
        # License: owner decision 2026-10-01: cybermetric/CyberMetric carries no license file.
        license="unknown",
    ),
    # cybermetric_10000 — imported by Task replay on 2026-10-02 from
    #   inspect_evals.cybermetric.cybermetric:cybermetric_10000.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://raw.githubusercontent.com/cybermetric/CyberMetric/205262cdf5022ba890e792efd176fb19d42913fa/CyberMetric-10000-v1.json
    #     pin sha256 4e35bb62c73b60bd27e54512b2ace6f9286ff2921a45a3d5fe2da22401e04bbb
    "cybermetric_10000": TaskReplayCasesSpec(
        task="inspect_evals.cybermetric.cybermetric:cybermetric_10000",
        case_count=10180,
        case_digest="058be2a68b92708a1e1a99c504fcbbfcd6b8b6c561eb92be0d4124d343fdbe58",
        # License: owner decision 2026-10-01: cybermetric/CyberMetric carries no license file.
        license="unknown",
    ),
    # sevenllm_mcq_zh — imported by Task replay on 2026-10-02 from
    #   inspect_evals.sevenllm.sevenllm:sevenllm_mcq_zh.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://huggingface.co/datasets/Multilingual-Multimodal-NLP/SEVENLLM-Dataset/raw/1de23ce55cadc984d3f3a7b52c4035a68c6cd5b0/test.jsonl
    #     pin commit 1de23ce55cadc984d3f3a7b52c4035a68c6cd5b0
    "sevenllm_mcq_zh": TaskReplayCasesSpec(
        task="inspect_evals.sevenllm.sevenllm:sevenllm_mcq_zh",
        case_count=50,
        case_digest="8c703ae7baf275cec15551ef2fd7c624547b05c64d50be6f907c28220bd5a823",
        # License: owner decision 2026-10-01: Apache-2.0, the SEVENLLM-Dataset card on Hugging Face.
        license="apache-2.0",
    ),
    # sevenllm_mcq_en — imported by Task replay on 2026-10-02 from
    #   inspect_evals.sevenllm.sevenllm:sevenllm_mcq_en.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://huggingface.co/datasets/Multilingual-Multimodal-NLP/SEVENLLM-Dataset/raw/1de23ce55cadc984d3f3a7b52c4035a68c6cd5b0/test.jsonl
    #     pin commit 1de23ce55cadc984d3f3a7b52c4035a68c6cd5b0
    "sevenllm_mcq_en": TaskReplayCasesSpec(
        task="inspect_evals.sevenllm.sevenllm:sevenllm_mcq_en",
        case_count=50,
        case_digest="dae1e9538a498a9cbb98ae8ec428db155258fd5a5660fab9d53f41874cf51578",
        # License: owner decision 2026-10-01: Apache-2.0, the SEVENLLM-Dataset card on Hugging Face.
        license="apache-2.0",
    ),
    # worldsense — imported by Task replay on 2026-10-02 from
    #   inspect_evals.worldsense.worldsense:worldsense.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://github.com/facebookresearch/worldsense/raw/bd81d945077f169cf95ff39207f788f86e4645e9/data/worldsense/test_set/trials.jsonl.bz2
    #     pin sha256 00c94031fc435c5f13156d57fcf61dace875d5e7fa4c218a40029a2eb0f3deb9
    "worldsense": TaskReplayCasesSpec(
        task="inspect_evals.worldsense.worldsense:worldsense",
        task_args={"shuffle": False},
        case_count=40176,
        case_digest="426b5a4e50aa171acc180de1e5836eb1f25b605a960ae8c6e08b1f414a3b079c",
        keep_sample_metadata=True,
        # License: owner decision 2026-10-01: CC-BY-NC-4.0, facebookresearch/worldsense LICENSE;
        #  non-commercial use only.
        license="cc-by-nc-4.0",
    ),
    # sad_facts_llms — imported by Task replay on 2026-10-02 from
    #   inspect_evals.sad.sad:sad_facts_llms.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/facts/human_defaults/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 fb5085dab38cecfac0a8e9fcbd663baab96c4837079fae80f9a7f4a823074650
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/facts/llms/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 c05b00d70bcf25bbccafb3cd64aadbce684a84041c36e7ac34cba533508a4f61
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/influence/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 63ed83e878320cd742f81a4c7f1d6ee413c508e68c053482453615cc48156881
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/stages/oversight/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 5b620b7bf45d04a2f79b1c7d2e825069fe774d853beeaff11b8b43c442c50ebb
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/stages/full/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 9bf272835a6b51c4b66010f8159dea3c92e62b587add54a1ec95148cf862293e
    "sad_facts_llms": TaskReplayCasesSpec(
        task="inspect_evals.sad.sad:sad_facts_llms",
        task_args={"seed": 7},
        case_count=249,
        case_digest="a84c6535db4e44841640423c96ab9030291eba2821896141494a9dfe0e8b9137",
        keep_sample_metadata=True,
        # License: owner decision 2026-10-01: CC-BY-4.0, LRudL/sad LICENSE; no dataset card.
        license="cc-by-4.0",
    ),
    # sad_facts_human_defaults — imported by Task replay on 2026-10-02 from
    #   inspect_evals.sad.sad:sad_facts_human_defaults.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/facts/human_defaults/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 fb5085dab38cecfac0a8e9fcbd663baab96c4837079fae80f9a7f4a823074650
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/facts/llms/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 c05b00d70bcf25bbccafb3cd64aadbce684a84041c36e7ac34cba533508a4f61
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/influence/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 63ed83e878320cd742f81a4c7f1d6ee413c508e68c053482453615cc48156881
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/stages/oversight/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 5b620b7bf45d04a2f79b1c7d2e825069fe774d853beeaff11b8b43c442c50ebb
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/stages/full/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 9bf272835a6b51c4b66010f8159dea3c92e62b587add54a1ec95148cf862293e
    "sad_facts_human_defaults": TaskReplayCasesSpec(
        task="inspect_evals.sad.sad:sad_facts_human_defaults",
        task_args={"seed": 7},
        case_count=1200,
        case_digest="faa75981e823a803b89f5aa3d47e2eddf58bf78075c2951b6db17a9347120980",
        keep_sample_metadata=True,
        # License: owner decision 2026-10-01: CC-BY-4.0, LRudL/sad LICENSE; no dataset card.
        license="cc-by-4.0",
    ),
    # sad_influence — imported by Task replay on 2026-10-02 from
    #   inspect_evals.sad.sad:sad_influence.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/facts/human_defaults/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 fb5085dab38cecfac0a8e9fcbd663baab96c4837079fae80f9a7f4a823074650
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/facts/llms/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 c05b00d70bcf25bbccafb3cd64aadbce684a84041c36e7ac34cba533508a4f61
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/influence/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 63ed83e878320cd742f81a4c7f1d6ee413c508e68c053482453615cc48156881
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/stages/oversight/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 5b620b7bf45d04a2f79b1c7d2e825069fe774d853beeaff11b8b43c442c50ebb
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/stages/full/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 9bf272835a6b51c4b66010f8159dea3c92e62b587add54a1ec95148cf862293e
    "sad_influence": TaskReplayCasesSpec(
        task="inspect_evals.sad.sad:sad_influence",
        task_args={"seed": 7},
        case_count=255,
        case_digest="cf1ebc85a3cb5b09f59bfc941fe5c162ad80f0b97a90f118fdc37eed39dd1c0b",
        keep_sample_metadata=True,
        # License: owner decision 2026-10-01: CC-BY-4.0, LRudL/sad LICENSE; no dataset card.
        license="cc-by-4.0",
    ),
    # sad_stages_oversight — imported by Task replay on 2026-10-02 from
    #   inspect_evals.sad.sad:sad_stages_oversight.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/facts/human_defaults/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 fb5085dab38cecfac0a8e9fcbd663baab96c4837079fae80f9a7f4a823074650
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/facts/llms/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 c05b00d70bcf25bbccafb3cd64aadbce684a84041c36e7ac34cba533508a4f61
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/influence/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 63ed83e878320cd742f81a4c7f1d6ee413c508e68c053482453615cc48156881
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/stages/oversight/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 5b620b7bf45d04a2f79b1c7d2e825069fe774d853beeaff11b8b43c442c50ebb
    #   url https://api.github.com/repos/LRudL/sad/contents/sad/stages/full/structs.zip?ref=dfc5c9831a9bcc5c9a9dbdcaa2955aae983cd1d3
    #     pin sha256 9bf272835a6b51c4b66010f8159dea3c92e62b587add54a1ec95148cf862293e
    "sad_stages_oversight": TaskReplayCasesSpec(
        task="inspect_evals.sad.sad:sad_stages_oversight",
        task_args={"seed": 7},
        case_count=400,
        case_digest="da1c29f15006c59da2807cca60390829efb2ad69c27552d63c265d091da13911",
        keep_sample_metadata=True,
        # License: owner decision 2026-10-01: CC-BY-4.0, LRudL/sad LICENSE; no dataset card.
        license="cc-by-4.0",
    ),
    # pre_flight — imported by Task replay on 2026-10-02 from
    #   inspect_evals.pre_flight.pre_flight:pre_flight.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face AirsideLabs/pre-flight-06
    #     pin revision 439d2d118fed7d9b009c1f87b9eb1205ab94766e
    "pre_flight": TaskReplayCasesSpec(
        task="inspect_evals.pre_flight.pre_flight:pre_flight",
        case_count=300,
        case_digest="eda28835a8b5c4dd45f2531315d6fcc2d2301d5ca59b1854346ff0e3c32ffd3f",
        # License: owner decision 2026-10-01: MIT, the AirsideLabs/pre-flight-06 card on
        #  Hugging Face.
        license="mit",
    ),
    # bbeh — imported by Task replay on 2026-10-02 from
    #   inspect_evals.bbeh.bbeh:bbeh.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face BBEH/bbeh
    #     pin revision 08e07a803851822c04399782ece3c4a07ce419f9
    "bbeh": TaskReplayCasesSpec(
        task="inspect_evals.bbeh.bbeh:bbeh",
        case_count=4519,
        case_digest="94e806ce381463c0f748ac90cbe5b4ba4b9d5b0ae88dec3f4350d34d11fd239b",
        keep_sample_metadata=True,
        # License: owner decision 2026-10-01: Apache-2.0, the BBEH/bbeh card on Hugging Face.
        license="apache-2.0",
    ),
    # --- importer: generated TaskReplayCasesSpec rows land above this line ---
}


def require_commit_sha(revision: str) -> str:
    """Refuse a mutable revision ref — only a 40-hex commit sha is benchmark identity.

    WHY: a branch/tag ref like ``main`` resolves to different data over time while
    the benchmark's revision hash — built from the unchanging ref STRING — stays the
    same: two builds could carry different benchmarks under one revision. The importer
    resolves refs to shas at import time; this is the mechanical backstop for a
    hand-written row (review round 2026-09-17).
    """

    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise PrepareError(
            f"dataset_revision {revision!r} is not a 40-hex commit sha — a mutable "
            "ref (branch/tag) would let upstream change a published exam; pin the "
            "resolved sha (the importer captures it for you)"
        )
    return revision


def templated_prompt(question: str, template: str) -> str:
    """The ``prompt_template(TEMPLATE), generate()`` eval family's render, prepared.

    One function for every free-text eval whose solver chain is
    ``[prompt_template(SOME_TEMPLATE), generate()]`` (16 of the 131 inspect_evals
    packages — gsm8k, math, aime, drop, paws, …): the spec points at the eval's own
    template constant, this applies that solver's one substitution.
    """

    return template.format(prompt=question)


def mcq_prompt(question: str, choices: Sequence[str], template: str | None = None) -> str:
    """The ``multiple_choice()`` eval family's 0-shot render — inspect's formatter, prepared.

    One function for every MCQ eval graded via the ``multiple_choice`` solver +
    ``choice()`` scorer (36 of the 131 inspect_evals packages). ``template`` is the
    eval's own override when it passes one to ``multiple_choice`` (the benchmark's
    ``choice_template`` reference, resolved by the caller); None renders inspect's
    default SINGLE_ANSWER template — a custom template must render VERBATIM, or the
    prepared benchmark would silently differ from the eval's (OME-1116 milestone C).
    """

    # AIDEV-NOTE: private-module import (inspect_ai.solver._multiple_choice) — safe
    # under the exact == pin; re-verify on any pin bump (the SINGLE_ANSWER prepared cases
    # test breaks loudly if the formatter moves or changes).
    from inspect_ai.solver import Choices, MultipleChoiceTemplate
    from inspect_ai.solver._multiple_choice import prompt as choice_prompt

    return choice_prompt(
        question=question,
        choices=Choices(list(choices)),
        template=str(MultipleChoiceTemplate.SINGLE_ANSWER.value) if template is None else template,
    )


def emit_cases(
    spec: CasesSpec,
    rows: list[dict[str, Any]],
    out: Path,
    *,
    expected_cases: int | None = None,
) -> dict[str, Any]:
    """Prepare any imported single-shot benchmark from the eval's own conversion functions.

    Think of it as one print shop for every imported benchmark: the spec points at the
    eval's own row-to-Sample rule and prompt template, and the shop prints the public
    booklet plus the sealed answer keys. Stages, in execution order:

        Stage 1 — refuse a mutable revision ref (only a 40-hex sha is benchmark identity)
                  and a wrong-sized dataset (the pinned case count is, too). A
                  question-filter benchmark checks its count after Stage 3b instead.
        Stage 2 — shuffle when the spec pins a seed (the prepared order is benchmark identity).
        Stage 3 — per row: the eval's ``record_to_sample`` builds the Sample; any raise
                  fails the prepare step by case number.
        Stage 3b — question-filter benchmarks only: the eval's own task function drops the
                  questions it would drop in inspect (:func:`task_kept_samples`); the
                  pinned case count is enforced on what it keeps.
        Stage 4 — shuffle each Sample's CHOICE order when the spec pins a choice seed,
                  via inspect's own ``MemoryDataset.shuffle_choices`` over the WHOLE
                  dataset at once — upstream draws every case's permutation from one
                  random stream, so a per-case shuffle would pin a different benchmark.
        Stage 5 — per Sample, via :func:`case_records`: cross the one validated boundary
                  (non-empty input/target,
                  target letter within the choices for MCQ benchmarks), then render the
                  prompt from the Sample's own shape: choices → the MCQ formatter; a
                  template reference → its substitution; neither → the raw input.
        Stage 6 — write the booklet (prompts only) and the private Grading Material records
                  (:func:`_write_cases`).

    Args:
        spec: the benchmark's prepare declaration.
        rows: raw dataset rows, one per Case.
        out: the empty directory to prepare into.
        expected_cases: the pinned case count to enforce; None skips the check (unit
            tests prepare tiny row lists; :func:`prepare_cases` always enforces).

    Returns:
        The prepare step summary: case count, dataset revision, output directory.
    """

    require_commit_sha(spec.dataset_revision)
    samples: list[Sample] = _pinned_samples(spec, rows, expected_cases)
    if spec.choice_shuffle_seed is not None:
        _shuffle_choices(samples, spec.choice_shuffle_seed)
    prepared: list[PreparedCase] = case_records(samples, spec)
    _write_cases(prepared, out)
    return {"cases": len(prepared), "dataset_revision": spec.dataset_revision, "out": str(out)}


def case_records(samples: Sequence[Sample], spec: CasesSpec) -> list[PreparedCase]:
    """Stage 5 — turn Samples into prepared Cases: the rendered input plus its Grading Material.

    The Hugging Face path's writer: it imitates the eval's render from the declaration's
    prompt fields. A Task-replay Benchmark never comes through here; its render is captured
    from the eval's own solvers (``capture.captured_case_records``), and the two share
    :func:`prepared_case` so a Case is written one way. Per Sample: render the prompt from
    the Sample's own shape, prepend the system text, and build the record.

    Args:
        samples: the Benchmark's Samples, in the order they are served.
        spec: the declaration whose prompt fields and writer options apply.

    Returns:
        One prepared Case per Sample, numbered from 1.
    """

    template: str | None = None if spec.prompt_template is None else _resolve(spec.prompt_template)
    choice_template: str | None = (
        None if spec.choice_template is None else _resolve(spec.choice_template)
    )
    system_text: str | None = _resolved_system_text(spec)
    prepared: list[PreparedCase] = []
    for case_id, sample in enumerate(samples, start=1):
        _, choices = _validated_answer_key(sample, case_id, spec.has_answer_key)
        input_text: str = _prompt(sample, choices, template, choice_template)
        if system_text is not None:
            # Named deviation (contracteval pattern): the eval's SYSTEM
            # instruction becomes the input's leading text, render untouched.
            input_text = f"{system_text}\n\n{input_text}"
        prepared.append(prepared_case(sample, case_id, input_text, spec))
    return prepared


def prepared_case(
    sample: Sample, case_id: int, input_text: str, spec: CasesSpec | TaskReplayCasesSpec
) -> PreparedCase:
    """One prepared Case from a Sample and its rendered input: the public row plus the
    private Grading Material, after the one validated boundary on eval-produced Samples.

    Shared by both preparation paths (OME-1273), so a Hugging Face Benchmark and a
    Task-replay Benchmark can never drift on how a Case is written.
    """

    target, choices = _validated_answer_key(sample, case_id, spec.has_answer_key)
    record: dict[str, Any] = (
        {"target": target} if choices is None else {"target": target, "choices": choices}
    )
    if spec.keep_sample_metadata and sample.metadata:
        record["metadata"] = _validated_metadata(sample.metadata, case_id)
    # WHY "case_id" beside "id": the benchmark's url4 protocol template reads
    # $item.case_id per Case (the transport contract's string spelling);
    # "id" is the integer that cases.json rows and the targets/ files key on.
    return {
        "case": {"id": case_id, "case_id": str(case_id), "input": input_text},
        "grading_material": record,
    }


def _pinned_samples(
    spec: CasesSpec, rows: list[dict[str, Any]], expected_cases: int | None
) -> list[Sample]:
    """Stages 1 (size), 2, 3 and 3b — the raw rows become the benchmark's Samples, in the
    pinned order. A benchmark that drops questions (a question filter, or a named exclusion)
    checks its size on what is left instead of on the raw rows."""

    drops_questions: bool = (
        spec.question_filter_task is not None or spec.excluded_sample_ids is not None
    )
    if not drops_questions:
        _require_case_count(len(rows), expected_cases, "dataset yielded", "rows")
    ordered: list[dict[str, Any]] = list(rows)
    if spec.shuffle_seed is not None:
        random.Random(spec.shuffle_seed).shuffle(ordered)
    samples: list[Sample] = _converted_samples(ordered, _resolve(spec.record_to_sample))
    if spec.question_filter_task is not None:
        samples = task_kept_samples(spec, samples)
    if spec.excluded_sample_ids is not None:
        samples = _without_excluded_samples(spec.excluded_sample_ids, samples)
    if drops_questions:
        _require_case_count(len(samples), expected_cases, "the prepare step kept", "cases")
    return samples


def _without_excluded_samples(excluded_ids: tuple[str, ...], samples: list[Sample]) -> list[Sample]:
    """The named deviation — drop the pinned ids, refusing any id that is not there.

    WHY refuse a missing id: the list was written against one revision's data; an
    id that no longer matches means the exclusion now describes nothing we can
    check, so the prepare step stops instead of shipping it.
    """

    present: set[str] = {str(sample.id) for sample in samples}
    missing: list[str] = sorted(set(excluded_ids) - present)
    if missing:
        raise PrepareError(
            f"excluded_sample_ids {', '.join(missing)} are not in the dataset — the named "
            "deviation no longer matches the pinned Samples"
        )
    return [sample for sample in samples if str(sample.id) not in excluded_ids]


def _converted_samples(ordered: list[dict[str, Any]], record_to_sample: Any) -> list[Sample]:
    """Stage 3 — every row through the eval's own conversion, failing by case number."""

    samples: list[Sample] = []
    for case_id, row in enumerate(ordered, start=1):
        try:
            samples.append(record_to_sample(row))
        except Exception as exc:  # noqa: BLE001 — WHY broad: the conversion is eval
            # code over an untrusted row; ANY raise must fail the prepare step by case number.
            raise PrepareError(
                f"case {case_id}: record_to_sample refused the row ({type(exc).__name__}: {exc})"
            ) from exc
    return samples


def task_kept_samples(spec: CasesSpec, samples: list[Sample]) -> list[Sample]:
    """Stage 3b — let the eval's own task pick which pinned Samples stay (OME-1269).

    Think of it as handing the eval's examiner our printed question stack instead
    of letting them fetch their own: they throw out the questions their rules
    exclude, and we freeze whatever they hand back. Worked example: pubmedqa's
    task loads 1,000 rows and keeps the 500 whose ids are on its bundled test
    list — we give it our 1,000 pinned Samples, it hands back 500, and the benchmark
    holds exactly those 500, in our pinned order.

    Stages, in execution order:

        Stage 1 — resolve the task function and its module's ``hf_dataset``
                  binding (the one load the eval makes; no binding → refuse).
        Stage 2 — swap that binding for a loader that returns a FRESH dataset of
                  our pinned Samples (no download, and the eval's own shuffle kwargs are
                  ignored: the order is already pinned), then call the task with
                  ``spec.question_filter_task_args``. A raise refuses by name — e.g. inspect's
                  "dataset is empty" when the filter kept nothing.
        Stage 3 — refuse unless the loader ran exactly once (a second load, a
                  fewshot pool, would have been handed the benchmark's Samples too), and
                  asked for the dataset, config and split this row pins (the swap
                  ignores them, so a mismatched row would prepare another load's benchmark).
        Stage 4 — refuse unless the Samples the Task holds are an in-order subset of ours,
                  compared by identity: the question filter may only DROP questions. An
                  added, duplicated or reordered Sample is a benchmark we never pinned.

    Args:
        spec: the benchmark's prepare declaration; ``spec.question_filter_task`` must be set.
        samples: our pinned Samples — converted by the eval's ``record_to_sample``
            and already in the benchmark's seeded order.

    Returns:
        The Samples the eval keeps, in our pinned order.
    """

    # Stage 1 — the task function and the load it makes.
    task_ref: str = str(spec.question_filter_task)
    module_name, _, attribute = task_ref.partition(":")
    module: Any = import_module(module_name)
    task_fn: Any = getattr(module, attribute)
    if not hasattr(module, "hf_dataset"):
        raise PrepareError(
            f"task {task_ref}: its module has no hf_dataset binding — the question-filter step "
            "can only hand the pinned Samples to an eval that loads through it"
        )

    # Stage 2 — swap the load for our pinned Samples, then build the eval's Task.
    from inspect_ai.dataset import MemoryDataset

    loads: list[dict[str, Any]] = []

    def pinned_loader(*args: Any, **kwargs: Any) -> Any:
        loads.append(_load_arguments(args, kwargs))
        return MemoryDataset(list(samples))

    original_loader: Any = module.hf_dataset
    module.hf_dataset = pinned_loader
    try:
        task: Any = task_fn(**dict(spec.question_filter_task_args or {}))
    except Exception as exc:  # noqa: BLE001 — WHY broad: this is eval code over our
        # pinned Samples; ANY raise must refuse the prepare step by name, never crash raw.
        raise PrepareError(
            f"task {task_ref}: the eval's task refused the pinned Samples "
            f"({type(exc).__name__}: {exc})"
        ) from exc
    finally:
        module.hf_dataset = original_loader

    # Stage 3 — exactly one load, of the dataset this row pins.
    if len(loads) != 1:
        paths: str = ", ".join(str(load.get("path", "?")) for load in loads) or "none"
        raise PrepareError(
            f"task {task_ref}: loaded {len(loads)} datasets ({paths}) — "
            "the question-filter step hands the pinned questions to exactly one load"
        )
    _require_the_pinned_load(task_ref, spec, loads[0])

    # Stage 4 — the kept Samples become our Cases, each once, in our order.
    kept: list[Sample] = list(task.dataset)
    _require_in_order_subset(task_ref, samples, kept)
    return kept


def _load_arguments(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """One swapped-out hf_dataset call as ``{parameter: value}``, bound like the real one.

    WHY bind: evals pass ``path`` (and sometimes ``split``) positionally; reading only
    kwargs would miss them. An unbindable call records nothing checkable, so the
    pinned-load check below refuses it.
    """

    import inspect as _inspect

    from inspect_ai.dataset import hf_dataset

    try:
        return dict(_inspect.signature(hf_dataset).bind_partial(*args, **kwargs).arguments)
    except TypeError:
        return {}


def _require_the_pinned_load(task_ref: str, spec: CasesSpec, arguments: dict[str, Any]) -> None:
    """Stage 3 of the question-filter step — the eval must ask for the load this row pins.

    WHY: the swap hands the task our pinned Samples whatever it asks for, so a row
    whose dataset/config/split drifted from the task's own call would prepare one
    load's questions through another load's filter, with every count agreeing.
    Worked example: onet_m6 asks ``path="matichon/thai-onet-m6-exam",
    name="default", split="test"`` and its row pins exactly those.
    """

    asked: dict[str, Any] = {
        "dataset": arguments.get("path"),
        "config": arguments.get("name") or "",
        "split": arguments.get("split"),
    }
    pinned: dict[str, str] = {"dataset": spec.dataset, "config": spec.config, "split": spec.split}
    mismatched: list[str] = [
        f"{field} {asked[field]!r} (the row pins {pinned[field]!r})"
        for field in pinned
        if asked[field] != pinned[field]
    ]
    if mismatched:
        raise PrepareError(
            f"task {task_ref}: the eval asks for a different load than its row — "
            + "; ".join(mismatched)
        )


def _require_in_order_subset(task_ref: str, samples: list[Sample], kept: list[Sample]) -> None:
    """Stage 4 of the question-filter step — refuse unless ``kept`` only DROPS from ``samples``.

    Compared by object identity (inspect's filter keeps the very Sample objects),
    so a look-alike question the task built itself is caught too. Worked example:
    pinned [s1, s2, s3, s4] → kept [s2, s4] passes; [s4, s2] (reordered), [s2, s2]
    (duplicated) or [s2, x] (added) refuse.
    """

    position_of: dict[int, int] = {id(sample): index for index, sample in enumerate(samples)}
    last_position: int = -1
    for sample in kept:
        position: int | None = position_of.get(id(sample))
        if position is None or position <= last_position:
            raise PrepareError(
                f"task {task_ref}: the Task's dataset is not an in-order subset of the "
                "pinned Samples — the task added, duplicated or reordered a sample"
            )
        last_position = position


def count_kept_cases(spec: CasesSpec) -> int:
    """How many questions a question-filter benchmark keeps at its pinned revision.

    The importer's case count for a question-filter row (import time only; this
    downloads the pinned split). Order cannot change the count, so no shuffle.
    """

    rows: list[dict[str, Any]] = _load_rows(spec)
    samples: list[Sample] = _converted_samples(rows, _resolve(spec.record_to_sample))
    return len(task_kept_samples(spec, samples))


def _shuffle_choices(samples: list[Sample], seed: int) -> None:
    """Stage 4 — pin each case's choice order with inspect's OWN shuffle, in place.

    WHY the whole dataset at once: ``MemoryDataset.shuffle_choices`` draws every
    sample's permutation (and target-letter remap) from ONE ``random.Random(seed)``
    stream, so each case's order depends on its position — shuffling per case
    would prepare a different benchmark than the eval family produces for this seed.
    """

    from inspect_ai.dataset import MemoryDataset

    try:
        MemoryDataset(samples).shuffle_choices(seed=seed)
    except Exception as exc:  # noqa: BLE001 — WHY broad: the shuffle runs inspect's
        # letter remap over eval-produced Samples; ANY raise (a non-letter target
        # hitting ord(), an out-of-range letter) must surface as the prepare step's own
        # named refusal, never a raw TypeError/KeyError (review finding on PR #1031).
        raise PrepareError(
            f"choice shuffle refused the dataset ({type(exc).__name__}: {exc}) — "
            "a sample's target/choices do not fit inspect's letter remap"
        ) from exc


def _resolved_system_text(spec: CasesSpec) -> str | None:
    """The eval's system instruction as leading input text, or None without one.

    WHY stripped once here: eval constants often carry framing newlines
    (hellaswag's SYSTEM_MESSAGE); the leading text must join the render with
    exactly one blank line. A non-string resolution (a mispointed reference
    landing on a function) refuses the prepare step — str() would silently prepare its
    repr into every case of the benchmark (review finding on PR #1018).
    """

    if spec.system_message is None:
        return None
    resolved_message: Any = _resolve(spec.system_message)
    if not isinstance(resolved_message, str):
        raise PrepareError(
            f"system_message {spec.system_message} must resolve to text, "
            f"got {type(resolved_message).__name__}"
        )
    return resolved_message.strip()


def prepare_cases(spec: CasesSpec, out: Path) -> dict[str, Any]:
    """Snapshot one benchmark's pinned HF split and prepare its assets (build time only).

    A gated dataset needs a Hugging Face token (``HF_TOKEN``, or a cached login).
    Without one the prepare step refuses by name, so a main or release image can never ship
    missing a benchmark; a PR build that sets ``SCREAMINGFACE_SKIP_BENCHMARKS_NEEDING_HF_TOKEN=1``
    skips the benchmark instead, writes nothing, and says so loudly in the build log.
    """

    if spec.needs_hf_token and _available_hf_token() is None:
        if os.environ.get(SKIP_BENCHMARKS_NEEDING_HF_TOKEN_ENV) != "1":
            raise PrepareError(
                f"{spec.dataset} is a gated Hugging Face dataset and no token is available — "
                "in CI, check the HF_TOKEN_BENCHMARKS repo secret; locally, export HF_TOKEN "
                "as a read-only token from an account that accepted the dataset's terms"
            )
        reason: str = f"gated dataset {spec.dataset}, built without a Hugging Face token"
        print(
            f"WARNING: skipping {reason} ({SKIP_BENCHMARKS_NEEDING_HF_TOKEN_ENV}=1); "
            "this image has NO assets for its board",
            file=sys.stderr,
            flush=True,
        )
        out.mkdir(parents=True, exist_ok=True)
        (out / SKIPPED_MARKER).write_text(reason + "\n", encoding="utf-8")
        return {"cases": 0, "skipped": reason, "out": str(out)}
    rows: list[dict[str, Any]] = _load_rows(spec)
    return emit_cases(spec, rows, out, expected_cases=spec.case_count)


def _prompt(
    sample: Sample,
    choices: list[str] | None,
    template: str | None,
    choice_template: str | None,
) -> str:
    """Stage 4 — the render is derived from the Sample's own shape, never per benchmark."""

    question: str = str(sample.input)
    if choices is not None:
        return mcq_prompt(question, choices, choice_template)
    if template is not None:
        return templated_prompt(question, template)
    return question


def _resolve(reference: str) -> Any:
    """Resolve one ``"module:attr"`` spec reference into the eval's own object."""

    module_name, _, attribute = reference.partition(":")
    return getattr(import_module(module_name), attribute)


def _validated_answer_key(
    sample: Sample, case_id: int, has_answer_key: bool = True
) -> tuple[str, list[str] | None]:
    """The one trust boundary on eval-produced Samples — never prepare an unkeyed Case.

    ``has_answer_key=False`` (a judged benchmark whose judge never reads a key) is the
    one place an empty answer key is accepted; the question itself is still required.
    """

    _require_a_question(sample, case_id)
    target: object = sample.target
    if not has_answer_key and target in ("", []) and sample.choices is None:
        return "", None
    if not isinstance(target, str) or not target.strip():
        raise PrepareError(f"case {case_id}: sample target is empty or not text")
    if sample.choices is None:
        return target, None
    choices: list[str] = [str(choice) for choice in sample.choices]
    if not choices or any(not choice.strip() for choice in choices):
        raise PrepareError(f"case {case_id}: sample carries an empty choice")
    letters: str = "".join(chr(ord("A") + index) for index in range(len(choices)))
    # WHY by value too: an eval that lists its options inside the question and asks for a
    # number (worldsense: choices "1" "2" "3", target "2") keys its answer by the choice's
    # value, not a letter; its own scorer reads it that way. Either form names one option.
    if target not in letters and target not in choices:
        raise PrepareError(
            f"case {case_id}: target {target!r} is neither a letter within {len(choices)} "
            "choices nor one of them"
        )
    return target, choices


def _require_a_question(sample: Sample, case_id: int) -> None:
    """Refuse a Sample with nothing to ask. WHY a list is accepted: a Sample may carry its
    input as chat messages; capture decides whether that shape is one prompt, this boundary
    only refuses an empty question."""

    if isinstance(sample.input, list):
        if not sample.input:
            raise PrepareError(f"case {case_id}: sample input is an empty message list")
    elif not isinstance(sample.input, str) or not sample.input.strip():
        raise PrepareError(f"case {case_id}: sample input is empty or not text")


def _validated_metadata(metadata: dict[str, Any], case_id: int) -> dict[str, Any]:
    """The Grading Material file is JSON — refuse an unserializable metadata value by case
    number; truncating or coercing a benchmark asset silently is never an option."""

    try:
        json.dumps(metadata)
    except (TypeError, ValueError) as exc:
        raise PrepareError(
            f"case {case_id}: sample metadata is not JSON-serializable ({exc})"
        ) from exc
    return metadata


def _require_case_count(count: int, expected: int | None, source: str, unit: str) -> None:
    """Refuse a wrong-sized prepare — a config/revision typo must never ship a smaller benchmark.

    WHY: the row count is part of the benchmark's identity (the pinned CASE_COUNT rides the
    revision hash); an upstream change or a wrong split silently yielding 0 or N±k rows
    would prepare a DIFFERENT benchmark with a green build. ``source``/``unit`` name what was
    counted: raw rows ("dataset yielded … rows") or a question filter's kept cases.
    """

    if expected is not None and count != expected:
        raise PrepareError(f"{source} {count} {unit}, pinned case count is {expected}")


def _write_cases(prepared: Sequence[PreparedCase], out: Path) -> None:
    """Stage 6 — write the public booklet and the private Grading Material records."""

    grading_material_dir: Path = out / "targets"
    # WHY refuse a dirty out: a re-prepare into a used directory would leave orphan
    # targets/*.json from a previous, larger prepare — the image build always starts
    # fresh, and this makes that assumption loud instead of silent.
    if (out / "cases.json").exists() or (
        grading_material_dir.is_dir() and any(grading_material_dir.iterdir())
    ):
        raise PrepareError(f"refusing to prepare into non-empty directory {out}")
    grading_material_dir.mkdir(parents=True, exist_ok=True)
    for item in prepared:
        (grading_material_dir / f"{item['case']['id']}.json").write_text(
            json.dumps(item["grading_material"], ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    (out / "cases.json").write_text(
        json.dumps([item["case"] for item in prepared], ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _available_hf_token() -> str | None:
    """The Hugging Face token ``datasets`` would send: ``HF_TOKEN`` or a cached login."""

    from huggingface_hub import get_token

    return get_token()


def _load_rows(spec: CasesSpec) -> list[dict[str, Any]]:
    """Load one pinned HF split — ``datasets`` is a build-environment dependency only."""

    try:
        import datasets  # noqa: PLC0415 — build-time-only dependency, by design
    except ModuleNotFoundError as exc:
        raise PrepareError(
            "the `datasets` package is required to prepare a benchmark — "
            "`uv pip install datasets` in the build environment"
        ) from exc
    selection: dict[str, Any] = {}
    if spec.data_files is not None:
        selection["data_files"] = spec.data_files
    if spec.features is not None:
        resolved_schema: Any = _resolve(spec.features)
        # WHY the type check: a mispointed reference landing on a string or a
        # function would corrupt every row silently or crash deep inside
        # `datasets` — refuse the prepare step by name instead (OME-1264 extension 2).
        if not isinstance(resolved_schema, datasets.Features):
            raise PrepareError(
                f"features {spec.features} must resolve to a datasets.Features "
                f"schema, got {type(resolved_schema).__name__}"
            )
        selection["features"] = resolved_schema
    loaded = datasets.load_dataset(
        spec.dataset, spec.config, revision=spec.dataset_revision, split=spec.split, **selection
    )
    return [dict(row) for row in loaded]


__all__ = [
    "PrepareError",
    "BENCHMARK_CASES",
    "CasesSpec",
    "LICENSE_TODO",
    "PreparedCase",
    "TASK_REPLAY_CASES",
    "TaskReplayCasesSpec",
    "case_digest",
    "case_records",
    "count_kept_cases",
    "emit_cases",
    "mcq_prompt",
    "prepare_cases",
    "prepared_case",
    "task_kept_samples",
    "templated_prompt",
]
