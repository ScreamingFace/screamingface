# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on, and with the extra installed
# these imports type-check normally.
"""Prepare the imported benchmarks' assets: public prompts and private Grading Material.

Run at IMAGE BUILD time, never at run time (OME-925): a Job's rootfs is read-only and
holds no HuggingFace credential, so every artifact exists before a run starts. Every
fetch happens here, at the declaration's pinned commits, and the Case Digest seals what it
produced; upstream gating or drift cannot change a published benchmark.

Emits, per benchmark::

    <out>/cases.json         [{"id", "case_id", "input"}] — ALL a client sees
    <out>/targets/<id>.json  {"target": ..., "choices": [...]?} — private; read by the
                             aggregate (the scorer adapter's grading material) and the
                             draft-feedback offer

ONE path serves every Imported Benchmark since OME-1460: a benchmark is a
:class:`TaskReplayCasesSpec` DATA entry in :data:`TASK_REPLAY_CASES`, and Case Preparation
calls the eval's own task function (task_replay.py) with the declaration's Hub commits and
seeds forced; capture renders each Sample through the Task's own solvers. Nothing here
reimplements inspect, so an Imported Benchmark's content is exactly what the eval sends.
Importing another eval means adding one declaration, zero new functions.

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
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

from screamingface_engine.benchmarks.deployment import BenchmarkAssetPreparationError

if TYPE_CHECKING:
    from inspect_ai.dataset import Sample


class PrepareError(BenchmarkAssetPreparationError):
    """The build refuses to prepare these assets. Always says which row and why."""


#: The build-time switch that lets a PR build skip gated benchmarks instead of failing.
SKIP_BENCHMARKS_NEEDING_HF_TOKEN_ENV = "SCREAMINGFACE_SKIP_BENCHMARKS_NEEDING_HF_TOKEN"

#: Written into a skipped gated bundle, so the runtime can say WHY the benchmark has no
#: questions instead of a bare "cases are unavailable" (review on PR #1112).
SKIPPED_MARKER = "SKIPPED"

#: One prepared Case as the writer writes it: the public ``case`` row of ``cases.json``
#: and its private ``grading_material`` record (``targets/<id>.json``).
type PreparedCase = dict[str, dict[str, Any]]


#: Where inspect's own scorers live (match, choice, model_graded_qa, …). None of them reads
#: the Sample metadata (D11), and every one that grades without a judge compares the reply
#: against the answer key (R19). The one spelling both rules check.
INSPECT_SCORER_PREFIX: str = "inspect_ai.scorer:"

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
    #: A NAMED DEVIATION: upstream Sample ids (``str(Sample.id)``)
    #: dropped after the task builds its dataset and before capture (sad_stages_full: three
    #: Samples with an empty question). Every id must still be there, or Case Preparation
    #: refuses; ``case_count`` is the count kept. The row says why beside the ids, and they
    #: ride Benchmark identity when set (spec R18).
    excluded_sample_ids: tuple[str, ...] | None = None
    #: The dataset license, from the Hugging Face card when the one Case Source has one and
    #: it is on the cleared list, otherwise the owner's decision replacing LICENSE_TODO in
    #: the diff (spec R6, R7).
    license: str = LICENSE_TODO
    #: Hub repo id → 40-hex commit, one per Hugging Face Case Source. Every replay forces
    #: these onto the eval's Hub fetches and refuses a fetch with no pin, so each build
    #: reads the same commit (OME-1460, R2, R6). They ride Benchmark identity when set (R7).
    source_pins: dict[str, str] = field(default_factory=dict)
    #: The seed forced onto an ``hf_dataset`` row shuffle the eval makes without one, and
    #: the one for a bare ``shuffle_choices=True`` (D1). No identity pin: the Case Digest
    #: seals the order they produce (R7).
    shuffle_seed: int | None = None
    choice_shuffle_seed: int | None = None
    #: The dataset is gated, so replaying it needs a Hugging Face token from an account that
    #: accepted its terms (xstest); access, not identity, so no pin (R8).
    needs_hf_token: bool = False


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


#: Every Imported Benchmark's Case Preparation, keyed by Benchmark key. Importing another
#: eval = one more entry, written by the importer above the anchor at the end.
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
        # Hub pin backfilled from the commit recorded at import (OME-1460, D4): every
        # build now forces it; the eval already passes the same commit.
        source_pins={
            "bigbio/med_qa": "ddef95d268cdad413693d634279a9a679d468469",
        },
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
        # Hub pin backfilled from the commit recorded at import (OME-1460, D4): every
        # build now forces it; the eval already passes the same commit.
        source_pins={
            "heegyu/bbq": "5d6faae52070aa5eb71b46d1c0723d3ba7930209",
        },
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
        # Hub pin backfilled from the commit recorded at import (OME-1460, D4): every
        # build now forces it; the eval already passes the same commit.
        source_pins={
            "ybisk/piqa": "2e8ac2dffd59bac8c3c6714948f4c551a0848bb0",
        },
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
    # sad_stages_full — imported by Task replay on 2026-10-05 from
    #   inspect_evals.sad.sad:sad_stages_full.
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
    "sad_stages_full": TaskReplayCasesSpec(
        task="inspect_evals.sad.sad:sad_stages_full",
        task_args={"seed": 7},
        case_count=797,
        case_digest="a5d0851ddeee6f85a4ac3f911245c2b37fdb2a20f305a9259846c011c1bc0385",
        keep_sample_metadata=True,
        # NAMED DEVIATION (spec R18): upstream's records 15, 59 and 103 of the stages/full
        # batch files have an empty body, so the eval asks "In what stage … the above text?"
        # about no text at all, and the Case boundary never prepares a Case with nothing to
        # ask. inspect keeps them; this Benchmark leaves them out, 797 of 800. The ids do not
        # depend on the seed (the loader numbers records in file order).
        excluded_sample_ids=(
            "stages_full:14",
            "stages_full:58",
            "stages_full:102",
        ),
        # License: owner decision 2026-10-01: CC-BY-4.0, LRudL/sad LICENSE; no dataset card.
        license="cc-by-4.0",
    ),
    # cyse4_mitre_frr — imported by Task replay on 2026-10-05 from
    #   inspect_evals.cyberseceval_4.mitre_frr.task:cyse4_mitre_frr.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   url https://raw.githubusercontent.com/meta-llama/PurpleLlama/fe05293b610dabc3967443f2dd4dc35c4e8971b6/CybersecurityBenchmarks/datasets/mitre_frr/mitre_frr.json
    #     pin commit fe05293b610dabc3967443f2dd4dc35c4e8971b6
    "cyse4_mitre_frr": TaskReplayCasesSpec(
        task="inspect_evals.cyberseceval_4.mitre_frr.task:cyse4_mitre_frr",
        case_count=750,
        case_digest="d62289a80a9e7cc067ed73b3cf8790009f16fcf3c9b2a0bdda3399e5d4990f3d",
        keep_sample_metadata=True,
        # The Samples carry no answer key: the eval's own scorer reads only the reply (a
        # refusal regex), so the row opts out of the key and its catalogue row says who
        # grades without one (spec R19).
        has_answer_key=False,
        # License: owner decision 2026-10-05: MIT, as the eval's code states for
        # PurpleLlama ("Copyright (c) Meta Platforms, Inc. and affiliates., MIT License");
        # no dataset card. Upstream publishes no sha256 for this file: the commit in the
        # URL and the Case Digest are its pins.
        license="mit",
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
        # Hub pin backfilled from the commit recorded at import (OME-1460, D4): every
        # build now forces it; the eval already passes the same commit.
        source_pins={
            "AirsideLabs/pre-flight-06": "439d2d118fed7d9b009c1f87b9eb1205ab94766e",
        },
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
        # Hub pin backfilled from the commit recorded at import (OME-1460, D4): every
        # build now forces it; the eval already passes the same commit.
        source_pins={
            "BBEH/bbeh": "08e07a803851822c04399782ece3c4a07ce419f9",
        },
    ),
    # arc_easy — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.arc.arc:arc_easy.
    # Fold: Cases identical to the Hugging Face path's.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face allenai/ai2_arc/ARC-Easy
    #     pin revision 210d026faf9955653af8916fad021475a3f00453
    "arc_easy": TaskReplayCasesSpec(
        task="inspect_evals.arc.arc:arc_easy",
        case_count=2376,
        case_digest="51b8598a4db653d7c60ec0a43487d4c5a3ea0daf505316c3b6f9a5d6fd656346",
        source_pins={
            "allenai/ai2_arc": "210d026faf9955653af8916fad021475a3f00453",
        },
        license="cc-by-sa-4.0",
    ),
    # arc_challenge — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.arc.arc:arc_challenge.
    # Fold: Cases identical to the Hugging Face path's.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face allenai/ai2_arc/ARC-Challenge
    #     pin revision 210d026faf9955653af8916fad021475a3f00453
    "arc_challenge": TaskReplayCasesSpec(
        task="inspect_evals.arc.arc:arc_challenge",
        case_count=1172,
        case_digest="71c66b3e10dcccf112dc4951676c83d62bb50d8055bad6e0494d6e5181880cfe",
        source_pins={
            "allenai/ai2_arc": "210d026faf9955653af8916fad021475a3f00453",
        },
        license="cc-by-sa-4.0",
    ),
    # wmdp_bio — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.wmdp.wmdp:wmdp_bio.
    # Fold: Cases identical to the Hugging Face path's.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face cais/wmdp/wmdp-bio
    #     pin revision 7125571f22f032c56415e7980f48d877dd830ff8
    "wmdp_bio": TaskReplayCasesSpec(
        task="inspect_evals.wmdp.wmdp:wmdp_bio",
        case_count=1273,
        case_digest="f36e89dd2551294dd4abdcb223262644ff9a4bb04ca69b8b07e993a673ad02aa",
        source_pins={
            "cais/wmdp": "7125571f22f032c56415e7980f48d877dd830ff8",
        },
        license="mit",
    ),
    # wmdp_chem — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.wmdp.wmdp:wmdp_chem.
    # Fold: Cases identical to the Hugging Face path's.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face cais/wmdp/wmdp-chem
    #     pin revision 7125571f22f032c56415e7980f48d877dd830ff8
    "wmdp_chem": TaskReplayCasesSpec(
        task="inspect_evals.wmdp.wmdp:wmdp_chem",
        case_count=408,
        case_digest="78fd64d8416db768091c674f665dbdd7c964dabbbeb30658690959620174103d",
        source_pins={
            "cais/wmdp": "7125571f22f032c56415e7980f48d877dd830ff8",
        },
        license="mit",
    ),
    # wmdp_cyber — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.wmdp.wmdp:wmdp_cyber.
    # Fold: Cases identical to the Hugging Face path's.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face cais/wmdp/wmdp-cyber
    #     pin revision 7125571f22f032c56415e7980f48d877dd830ff8
    "wmdp_cyber": TaskReplayCasesSpec(
        task="inspect_evals.wmdp.wmdp:wmdp_cyber",
        case_count=1987,
        case_digest="fcb59e16ad49985fa62beb40d8b82d50ee777855d82ca6a25bc5455b2bb1981f",
        source_pins={
            "cais/wmdp": "7125571f22f032c56415e7980f48d877dd830ff8",
        },
        license="mit",
    ),
    # pubmedqa — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.pubmedqa.pubmedqa:pubmedqa.
    # Fold: Cases identical to the Hugging Face path's.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face qiaojin/PubMedQA/pqa_labeled
    #     pin revision 9001f2853fb87cab8d220904e0de81ac6973b318
    "pubmedqa": TaskReplayCasesSpec(
        task="inspect_evals.pubmedqa.pubmedqa:pubmedqa",
        case_count=500,
        case_digest="482998340464f3bf8e35502be4f83dc8fcefa64f6d2eb35d101bac84e1e48f77",
        source_pins={
            "qiaojin/PubMedQA": "9001f2853fb87cab8d220904e0de81ac6973b318",
        },
        license="mit",
    ),
    # gsm8k — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.gsm8k.gsm8k:gsm8k.
    # Fold: Cases identical to the Hugging Face path's at fewshot=0 (D2).
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face openai/gsm8k
    #     pin revision cc7b047b6e5bb11b4f1af84efc572db110a51b3c
    "gsm8k": TaskReplayCasesSpec(
        task="inspect_evals.gsm8k.gsm8k:gsm8k",
        task_args={"fewshot": 0},
        case_count=1319,
        case_digest="11e0dccbf379586a9618b98200c02ef98fc9a30d426e6f36423f420982637e8f",
        source_pins={
            "openai/gsm8k": "cc7b047b6e5bb11b4f1af84efc572db110a51b3c",
        },
        license="mit",
    ),
    # winogrande — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.winogrande.winogrande:winogrande.
    # Fold: Cases identical to the Hugging Face path's at fewshot=0 (D2).
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face allenai/winogrande/winogrande_xl
    #     pin revision 01e74176c63542e6b0bcb004dcdea22d94fb67b5
    "winogrande": TaskReplayCasesSpec(
        task="inspect_evals.winogrande.winogrande:winogrande",
        task_args={"fewshot": 0},
        case_count=1267,
        case_digest="437ab435a55b3959660977aef0a0ed17eb45919a475dfd43ffd94362c2b71f67",
        source_pins={
            "allenai/winogrande": "01e74176c63542e6b0bcb004dcdea22d94fb67b5",
        },
        # License: owner decision 2026-10-06: CC-BY per the
        #  github.com/allenai/winogrande README (no version stated, read as 4.0).
        license="cc-by-4.0",
    ),
    # mmlu — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.mmlu.mmlu:mmlu_0_shot.
    # Fold: inspect's own seeded order (seed=42), and 105 duplicate questions dropped as
    #   inspect drops them.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face cais/mmlu/all
    #     pin revision c30699e8356da336a370243923dbaf21066bb9fe
    "mmlu": TaskReplayCasesSpec(
        task="inspect_evals.mmlu.mmlu:mmlu_0_shot",
        case_count=13937,
        case_digest="ea69cb0179c201b4e138eed2f2c21f653f9d0f11e6a2f88812de0143b8930a34",
        source_pins={
            "cais/mmlu": "c30699e8356da336a370243923dbaf21066bb9fe",
        },
        license="mit",
    ),
    # aime24 — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.aime2024.aime2024:aime2024.
    # Fold: same Cases, in the Hub's order: the eval never shuffles; ours was policy.
    #   Grading Material now also keeps each Sample's metadata, as for every eval-own scorer
    #   (D11); the scorer reads none of it, so grading is unchanged.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face Maxwell-Jia/AIME_2024
    #     pin revision 8d88b2876a82a080e2f172cc9b25d0d9d2cb4792
    "aime24": TaskReplayCasesSpec(
        task="inspect_evals.aime2024.aime2024:aime2024",
        case_count=30,
        case_digest="2f8cbd5ab7aa8d31f8ffd8e7a10e27a6ea08de6d552e7b6b95d9720ca83a0321",
        keep_sample_metadata=True,
        source_pins={
            "Maxwell-Jia/AIME_2024": "8d88b2876a82a080e2f172cc9b25d0d9d2cb4792",
        },
        license="mit",
    ),
    # aime25 — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.aime2025.aime2025:aime2025.
    # Fold: same Cases, in the Hub's order: the eval never shuffles; ours was policy.
    #   Grading Material now also keeps each Sample's metadata, as for every eval-own scorer
    #   (D11); the scorer reads none of it, so grading is unchanged.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face math-ai/aime25
    #     pin revision 563bb8404243c5f09de6ec262f2db674fe5bce9b
    "aime25": TaskReplayCasesSpec(
        task="inspect_evals.aime2025.aime2025:aime2025",
        case_count=30,
        case_digest="200b95b0f1b1542b280795e6143c0aa066784788cb5056239def5b89c1c5eabe",
        keep_sample_metadata=True,
        source_pins={
            "math-ai/aime25": "563bb8404243c5f09de6ec262f2db674fe5bce9b",
        },
        license="apache-2.0",
    ),
    # hellaswag — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.hellaswag.hellaswag:hellaswag.
    # Fold: the Hub's order (ours was policy); each input keeps the leading newline its
    #   system message starts with.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face Rowan/hellaswag
    #     pin revision 218ec52e09a7e7462a5400043bb9a69a41d06b76
    "hellaswag": TaskReplayCasesSpec(
        task="inspect_evals.hellaswag.hellaswag:hellaswag",
        case_count=10042,
        case_digest="13d0a551dc717a7b6aad29674a9b875a47b09a6d869ea36cce7da34900632827",
        source_pins={
            "Rowan/hellaswag": "218ec52e09a7e7462a5400043bb9a69a41d06b76",
        },
        # License: owner decision 2026-09-22: MIT per github.com/rowanz/hellaswag;
        #  the Hub card carries no licence tag.
        license="mit",
    ),
    # xstest_safe — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.xstest.xstest:xstest.
    # Fold: same Cases and ids; inputs gain the eval's system message (D3).
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face walledai/XSTest
    #     pin revision f1d713187c61b6ae64e602d74f0b3d812cc2e8e8
    "xstest_safe": TaskReplayCasesSpec(
        task="inspect_evals.xstest.xstest:xstest",
        task_args={"subset": "safe"},
        case_count=250,
        case_digest="6800b16845a272bd27552f57ebc3798f3f3567ea67907e6132e69c9a4e1c13b7",
        has_answer_key=False,
        source_pins={
            "walledai/XSTest": "f1d713187c61b6ae64e602d74f0b3d812cc2e8e8",
        },
        needs_hf_token=True,
        license="cc-by-4.0",
    ),
    # xstest_unsafe — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.xstest.xstest:xstest.
    # Fold: same Cases and ids; inputs gain the eval's system message (D3).
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face walledai/XSTest
    #     pin revision f1d713187c61b6ae64e602d74f0b3d812cc2e8e8
    "xstest_unsafe": TaskReplayCasesSpec(
        task="inspect_evals.xstest.xstest:xstest",
        task_args={"subset": "unsafe"},
        case_count=200,
        case_digest="ecdd47957876ff2e5354b76c45eedbfece6c7ea875f3c8d3c43a7b01f056ec86",
        has_answer_key=False,
        source_pins={
            "walledai/XSTest": "f1d713187c61b6ae64e602d74f0b3d812cc2e8e8",
        },
        needs_hf_token=True,
        license="cc-by-4.0",
    ),
    # coconot_original — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.coconot.coconot:coconot.
    # Fold: Cases identical to the Hugging Face path's.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face allenai/coconot/original
    #     pin revision 2cbe16aabf9069f17e48c8daad8aeabc29469eb7
    "coconot_original": TaskReplayCasesSpec(
        task="inspect_evals.coconot.coconot:coconot",
        task_args={"subset": "original"},
        case_count=1001,
        case_digest="64ec2519afb9052a577a81ef4fbe365d58d02de47298ed7746a76dc636e82ec3",
        # WHY kept although the scorer is inspect's: the Judge template reads the category
        # rubric from the metadata (OME-1371); imported with --keep-sample-metadata.
        keep_sample_metadata=True,
        has_answer_key=False,
        source_pins={
            "allenai/coconot": "2cbe16aabf9069f17e48c8daad8aeabc29469eb7",
        },
        # License: owner decision 2026-10-01 (OME-1371): ODC-BY, the dataset
        #  card's Licensing Information.
        license="odc-by",
    ),
    # coconot_contrast — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.coconot.coconot:coconot.
    # Fold: Cases identical to the Hugging Face path's.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face allenai/coconot/contrast
    #     pin revision 2cbe16aabf9069f17e48c8daad8aeabc29469eb7
    "coconot_contrast": TaskReplayCasesSpec(
        task="inspect_evals.coconot.coconot:coconot",
        task_args={"subset": "contrast"},
        case_count=379,
        case_digest="1e8579eabe4c113b285e55ff09fd643a4fff424dda067068175a853aa5a39d23",
        # WHY kept although the scorer is inspect's: the Judge template reads the category
        # rubric from the metadata (OME-1371); imported with --keep-sample-metadata.
        keep_sample_metadata=True,
        has_answer_key=False,
        source_pins={
            "allenai/coconot": "2cbe16aabf9069f17e48c8daad8aeabc29469eb7",
        },
        # License: odc-by, as coconot_original (owner decision 2026-10-01).
        license="odc-by",
    ),
    # commonsense_qa — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.commonsense_qa.commonsense_qa:commonsense_qa.
    # Fold: same Cases; order forced by shuffle_seed through inspect's shuffle (D1).
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face tau/commonsense_qa
    #     pin revision 94630fe30dad47192a8546eb75f094926d47e155
    "commonsense_qa": TaskReplayCasesSpec(
        task="inspect_evals.commonsense_qa.commonsense_qa:commonsense_qa",
        case_count=1221,
        case_digest="0a4789cbd8e63a06f9d3d75a361538276bca39d4c45789715b9d9350bb3c1053",
        source_pins={
            "tau/commonsense_qa": "94630fe30dad47192a8546eb75f094926d47e155",
        },
        shuffle_seed=20260917,
        license="mit",
    ),
    # paws — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.paws.paws:paws.
    # Fold: same Cases; order forced by shuffle_seed through inspect's shuffle (D1).
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face google-research-datasets/paws/labeled_final
    #     pin revision 161ece9501cf0a11f3e48bd356eaa82de46d6a09
    "paws": TaskReplayCasesSpec(
        task="inspect_evals.paws.paws:paws",
        case_count=8000,
        case_digest="b0e17f7d59264fda8c48a489c8f990936ac97def157dc680713cc7d78d1381f8",
        source_pins={
            "google-research-datasets/paws": "161ece9501cf0a11f3e48bd356eaa82de46d6a09",
        },
        shuffle_seed=20260917,
        # License: owner decision 2026-10-06: Google's PAWS licence, "may be freely
        #  used for any purpose"; credit Google LLC as the data source (description).
        license="other",
    ),
    # boolq — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.boolq.boolq:boolq.
    # Fold: same Cases; order forced by shuffle_seed through inspect's shuffle (D1).
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face google/boolq
    #     pin revision 35b264d03638db9f4ce671b711558bf7ff0f80d5
    "boolq": TaskReplayCasesSpec(
        task="inspect_evals.boolq.boolq:boolq",
        case_count=3270,
        case_digest="71ee1e88969337159eedfe47c6c3af66816b01eb984d338f36deed56685fd3e2",
        source_pins={
            "google/boolq": "35b264d03638db9f4ce671b711558bf7ff0f80d5",
        },
        shuffle_seed=20260917,
        # License: CC-BY-SA-3.0 per the Hub card, carried over from the Hugging
        #  Face-path row (OME-1460); not on the cleared list, owner to confirm.
        license="cc-by-sa-3.0",
    ),
    # mmlu_pro — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.mmlu_pro.mmlu_pro:mmlu_pro.
    # Fold: same Cases; order forced by shuffle_seed through inspect's shuffle (D1).
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face TIGER-Lab/MMLU-Pro
    #     pin revision 527feea0afed1de15a8c115abf7be4c912123315
    "mmlu_pro": TaskReplayCasesSpec(
        task="inspect_evals.mmlu_pro.mmlu_pro:mmlu_pro",
        case_count=12032,
        case_digest="b765c667c3ad277a8bd49c388fcf26dc4abc2dcaacd34ac43f05e94cad611426",
        source_pins={
            "TIGER-Lab/MMLU-Pro": "527feea0afed1de15a8c115abf7be4c912123315",
        },
        shuffle_seed=20260917,
        license="mit",
    ),
    # race_h — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.race_h.race_h:race_h.
    # Fold: same Cases; order forced by shuffle_seed through inspect's shuffle (D1).
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face ehovy/race/high
    #     pin revision 2fec9fd81f1dc971569a9b729c43f2f0e6436637
    "race_h": TaskReplayCasesSpec(
        task="inspect_evals.race_h.race_h:race_h",
        case_count=3498,
        case_digest="49e1ebc1ebbefe9569375bf666659f1a1d3ae1f309880fcf350875550c330441",
        source_pins={
            "ehovy/race": "2fec9fd81f1dc971569a9b729c43f2f0e6436637",
        },
        shuffle_seed=20260917,
        # License: owner decision 2026-10-06: CMU's RACE terms, non-commercial
        #  research only; credit and link www.cs.cmu.edu/~glai1/data/race/ (description).
        license="non-commercial-research-only",
    ),
    # frontierscience — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.frontierscience.frontierscience:frontierscience.
    # Fold: same Cases; order forced by shuffle_seed through inspect's shuffle (D1).
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face openai/frontierscience
    #     pin revision 25ed67db7da8f4591484e764008ff585544f5a30
    "frontierscience": TaskReplayCasesSpec(
        task="inspect_evals.frontierscience.frontierscience:frontierscience",
        case_count=160,
        case_digest="7f0ef5c2834d2c980458f67fbba3b2576a18f8c08ee669f355b922afedecc3ad",
        keep_sample_metadata=True,
        source_pins={
            "openai/frontierscience": "25ed67db7da8f4591484e764008ff585544f5a30",
        },
        shuffle_seed=20260923,
        license="apache-2.0",
    ),
    # onet_m6 — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.onet.onet:onet_m6.
    # Fold: same Cases; order forced by shuffle_seed through inspect's shuffle (D1).
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face matichon/thai-onet-m6-exam/default
    #     pin revision 93ffb5e3f3ec630b73e501937805984dd24f2365
    "onet_m6": TaskReplayCasesSpec(
        task="inspect_evals.onet.onet:onet_m6",
        case_count=391,
        case_digest="92d013fe6efd85165221d02958efaf13df3f31ee25ce4e8868112b92c30e613b",
        # NAMED DEVIATION (owner decision 2026-09-29, OME-1269): inspect keeps 397
        # questions, the Benchmark serves 391. Six cannot be graded as published: upstream
        # split their numbered choices wrongly, so the answer letter points past the last
        # choice (2021_4_b447: answer E, 4 choices).
        excluded_sample_ids=(
            "2019_10ข_6985",
            "2020_28_177b",
            "2020_43_b673",
            "2021_10_0325",
            "2021_13_1922",
            "2021_4_b447",
        ),
        source_pins={
            "matichon/thai-onet-m6-exam": "93ffb5e3f3ec630b73e501937805984dd24f2365",
        },
        shuffle_seed=7,
        license="apache-2.0",
    ),
    # musr — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.musr.musr:musr.
    # Fold: order forced by shuffle_seed through inspect's shuffle (D1); inputs gain the
    #   eval's system message (D3).
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face TAUR-Lab/MuSR
    #     pin revision 7c365b439a222150f317764d4f16ae6c96d7d94a
    "musr": TaskReplayCasesSpec(
        task="inspect_evals.musr.musr:musr",
        case_count=250,
        case_digest="fa7e1c77159eda64b06ec32238afe23ac0be8497bfcd500db46cd435e846204c",
        source_pins={
            "TAUR-Lab/MuSR": "7c365b439a222150f317764d4f16ae6c96d7d94a",
        },
        shuffle_seed=20260922,
        license="cc-by-4.0",
    ),
    # lab_bench_litqa — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.lab_bench.lab_bench:lab_bench_litqa.
    # Fold: row and answer-option order forced by both seeds through inspect's shuffles (D1).
    #   Grading Material now also keeps each Sample's metadata, as for every eval-own scorer
    #   (D11); the scorer reads none of it, so grading is unchanged.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face futurehouse/lab-bench/LitQA2
    #     pin revision 5c77cec648430f30611808808861eb86f81d5eaa
    "lab_bench_litqa": TaskReplayCasesSpec(
        task="inspect_evals.lab_bench.lab_bench:lab_bench_litqa",
        case_count=199,
        case_digest="53c9f8077dcf1c9edfa52b1e426be95549dd3b8d9b72cffb9a21001c27417dfe",
        keep_sample_metadata=True,
        source_pins={
            "futurehouse/lab-bench": "5c77cec648430f30611808808861eb86f81d5eaa",
        },
        shuffle_seed=7,
        choice_shuffle_seed=7,
        license="cc-by-sa-4.0",
    ),
    # lab_bench_suppqa — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.lab_bench.lab_bench:lab_bench_suppqa.
    # Fold: row and answer-option order forced by both seeds through inspect's shuffles (D1).
    #   Grading Material now also keeps each Sample's metadata, as for every eval-own scorer
    #   (D11); the scorer reads none of it, so grading is unchanged.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face futurehouse/lab-bench/SuppQA
    #     pin revision 5c77cec648430f30611808808861eb86f81d5eaa
    "lab_bench_suppqa": TaskReplayCasesSpec(
        task="inspect_evals.lab_bench.lab_bench:lab_bench_suppqa",
        case_count=82,
        case_digest="5233348a35d4e988fd71f1741ded483b9d8ffae3a0e8979203fb6ab0e7aa90f9",
        keep_sample_metadata=True,
        source_pins={
            "futurehouse/lab-bench": "5c77cec648430f30611808808861eb86f81d5eaa",
        },
        shuffle_seed=7,
        choice_shuffle_seed=7,
        license="cc-by-sa-4.0",
    ),
    # lab_bench_dbqa — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.lab_bench.lab_bench:lab_bench_dbqa.
    # Fold: row and answer-option order forced by both seeds through inspect's shuffles (D1).
    #   Grading Material now also keeps each Sample's metadata, as for every eval-own scorer
    #   (D11); the scorer reads none of it, so grading is unchanged.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face futurehouse/lab-bench/DbQA
    #     pin revision 5c77cec648430f30611808808861eb86f81d5eaa
    "lab_bench_dbqa": TaskReplayCasesSpec(
        task="inspect_evals.lab_bench.lab_bench:lab_bench_dbqa",
        case_count=520,
        case_digest="8584a3df081501f949f28a03ff5b058208985ef653a98b88d9946b24e08be17b",
        keep_sample_metadata=True,
        source_pins={
            "futurehouse/lab-bench": "5c77cec648430f30611808808861eb86f81d5eaa",
        },
        shuffle_seed=7,
        choice_shuffle_seed=7,
        license="cc-by-sa-4.0",
    ),
    # lab_bench_protocolqa — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.lab_bench.lab_bench:lab_bench_protocolqa.
    # Fold: row and answer-option order forced by both seeds through inspect's shuffles (D1).
    #   Grading Material now also keeps each Sample's metadata, as for every eval-own scorer
    #   (D11); the scorer reads none of it, so grading is unchanged.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face futurehouse/lab-bench/ProtocolQA
    #     pin revision 5c77cec648430f30611808808861eb86f81d5eaa
    "lab_bench_protocolqa": TaskReplayCasesSpec(
        task="inspect_evals.lab_bench.lab_bench:lab_bench_protocolqa",
        case_count=108,
        case_digest="06f94fdd1c65c0872d6c6cde6afe35019a97e3ac40240771cebfa7fa022fc76f",
        keep_sample_metadata=True,
        source_pins={
            "futurehouse/lab-bench": "5c77cec648430f30611808808861eb86f81d5eaa",
        },
        shuffle_seed=7,
        choice_shuffle_seed=7,
        license="cc-by-sa-4.0",
    ),
    # lab_bench_seqqa — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.lab_bench.lab_bench:lab_bench_seqqa.
    # Fold: row and answer-option order forced by both seeds through inspect's shuffles (D1).
    #   Grading Material now also keeps each Sample's metadata, as for every eval-own scorer
    #   (D11); the scorer reads none of it, so grading is unchanged.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face futurehouse/lab-bench/SeqQA
    #     pin revision 5c77cec648430f30611808808861eb86f81d5eaa
    "lab_bench_seqqa": TaskReplayCasesSpec(
        task="inspect_evals.lab_bench.lab_bench:lab_bench_seqqa",
        case_count=600,
        case_digest="b11b60d26139ccf4d937cb48ddcaa84c5d931cb838e857c1cab0b4ff8ce89c0d",
        keep_sample_metadata=True,
        source_pins={
            "futurehouse/lab-bench": "5c77cec648430f30611808808861eb86f81d5eaa",
        },
        shuffle_seed=7,
        choice_shuffle_seed=7,
        license="cc-by-sa-4.0",
    ),
    # lab_bench_cloning_scenarios — re-imported by Task replay (OME-1460) on 2026-10-06 from
    #   inspect_evals.lab_bench.lab_bench:lab_bench_cloning_scenarios.
    # Fold: row and answer-option order forced by both seeds through inspect's shuffles (D1).
    #   Grading Material now also keeps each Sample's metadata, as for every eval-own scorer
    #   (D11); the scorer reads none of it, so grading is unchanged.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face futurehouse/lab-bench/CloningScenarios
    #     pin revision 5c77cec648430f30611808808861eb86f81d5eaa
    "lab_bench_cloning_scenarios": TaskReplayCasesSpec(
        task="inspect_evals.lab_bench.lab_bench:lab_bench_cloning_scenarios",
        case_count=33,
        case_digest="0e21d7411577ba5b2b946ffd81f89d7b63269e47303228992a1066a531ddf2c7",
        keep_sample_metadata=True,
        source_pins={
            "futurehouse/lab-bench": "5c77cec648430f30611808808861eb86f81d5eaa",
        },
        shuffle_seed=7,
        choice_shuffle_seed=7,
        license="cc-by-sa-4.0",
    ),
    # squad — imported by Task replay on 2026-10-07 from
    #   inspect_evals.squad.squad:squad.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face rajpurkar/squad_v2
    #     pin revision 3ffb306f725f7d2ce8394bc1873b24868140c412
    "squad": TaskReplayCasesSpec(
        task="inspect_evals.squad.squad:squad",
        task_args={"shuffle": False},
        case_count=11873,
        case_digest="1a56ec15f8b0ae3147ca5e000962e43894147afa03e226c54f22b98ddd19b29f",
        source_pins={
            "rajpurkar/squad_v2": "3ffb306f725f7d2ce8394bc1873b24868140c412",
        },
        license="cc-by-sa-4.0",
    ),
    # math — imported by Task replay on 2026-10-07 from
    #   inspect_evals.math.math:math.
    # Case Sources, as recorded at import (review them; the Case Digest pins them):
    #   hugging-face DigitalLearningGmbH/MATH-lighteval/default
    #     pin revision 0530c78699ea5e8eb5530600900e1f328b48acad
    "math": TaskReplayCasesSpec(
        task="inspect_evals.math.math:math",
        task_args={"shuffle": False, "fewshot": 0},
        case_count=5000,
        case_digest="4652e25e01f6da8ecf093e5ab8b1018de59a6a0ede205d12cab2e3adb10f2a8b",
        keep_sample_metadata=True,
        source_pins={
            "DigitalLearningGmbH/MATH-lighteval": "0530c78699ea5e8eb5530600900e1f328b48acad",
        },
        license="mit",
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


def prepared_case(
    sample: Sample, case_id: int, input_text: str, spec: TaskReplayCasesSpec
) -> PreparedCase:
    """One prepared Case from a Sample and its rendered input: the public row plus the
    private Grading Material, after the one validated boundary on eval-produced Samples.
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


