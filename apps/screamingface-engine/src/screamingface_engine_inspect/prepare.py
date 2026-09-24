# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on, and with the extra installed
# these imports type-check normally.
"""Bake the imported boards' assets: public prompts and private targets.

Run at IMAGE BUILD time, never at run time (OME-925): a Job's rootfs is read-only and
holds no HuggingFace credential, so every artifact exists before a run starts. HF
downloads happen here once; upstream gating or drift cannot change a published board.

Emits, per board::

    <out>/cases.json         [{"id", "case_id", "input"}] — ALL a client sees
    <out>/targets/<id>.json  {"target": ..., "choices": [...]?} — private; read by the
                             aggregate (the shim's grading material) and the check surface

ONE generic pipeline serves every imported single-shot board; a board is a
:class:`SnapshotSpec` DATA entry in :data:`SNAPSHOTS` — dataset pins plus two dotted
references into the eval's own code (its ``record_to_sample`` row rule, its prompt
template). Row conversion and prompt formatting are inspect's own functions, CALLED,
never reimplemented, so an imported exam's content is exactly what the eval publishes.
Importing eval #3 means adding one spec entry, zero new functions.

INVARIANT — the Sample coming back from the eval's ``record_to_sample`` crosses ONE
validated boundary (:func:`_validated_target`): a malformed row fails the whole bake
by case number, never bakes a half-keyed or unkeyed exam.

INVARIANT — ``cases.json`` carries NO target. The client receives ids and prompts; the
answer key stays in the image.
"""

from __future__ import annotations

import json
import random
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
    PAWS_CASE_COUNT,
    PAWS_CONFIG,
    PAWS_DATASET,
    PAWS_DATASET_REVISION,
    PAWS_SHUFFLE_SEED,
    PAWS_SPLIT,
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
)

if TYPE_CHECKING:
    from inspect_ai.dataset import Sample


class PrepareError(BenchmarkAssetPreparationError):
    """The build refuses to bake these assets. Always says which row and why."""


