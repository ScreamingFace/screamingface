# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Which revisions OME-1642 moves — and which it must not.

The failure policy is Benchmark identity (spec R6): a `withhold` score is a different number
from the same answers, so every `withhold` Benchmark gets a new revision and its old and new
scores never share a board. A `coverage_declare` Benchmark scores exactly as before, so its
revision stays byte-identical. Both tables are the revisions served on origin/main cbce4b202
(2026-10-19), the last commit before the change.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks.medxpert.definition import MEDXPERT  # noqa: E402
from screamingface_engine_inspect.benchmarks import BENCHMARKS, imported_benchmark  # noqa: E402


def _revision(key: str) -> str:
    return MEDXPERT.revision if key == "medxpert" else imported_benchmark(key).benchmark.revision


def _policy(key: str) -> str:
    if key == "medxpert":
        return MEDXPERT.declaration.failure_policy
    return imported_benchmark(key).benchmark.declaration.failure_policy


#: The 17 coverage_declare Benchmarks: unchanged revision, as served before OME-1642.
_KEPT: dict[str, str] = {
    "air_bench": "b5d90afe0f368dab",
    "arc_agi_2": "4f831492ca42fdf4",
    "coconot_contrast": "0eff77619697954b",
    "coconot_original": "0c4d77a9254ebc29",
    "contracteval": "890889e5b2863be4",
    "cyse4_mitre_frr": "0d6a53f259f81eff",
    "draco": "c6fb6f500dc58622",
    "draco-3pass": "e8c3ad925dcd4d4a",
    "fortress_benign": "b04be10a93356ccd",
    "healthbench-professional": "d8fb037307f35415",
    "healthbench-worst30": "39cfd96b068f7230",
    "ifeval": "1cba769ece27f7ef",
    "simpleqa": "ffd3e901b78f9d0e",
    "simpleqa_verified": "f2b42ba095cade8e",
    "strong_reject": "6794ed308fafe0a6",
    "xstest_safe": "1044036b2049e623",
    "xstest_unsafe": "fad9dd3ebabd84a5",
}

#: The 61 withhold Benchmarks: the revision each served BEFORE OME-1642, which it must
#: no longer serve.
_MOVED_FROM: dict[str, str] = {
    "agieval_aqua_rat": "878ad44393d431a4",
    "agieval_logiqa_en": "2e1f1c960caa7a0f",
    "agieval_lsat_ar": "017a3493849e9bf3",
    "agieval_lsat_lr": "633ce0a2c3f1e4fa",
    "agieval_lsat_rc": "d15fdabe16971db5",
    "agieval_sat_en": "0dd4b206f7f3787b",
    "agieval_sat_en_without_passage": "05d42ff073975ee3",
    "agieval_sat_math": "71f3e7b2ddfa58e9",
    "aime24": "d958c058e3f67e44",
    "aime25": "c637b487988d0753",
    "aime26": "3911b4aa84b0f731",
    "arc_challenge": "b54aa46de0840b60",
    "arc_easy": "5f063684bf708ca1",
    "bbeh": "9ad134d74b1574ef",
    "bbq": "9df63a8c954c961d",
    "boolq": "d29adda5bb6a246c",
    "commonsense_qa": "c133584254776a5e",
    "cybermetric_10000": "1174c252ffaebfab",
    "cybermetric_2000": "4d53683a812ef2c5",
    "cybermetric_500": "9ff30cf33ee155e4",
    "cybermetric_80": "6cfebaf54236f398",
    "frames_oracle": "eb27d52bf8431b07",
    "frontierscience": "fb33b1e6a2cf0c12",
    "gdpval-text": "2e839377e3ee28d4",
    "gsm8k": "330615c3213bb681",
    "hellaswag": "c98211d79bcab080",
    "infinite_bench_math_find": "16df28a909f03949",
    "lab_bench_cloning_scenarios": "6edd96369e7edf26",
    "lab_bench_dbqa": "4c1fd2e4909e49b3",
    "lab_bench_litqa": "dd9d5d13246dd76e",
    "lab_bench_protocolqa": "d4f1147ddcf10a00",
    "lab_bench_seqqa": "c937ddbf95ef87f9",
    "lab_bench_suppqa": "4f7adf70164e369f",
    "math": "1963559fac28e4a1",
    "medqa": "bb43303a4d091f91",
    "medxpert": "791a7d5b2e961f1c",
    "mgsm_en": "e96465d3247b9658",
    "mmlu": "1e42325597dee3d6",
    "mmlu_pro": "05aaa663ac69d943",
    "musique": "9ba23547b22e70ff",
    "musr": "335aca22d85fd610",
    "onet_m6": "3e171cd4f7e9b770",
    "paws": "866ee57e62d10a88",
    "piqa": "8a6628548da85c3d",
    "pre_flight": "ec859111af790871",
    "pubmedqa": "437d093493558d75",
    "race_h": "5ca6b26990c19643",
    "sad_facts_human_defaults": "0a90cd743e4e33a7",
    "sad_facts_llms": "6e0763d561439f9a",
    "sad_influence": "c6124a6e15dcdef7",
    "sad_stages_full": "a548998184f8fe54",
    "sad_stages_oversight": "ad42c0f4e66ad0cf",
    "sevenllm_mcq_en": "c8ef9b7c8db97e9a",
    "sevenllm_mcq_zh": "a8177911cb41f07e",
    "squad": "d0075817a5457cfb",
    "uccb": "c00d690b97fc6d5e",
    "winogrande": "07e46e0177ff0cb9",
    "wmdp_bio": "8b36af2e74e0c6d5",
    "wmdp_chem": "297614ecae016baa",
    "wmdp_cyber": "64c7e14444d0a4b5",
    "worldsense": "e30c575f1b740fae",
}


@pytest.mark.parametrize(("key", "revision"), sorted(_KEPT.items()))
def test_a_coverage_declare_benchmark_keeps_its_revision(key: str, revision: str) -> None:
    assert _policy(key) == "coverage_declare"
    assert _revision(key) == revision


@pytest.mark.parametrize(("key", "old_revision"), sorted(_MOVED_FROM.items()))
def test_a_withhold_benchmark_moves_off_its_old_revision(key: str, old_revision: str) -> None:
    assert _policy(key) == "withhold"
    assert _revision(key) != old_revision


def test_no_withhold_row_pins_a_published_revision() -> None:
    """A pinned `published_revision` wins over the fingerprint, so a withhold row that pinned
    one would keep its old revision and mix old and new scores on one board."""

    pinned: list[str] = [
        spec.key
        for spec in BENCHMARKS
        if spec.failure_policy == "withhold" and spec.published_revision is not None
    ]
    assert pinned == []