def without_excluded_samples(excluded_ids: tuple[str, ...], samples: list[Sample]) -> list[Sample]:
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


def skip_without_hf_token(dataset: str, out: Path) -> dict[str, Any] | None:
    """The gated-dataset rule both preparation paths share: go on, skip, or refuse.

    With a token (``HF_TOKEN`` or a cached login) → None, and the caller prepares. Without
    one, a PR build that sets ``SCREAMINGFACE_SKIP_BENCHMARKS_NEEDING_HF_TOKEN=1`` writes the
    SKIPPED marker and returns the skip summary; INVARIANT: that summary never carries
    ``UNCONFIRMED_CASES_KEY``, so the strict PR image job stays green (F7). Any other build
    refuses by name, so a main or release image never ships missing a Benchmark.

    Args:
        dataset: what the reason names, e.g. ``walledai/XSTest``.
        out: the directory the Benchmark prepares into.

    Returns:
        None to go on; the skip summary when skipped.

    Raises:
        PrepareError: no token and no skip flag.
    """

    if _available_hf_token() is not None:
        return None
    if os.environ.get(SKIP_BENCHMARKS_NEEDING_HF_TOKEN_ENV) != "1":
        raise PrepareError(
            f"{dataset} is a gated Hugging Face dataset and no token is available — "
            "in CI, check the HF_TOKEN_BENCHMARKS repo secret; locally, export HF_TOKEN "
            "as a read-only token from an account that accepted the dataset's terms"
        )
    reason: str = f"gated dataset {dataset}, built without a Hugging Face token"
    print(
        f"WARNING: skipping {reason} ({SKIP_BENCHMARKS_NEEDING_HF_TOKEN_ENV}=1); "
        "this image has NO assets for its board",
        file=sys.stderr,
        flush=True,
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / SKIPPED_MARKER).write_text(reason + "\n", encoding="utf-8")
    return {"cases": 0, "skipped": reason, "out": str(out)}