@dataclass(frozen=True)
class SnapshotSpec:
    """One imported board's bake, as pure data — pins plus pointers into the eval.

    ``record_to_sample`` and ``prompt_template`` are dotted ``"module:attr"``
    references into the eval's own package, resolved lazily at bake time (the
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
    #: convention as ``prompt_template``, resolved lazily at bake time.
    choice_template: str | None = None
    #: The eval's system instruction, delivered as the LEADING TEXT of the
    #: candidate input at bake time — a benchmark cannot address a candidate's
    #: system role (the contracteval named-deviation pattern), so the
    #: instruction rides ahead of the render. Same dotted-reference convention
    #: as ``prompt_template``.
    system_message: str | None = None
    shuffle_seed: int | None = None
    #: Pins one per-case CHOICE order for an eval whose hf_dataset call shuffles
    #: choices (shuffle_choices) — applied via inspect's own
    #: ``MemoryDataset.shuffle_choices`` over THIS BAKE'S pinned row order. The
    #: pinned order is exam identity (it rides the board's revision pins); it is
    #: NOT the order inspect would produce for the same seeds when a row shuffle
    #: is also active, because the bake's row shuffle is not HF's algorithm —
    #: the importer refuses that combination whenever upstream seeded either
    #: shuffle (review blocker on PR #1031). OME-1264.
    choice_shuffle_seed: int | None = None
    #: hf_dataset's data_files selection (a dict of str to str, infinite_bench's
    #: {"passkey": "passkey.jsonl"}), forwarded verbatim to
    #: ``datasets.load_dataset`` — it selects WHICH files load, so it rides the
    #: board's revision pins. OME-1264 extension 2.
    data_files: Any = None
    #: The eval's Features schema as a dotted POINTER at its own module constant
    #: (infinite_bench's ``constants:ft``) — same convention as
    #: ``record_to_sample``; resolved at bake time and required to be a
    #: ``datasets.Features``. Rides the board's revision pins too.
    features: str | None = None


#: Every imported board's bake. Importing another eval = one more entry here
#: (plus its pins) — never a new function.
SNAPSHOTS: dict[str, SnapshotSpec] = {
    "gsm8k": SnapshotSpec(
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
    "mmlu": SnapshotSpec(
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
    "arc_easy": SnapshotSpec(
        dataset=ARC_EASY_DATASET,
        config=ARC_EASY_CONFIG,
        split=ARC_EASY_SPLIT,
        dataset_revision=ARC_EASY_DATASET_REVISION,
        case_count=ARC_EASY_CASE_COUNT,
        # arc_easy's dataset: sample_fields=record_to_sample (letters or numbered
        # answerKeys normalized to letters); prompt = the default MCQ render.
        # Verified by a full offline bake, 2026-09-17.
        record_to_sample="inspect_evals.arc.arc:record_to_sample",
    ),
    "arc_challenge": SnapshotSpec(
        dataset=ARC_CHALLENGE_DATASET,
        config=ARC_CHALLENGE_CONFIG,
        split=ARC_CHALLENGE_SPLIT,
        dataset_revision=ARC_CHALLENGE_DATASET_REVISION,
        case_count=ARC_CHALLENGE_CASE_COUNT,
        # Same eval module as arc_easy — only the HF config differs.
        # Verified by a full offline bake, 2026-09-17.
        record_to_sample="inspect_evals.arc.arc:record_to_sample",
    ),
    "commonsense_qa": SnapshotSpec(
        dataset=COMMONSENSE_QA_DATASET,
        config=COMMONSENSE_QA_CONFIG,
        split=COMMONSENSE_QA_SPLIT,
        dataset_revision=COMMONSENSE_QA_DATASET_REVISION,
        case_count=COMMONSENSE_QA_CASE_COUNT,
        # commonsense_qa's dataset: sample_fields=record_to_sample (5 choices,
        # letter target); prompt = the default MCQ render. Verified by a full
        # offline bake, 2026-09-17.
        record_to_sample="inspect_evals.commonsense_qa.commonsense_qa:record_to_sample",
        # WHY the seed: the upstream eval shuffles this exam's order per run
        # (hf_dataset shuffle=True, no seed) — the import pins one order as
        # exam identity (review round 2026-09-17).
        shuffle_seed=COMMONSENSE_QA_SHUFFLE_SEED,
    ),
    "paws": SnapshotSpec(
        dataset=PAWS_DATASET,
        config=PAWS_CONFIG,
        split=PAWS_SPLIT,
        dataset_revision=PAWS_DATASET_REVISION,
        case_count=PAWS_CASE_COUNT,
        # paws' task: solver=[prompt_template(TEMPLATE), generate()]; target is
        # Yes/No from the label. Verified by a full offline bake, 2026-09-17.
        record_to_sample="inspect_evals.paws.paws:record_to_sample",
        prompt_template="inspect_evals.paws.paws:TEMPLATE",
        # WHY the seed: the upstream eval shuffles this exam's order per run
        # (hf_dataset shuffle=True, no seed) — the import pins one order as
        # exam identity (review round 2026-09-17).
        shuffle_seed=PAWS_SHUFFLE_SEED,
    ),
    "boolq": SnapshotSpec(
        dataset=BOOLQ_DATASET,
        config=BOOLQ_CONFIG,
        split=BOOLQ_SPLIT,
        dataset_revision=BOOLQ_DATASET_REVISION,
        case_count=BOOLQ_CASE_COUNT,
        # boolq's dataset: sample_fields=record_to_sample (passage folded into
        # the question, Yes/No target); raw-input render (no template).
        # Verified by a full offline bake, 2026-09-17.
        record_to_sample="inspect_evals.boolq.boolq:record_to_sample",
        # WHY the seed: the upstream eval shuffles this exam's order per run
        # (hf_dataset shuffle=True, no seed) — the import pins one order as
        # exam identity (review round 2026-09-17).
        shuffle_seed=BOOLQ_SHUFFLE_SEED,
    ),
    "mmlu_pro": SnapshotSpec(
        dataset=MMLU_PRO_DATASET,
        config=MMLU_PRO_CONFIG,
        split=MMLU_PRO_SPLIT,
        dataset_revision=MMLU_PRO_DATASET_REVISION,
        case_count=MMLU_PRO_CASE_COUNT,
        # mmlu_pro's dataset: sample_fields=record_to_sample (10 options); the
        # prompt renders through the eval's own CoT template below. Verified by
        # a full offline bake, 2026-09-17.
        record_to_sample="inspect_evals.mmlu_pro.mmlu_pro:record_to_sample",
        choice_template="inspect_evals.mmlu_pro.mmlu_pro:USER_PROMPT_TEMPLATE",
        # WHY the shuffle: the HF split is category-grouped (first 100 rows are
        # one discipline), so a limit=N run over raw order would examine one
        # discipline; the seed rides the revision hash.
        shuffle_seed=MMLU_PRO_SHUFFLE_SEED,
    ),
    "winogrande": SnapshotSpec(
        dataset=WINOGRANDE_DATASET,
        config=WINOGRANDE_CONFIG,
        split=WINOGRANDE_SPLIT,
        dataset_revision=WINOGRANDE_DATASET_REVISION,
        case_count=WINOGRANDE_CASE_COUNT,
        # winogrande's dataset (fewshot=0): sample_fields=record_to_sample
        # ([BLANK] sentence, two options); renders through the eval's own
        # template below. Verified by a full offline bake, 2026-09-17.
        record_to_sample="inspect_evals.winogrande.winogrande:record_to_sample",
        choice_template="inspect_evals.winogrande.winogrande:USER_PROMPT_TEMPLATE",
    ),
    "race_h": SnapshotSpec(
        dataset=RACE_H_DATASET,
        config=RACE_H_CONFIG,
        split=RACE_H_SPLIT,
        dataset_revision=RACE_H_DATASET_REVISION,
        case_count=RACE_H_CASE_COUNT,
        # race_h's dataset: sample_fields=record_to_sample (passage + question
        # folded into input); renders through the eval's own template below.
        # Verified by a full offline bake, 2026-09-17.
        record_to_sample="inspect_evals.race_h.race_h:record_to_sample",
        choice_template="inspect_evals.race_h.race_h:TEMPLATE",
        # WHY the shuffle: questions arrive in per-passage runs, so a small
        # limit=N run would see few passages; the seed rides the revision hash.
        shuffle_seed=RACE_H_SHUFFLE_SEED,
    ),
    "aime24": SnapshotSpec(
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
    "aime25": SnapshotSpec(
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
    "musr": SnapshotSpec(
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
        # exam content. Every format instruction rides REGULAR_PROMPT, which IS
        # the baked choice_template, so the baked prompt matches the eval's
        # rendered user turn.
    ),
    "wmdp_bio": SnapshotSpec(
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
        # bake's unfiltered rows are the same exam.
        record_to_sample="inspect_evals.wmdp.wmdp:record_to_sample",
    ),
    "wmdp_chem": SnapshotSpec(
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
        # bake's unfiltered rows are the same exam.
        record_to_sample="inspect_evals.wmdp.wmdp:record_to_sample",
    ),
    "wmdp_cyber": SnapshotSpec(
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
        # bake's unfiltered rows are the same exam.
        record_to_sample="inspect_evals.wmdp.wmdp:record_to_sample",
    ),
    "hellaswag": SnapshotSpec(
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
        # bake delivers it as leading input text (a benchmark cannot
        # address a candidate's system role).
        system_message="inspect_evals.hellaswag.hellaswag:SYSTEM_MESSAGE",
        # WHY the seed: the split is domain-grouped (ActivityNet then
        # WikiHow) — see the pin's comment; OURS by policy.
        shuffle_seed=HELLASWAG_SHUFFLE_SEED,
    ),
    "lab_bench_litqa": SnapshotSpec(
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
    "lab_bench_suppqa": SnapshotSpec(
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
    "lab_bench_dbqa": SnapshotSpec(
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
    "lab_bench_protocolqa": SnapshotSpec(
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
    "lab_bench_seqqa": SnapshotSpec(
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
    "lab_bench_cloning_scenarios": SnapshotSpec(
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
    # --- importer: generated SnapshotSpec rows land above this line ---
}


def require_commit_sha(revision: str) -> str:
    """Refuse a mutable revision ref — only a 40-hex commit sha is exam identity.

    WHY: a branch/tag ref like ``main`` resolves to different data over time while
    the board's revision hash — built from the unchanging ref STRING — stays the
    same: two builds could carry different exams under one revision. The importer
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
    """The ``prompt_template(TEMPLATE), generate()`` eval family's render, baked.

    One function for every free-text eval whose solver chain is
    ``[prompt_template(SOME_TEMPLATE), generate()]`` (16 of the 131 inspect_evals
    packages — gsm8k, math, aime, drop, paws, …): the spec points at the eval's own
    template constant, this applies that solver's one substitution.
    """

    return template.format(prompt=question)


