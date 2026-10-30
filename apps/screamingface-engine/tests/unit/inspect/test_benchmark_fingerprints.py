# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Every Benchmark's computed fingerprint — frozen as a literal (OME-1610).

A Benchmark's fingerprint is the hash of everything that defines it: its Cases, its scorer's
source, its judge and the pinned packages. It is an alarm, never published: every row sets
``published_revision`` and the Engine publishes that id, and nothing compares the two at run
time (owner decision, 2026-10-15). ``test_published_revisions.py`` pins the id a Benchmark
publishes; this file pins what its inputs compute. So a code move, a grading fix or a package
bump turns a literal here red while the published id, and every leaderboard result under it,
stays where it is.

AIDEV-NOTE: a red literal here is NEVER a reason to change ``published_revision``. Read the
rule in ``docs/adding-an-imported-benchmark.md`` ("Changing a Benchmark's published
revision") first. Same Cases (a refactor, a grading fix, a package bump): update only the
literal here. A fundamental change (a changed Case set, a new Benchmark): run
``just engine benchmark-bump <key>`` and get the owner's sign-off before the id moves.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks.medxpert import definition as medxpert  # noqa: E402
from screamingface_engine_inspect.benchmarks import BENCHMARKS, imported_benchmark  # noqa: E402

#: key → the fingerprint the Benchmark's inputs compute. The held rows come first: their
#: fingerprint differs from the id they publish because a grading fix kept every Case.
_FINGERPRINTS: dict[str, str] = {
    # OME-1701 PR 1: paws and boolq grade on a bare Yes or No (inspect_evals PR #2334 adopted).
    "paws": "992540ea3309d384",
    "boolq": "588977e58b380d7f",
    # OME-1701 PR 2: chembench grades its letters as a set (inspect_evals PR #2591 adopted);
    # infinite_bench_math_find grades by the first number (inspect_evals PR #2346 adopted).
    "chembench": "b86658ea78c51962",
    "infinite_bench_math_find": "1ed274442ad5dba1",
    # OME-1701 PR 3: math reads its answer line through a boxed answer, outer delimiters and
    # bold (inspect_evals' fixes adopted).
    "math": "4129dccca9dbb8ce",
    # OME-1701 PR 7: a reply cut off before its ANSWER: line is wrong (inspect_evals issue
    # #2701 adopted).
    "aime24": "600e759b1c5766e6",
    "aime25": "a8d8eb4969ef8b8a",
    "aime26": "b289716a32495871",
    # OME-1527: healthbench and ifeval moved from their hand-built folders to local Tasks and
    # kept the hand-built ids; the golden replays proved the exam unchanged.
    "healthbench-worst30": "f12c3e30661ea9d3",
    "healthbench-professional": "44ddda05be338699",
    "ifeval": "ada07458a23c55ab",
    # OME-1755: the judge reads the Sample's own question; each Case's Grading Material keeps
    # it, so the Case Digest moved while every Case input and the published id stayed (owner
    # decision 2026-10-28, no leaderboard scores on them yet).
    "xstest_safe": "141b1d86dc202e60",
    "xstest_unsafe": "306cf7e61c72c919",
    "uccb": "2dbcedb55406dc6e",
    # OME-1610: every other Benchmark, at the fingerprint main computes (2026-10-22), which is
    # also the id it publishes: no change since its id was last set.
    "gsm8k": "075954bfd63059e0",
    "mmlu": "9d4c0946ae71f6fa",
    "arc_easy": "f7d6a5325fb0bcff",
    "arc_challenge": "810d45748fde3b18",
    "commonsense_qa": "203aa920ad7ad52b",
    "mmlu_pro": "145edec84bfc2324",
    "winogrande": "4eb60a70db7518d6",
    "race_h": "8c5ebb4a9d38cc6f",
    "musr": "a527e0f0db79d923",
    "wmdp_bio": "557c21ed4fcf926e",
    "wmdp_chem": "08989c0d94e03c70",
    "wmdp_cyber": "d8310da16b5e9e1c",
    "hellaswag": "9190ec85b43791e0",
    "lab_bench_litqa": "109142a4408d3f4b",
    "lab_bench_suppqa": "3aae3cdf14efeab8",
    "lab_bench_dbqa": "21ff94a2ef9982c5",
    "lab_bench_protocolqa": "236b15e7b2c90e9b",
    "lab_bench_seqqa": "48e1368633436c5a",
    "lab_bench_cloning_scenarios": "9c6f66d6acae7f05",
    # OME-1327: the two LAB-Bench picture subsets, imported once a Case could carry a picture.
    "lab_bench_figqa": "7376109d25378310",
    "lab_bench_tableqa": "9990079555f06a35",
    # OME-1477: MMMU's multiple-choice task, the first picture Benchmark from a whole exam.
    "mmmu_multiple_choice": "5b008891134ef4c1",
    # OME-1479: MathVista, maths over pictures, the last of the four picture Benchmarks.
    "mathvista": "ca4cd0f692d18f0e",
    "frontierscience": "826050de44778515",
    "onet_m6": "cfc5f0da9f9418bd",
    "pubmedqa": "15e20f21d0a78fd9",
    "agieval_lsat_ar": "13fe1a6267102769",
    "agieval_lsat_lr": "dbaf28cfdc818528",
    "agieval_lsat_rc": "7e36f14f4aec1e60",
    "agieval_sat_math": "098022e0b1e81f81",
    "agieval_sat_en": "092ea478f523193d",
    "agieval_sat_en_without_passage": "7a4baa0259c5a3b7",
    "agieval_aqua_rat": "2550038f01d739fb",
    "agieval_logiqa_en": "884951da7ad9e2e1",
    "medqa": "0d4c53de5fd83ec4",
    "mgsm_en": "eba62e86a8d689a1",
    "bbq": "cb1baddfb5da6950",
    "piqa": "b51564ee7754bc92",
    "cybermetric_80": "8f8705617be73c5b",
    "cybermetric_500": "c558ca68a995b0e8",
    "cybermetric_2000": "c745e4876131fee2",
    "cybermetric_10000": "9cc0058e566bc9e5",
    "sevenllm_mcq_zh": "bf67d1707f236386",
    "sevenllm_mcq_en": "e0332fcbf2cfbded",
    "worldsense": "ad49b23d305a87dd",
    "coconot_original": "0c4d77a9254ebc29",
    "coconot_contrast": "0eff77619697954b",
    "sad_facts_llms": "c55f043049f958b9",
    "sad_facts_human_defaults": "8c6160f7390d08df",
    "sad_influence": "429f77793f3a10ca",
    "sad_stages_oversight": "2d5f56c1f30ee5dd",
    "sad_stages_full": "0dcca947db2e64de",
    "cyse4_mitre_frr": "0d6a53f259f81eff",
    "pre_flight": "11c8a1de849b8f0b",
    "bbeh": "4e98fa90e309b145",
    "squad": "5b97eeadbf95b722",
    "musique": "9ef0dcbdf3c310c6",
    "arc_agi_2": "4f831492ca42fdf4",
    "contracteval": "890889e5b2863be4",
    "gdpval-text": "f6ea752427e71362",
    "draco": "c6fb6f500dc58622",
    "draco-3pass": "e8c3ad925dcd4d4a",
    "frames_oracle": "6541f5df078dfabd",
    "simpleqa": "ffd3e901b78f9d0e",
    "simpleqa_verified": "f2b42ba095cade8e",
    "fortress_benign": "b04be10a93356ccd",
    "strong_reject": "6794ed308fafe0a6",
    "air_bench": "b5d90afe0f368dab",
    "truthfulqa_mc1": "a4ea7f621bf1640c",
    "stereoset": "c2bf158bee6d5f8b",
    "cyse4_malware_analysis": "0a1c3a7364512973",
    "drop": "9be2d9ed4b5f1a67",
    "cyse4_threat_intelligence": "92558cfb773e64d2",
    "bbh": "467f06b54836a6f8",
    "medmcqa": "60e9f16fbe7c0227",
    # The hand-built Benchmark (screamingface_engine.benchmarks.medxpert).
    "medxpert": "1e5a3b8a461a52f7",
}


def _fingerprint(key: str) -> str:
    """What the Benchmark's inputs compute today, whatever id it publishes."""

    return medxpert.FINGERPRINT if key == "medxpert" else imported_benchmark(key).fingerprint


@pytest.mark.parametrize("key", sorted(_FINGERPRINTS))
def test_the_fingerprint_follows_the_exam_not_the_published_id(key: str) -> None:
    """INVARIANT: the published id is hand-set, so a change to a Benchmark's scorer, Cases or
    pins moves only its fingerprint; this literal is the one place that change shows up."""

    computed: str = _fingerprint(key)

    assert computed == _FINGERPRINTS[key], (
        f"{key}: the fingerprint moved ({_FINGERPRINTS[key]} -> {computed}). "
        "Do NOT change published_revision to make this green. Same Cases (a refactor, a "
        "grading fix, a package bump): update only this literal. A fundamental change (a "
        f"changed Case set): run `just engine benchmark-bump {key}` and follow its checklist; "
        "the published id moves only with the owner's sign-off. Rule: "
        "docs/adding-an-imported-benchmark.md, 'Changing a Benchmark's published revision'."
    )


def test_every_benchmark_has_a_pinned_fingerprint() -> None:
    """A new row joins this file in the PR that adds it, so no Benchmark is ever unalarmed."""

    keys: set[str] = {spec.key for spec in BENCHMARKS} | {"medxpert"}

    assert keys == set(_FINGERPRINTS)