def _resolve(reference: str) -> Any:
    """Resolve one ``"module:attr"`` spec reference into the eval's own object."""

    module_name, _, attribute = reference.partition(":")
    return getattr(import_module(module_name), attribute)


def _validated_list_key(target: list[Any], sample: Sample, case_id: int) -> list[str]:
    """A list of accepted answers as a Case's key: non-empty, every entry non-blank text,
    and never beside multiple-choice options (OME-1268)."""

    if not target:
        raise PrepareError(f"case {case_id}: sample target is empty or not text")
    if any(not isinstance(item, str) or not item.strip() for item in target):
        raise PrepareError(
            f"case {case_id}: a list target must hold only non-blank accepted answers"
        )
    if sample.choices is not None:
        raise PrepareError(
            f"case {case_id}: a list target beside choices is a multi-answer "
            "multiple-choice Case, which no Benchmark declares"
        )
    return list(target)


def _validated_answer_key(
    sample: Sample, case_id: int, has_answer_key: bool = True
) -> tuple[str | list[str], list[str] | None]:
    """The one trust boundary on eval-produced Samples — never prepare an unkeyed Case.

    ``has_answer_key=False`` (a judged benchmark whose judge never reads a key, or one
    graded by the eval's own scorer from the reply alone, R19) is the one place an empty
    answer key is accepted; the question itself is still required.

    FEATURE (OME-1268): a LIST of accepted answers (SQuAD's every accepted span) is a valid
    key on a free-text Case; it is frozen as the list inspect's own f1 and exact read, so
    the grading code is untouched. A list beside multiple-choice options is refused: that
    would be a multi-answer MCQ, which no row declares.
    """

    _require_a_question(sample, case_id)
    target: object = sample.target
    if not has_answer_key and target in ("", []) and sample.choices is None:
        return "", None
    key: str | list[str]
    if isinstance(target, list):
        key = _validated_list_key(target, sample, case_id)
    elif not isinstance(target, str) or not target.strip():
        raise PrepareError(f"case {case_id}: sample target is empty or not text")
    else:
        key = target
    if sample.choices is None:
        return key, None
    # A list key beside choices was refused above, so the key here is the one option's text.
    assert isinstance(target, str)
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


__all__ = [
    "PrepareError",
    "INSPECT_SCORER_PREFIX",
    "LICENSE_TODO",
    "PreparedCase",
    "TASK_REPLAY_CASES",
    "TaskReplayCasesSpec",
    "case_digest",
    "prepared_case",
    "without_excluded_samples",
]