def mcq_prompt(question: str, choices: Sequence[str], template: str | None = None) -> str:
    """The ``multiple_choice()`` eval family's 0-shot render — inspect's formatter, baked.

    One function for every MCQ eval graded via the ``multiple_choice`` solver +
    ``choice()`` scorer (36 of the 131 inspect_evals packages). ``template`` is the
    eval's own override when it passes one to ``multiple_choice`` (the board's
    ``choice_template`` reference, resolved by the caller); None renders inspect's
    default SINGLE_ANSWER template — a custom template must render VERBATIM, or the
    baked exam would silently differ from the eval's (OME-1116 milestone C).
    """

    # AIDEV-NOTE: private-module import (inspect_ai.solver._multiple_choice) — safe
    # under the exact == pin; re-verify on any pin bump (the SINGLE_ANSWER snapshot
    # test breaks loudly if the formatter moves or changes).
    from inspect_ai.solver import Choices, MultipleChoiceTemplate
    from inspect_ai.solver._multiple_choice import prompt as choice_prompt

    return choice_prompt(
        question=question,
        choices=Choices(list(choices)),
        template=str(MultipleChoiceTemplate.SINGLE_ANSWER.value) if template is None else template,
    )


def emit_snapshot(
    spec: SnapshotSpec,
    rows: list[dict[str, Any]],
    out: Path,
    *,
    expected_cases: int | None = None,
) -> dict[str, Any]:
    """Bake any imported single-shot board from the eval's own conversion functions.

    Think of it as one print shop for every imported exam: the spec points at the
    eval's own row-to-Sample rule and prompt template, and the shop prints the public
    booklet plus the sealed answer keys. Stages, in execution order:

        Stage 1 — refuse a mutable revision ref (only a 40-hex sha is exam identity)
                  and a wrong-sized dataset (the pinned case count is, too).
        Stage 2 — shuffle when the spec pins a seed (the baked order is exam identity).
        Stage 3 — per row: the eval's ``record_to_sample`` builds the Sample; any raise
                  fails the bake by case number.
        Stage 4 — shuffle each Sample's CHOICE order when the spec pins a choice seed,
                  via inspect's own ``MemoryDataset.shuffle_choices`` over the WHOLE
                  dataset at once — upstream draws every case's permutation from one
                  random stream, so a per-case shuffle would pin a different exam.
        Stage 5 — per Sample: cross the one validated boundary (non-empty input/target,
                  target letter within the choices for MCQ boards), then render the
                  prompt from the Sample's own shape: choices → the MCQ formatter; a
                  template reference → its substitution; neither → the raw input.
        Stage 6 — write the booklet (prompts only) and the private targets.

    Args:
        spec: the board's bake declaration.
        rows: raw dataset rows, one per Case.
        out: the empty directory to bake into.
        expected_cases: the pinned case count to enforce; None skips the check (unit
            tests bake tiny row lists; :func:`prepare_snapshot` always enforces).

    Returns:
        The bake summary: case count, dataset revision, output directory.
    """

    require_commit_sha(spec.dataset_revision)
    _require_case_count(rows, expected_cases)
    record_to_sample = _resolve(spec.record_to_sample)
    template: str | None = None if spec.prompt_template is None else _resolve(spec.prompt_template)
    choice_template: str | None = (
        None if spec.choice_template is None else _resolve(spec.choice_template)
    )
    system_text: str | None = _resolved_system_text(spec)
    ordered: list[dict[str, Any]] = list(rows)
    if spec.shuffle_seed is not None:
        random.Random(spec.shuffle_seed).shuffle(ordered)
    samples: list[Sample] = _converted_samples(ordered, record_to_sample)
    if spec.choice_shuffle_seed is not None:
        _shuffle_choices(samples, spec.choice_shuffle_seed)
    cases: list[dict[str, Any]] = []
    targets: dict[int, dict[str, Any]] = {}
    for case_id, sample in enumerate(samples, start=1):
        target, choices = _validated_target(sample, case_id)
        input_text: str = _prompt(sample, choices, template, choice_template)
        if system_text is not None:
            # Named deviation (contracteval pattern): the eval's SYSTEM
            # instruction becomes the input's leading text, render untouched.
            input_text = f"{system_text}\n\n{input_text}"
        # WHY "case_id" beside "id": the board's url4 protocol template reads
        # $item.case_id per Case (the transport contract's string spelling);
        # "id" is the integer the engine's row/target files key on.
        cases.append(
            {
                "id": case_id,
                "case_id": str(case_id),
                "input": input_text,
            }
        )
        targets[case_id] = (
            {"target": target} if choices is None else {"target": target, "choices": choices}
        )
    return _emit(cases, targets, out, dataset_revision=spec.dataset_revision)


def _converted_samples(ordered: list[dict[str, Any]], record_to_sample: Any) -> list[Sample]:
    """Stage 3 — every row through the eval's own conversion, failing by case number."""

    samples: list[Sample] = []
    for case_id, row in enumerate(ordered, start=1):
        try:
            samples.append(record_to_sample(row))
        except Exception as exc:  # noqa: BLE001 — WHY broad: the conversion is eval
            # code over an untrusted row; ANY raise must fail the bake by case number.
            raise PrepareError(
                f"case {case_id}: record_to_sample refused the row ({type(exc).__name__}: {exc})"
            ) from exc
    return samples


def _shuffle_choices(samples: list[Sample], seed: int) -> None:
    """Stage 4 — pin each case's choice order with inspect's OWN shuffle, in place.

    WHY the whole dataset at once: ``MemoryDataset.shuffle_choices`` draws every
    sample's permutation (and target-letter remap) from ONE ``random.Random(seed)``
    stream, so each case's order depends on its position — shuffling per case
    would bake a different exam than the eval family produces for this seed.
    """

    from inspect_ai.dataset import MemoryDataset

    try:
        MemoryDataset(samples).shuffle_choices(seed=seed)
    except Exception as exc:  # noqa: BLE001 — WHY broad: the shuffle runs inspect's
        # letter remap over eval-produced Samples; ANY raise (a non-letter target
        # hitting ord(), an out-of-range letter) must surface as the bake's own
        # named refusal, never a raw TypeError/KeyError (review finding on PR #1031).
        raise PrepareError(
            f"choice shuffle refused the dataset ({type(exc).__name__}: {exc}) — "
            "a sample's target/choices do not fit inspect's letter remap"
        ) from exc


def _resolved_system_text(spec: SnapshotSpec) -> str | None:
    """The eval's system instruction as leading input text, or None without one.

    WHY stripped once here: eval constants often carry framing newlines
    (hellaswag's SYSTEM_MESSAGE); the leading text must join the render with
    exactly one blank line. A non-string resolution (a mispointed reference
    landing on a function) refuses the bake — str() would silently bake its
    repr into every case of the exam (review finding on PR #1018).
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


def prepare_snapshot(spec: SnapshotSpec, out: Path) -> dict[str, Any]:
    """Snapshot one board's pinned HF split and bake its assets (build time only)."""

    rows: list[dict[str, Any]] = _load_rows(spec)
    return emit_snapshot(spec, rows, out, expected_cases=spec.case_count)


def _prompt(
    sample: Sample,
    choices: list[str] | None,
    template: str | None,
    choice_template: str | None,
) -> str:
    """Stage 4 — the render is derived from the Sample's own shape, never per board."""

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


def _validated_target(sample: Sample, case_id: int) -> tuple[str, list[str] | None]:
    """The one trust boundary on eval-produced Samples — never bake an unkeyed Case."""

    if not isinstance(sample.input, str) or not sample.input.strip():
        raise PrepareError(f"case {case_id}: sample input is empty or not text")
    target: object = sample.target
    if not isinstance(target, str) or not target.strip():
        raise PrepareError(f"case {case_id}: sample target is empty or not text")
    if sample.choices is None:
        return target, None
    choices: list[str] = [str(choice) for choice in sample.choices]
    if not choices or any(not choice.strip() for choice in choices):
        raise PrepareError(f"case {case_id}: sample carries an empty choice")
    letters: str = "".join(chr(ord("A") + index) for index in range(len(choices)))
    if target not in letters:
        raise PrepareError(
            f"case {case_id}: target {target!r} is not a letter within {len(choices)} choices"
        )
    return target, choices


def _require_case_count(rows: list[dict[str, Any]], expected: int | None) -> None:
    """Refuse a wrong-sized bake — a config/revision typo must never ship a smaller exam.

    WHY: the row count is part of the exam's identity (the pinned CASE_COUNT rides the
    revision hash); an upstream change or a wrong split silently yielding 0 or N±k rows
    would bake a DIFFERENT exam with a green build.
    """

    if expected is not None and len(rows) != expected:
        raise PrepareError(f"dataset yielded {len(rows)} rows, pinned case count is {expected}")


def _emit(
    cases: list[dict[str, Any]],
    targets: dict[int, dict[str, Any]],
    out: Path,
    *,
    dataset_revision: str,
) -> dict[str, Any]:
    targets_dir: Path = out / "targets"
    # WHY refuse a dirty out: a re-bake into a used directory would leave orphan
    # targets/*.json from a previous, larger bake — the image build always starts
    # fresh, and this makes that assumption loud instead of silent.
    if (out / "cases.json").exists() or (targets_dir.is_dir() and any(targets_dir.iterdir())):
        raise PrepareError(f"refusing to bake into non-empty directory {out}")
    targets_dir.mkdir(parents=True, exist_ok=True)
    for case_id, record in targets.items():
        (targets_dir / f"{case_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    (out / "cases.json").write_text(
        json.dumps(cases, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return {"cases": len(cases), "dataset_revision": dataset_revision, "out": str(out)}


def _load_rows(spec: SnapshotSpec) -> list[dict[str, Any]]:
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
        # `datasets` — refuse the bake by name instead (OME-1264 extension 2).
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
    "SNAPSHOTS",
    "SnapshotSpec",
    "emit_snapshot",
    "mcq_prompt",
    "prepare_snapshot",
    "templated_prompt",
]
