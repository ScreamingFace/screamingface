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
    # OME-1853: published id HELD at 1cba769ece27f7ef (fingerprint was ada07458a23c55ab); the
    # row now declares nltk and langdetect as scorer dependencies, so their installed versions
    # (nltk 3.10.4 after the security bump, langdetect 1.0.9) pin into the fingerprint.
    "ifeval": "29daaba023020d0a",
    # OME-1853: Pillow 13 re-encoded every picture of the three picture Benchmarks and pypdf
    # 6.21 re-extracted cyse4's report text, so their Cases and fingerprints moved; each
    # published id HELD by owner ruling 2026-11-09 (no official leaderboard runs on them yet).
    # mmmu_multiple_choice: published id 5b008891134ef4c1 (fingerprint was the same).
    "mmmu_multiple_choice": "43062a000fc39371",
    # mathvista: published id ca4cd0f692d18f0e (fingerprint was the same).
    "mathvista": "3a49fb3c5a5cad03",
    # cyse4_threat_intelligence: published id 92558cfb773e64d2 (fingerprint was the same).
    "cyse4_threat_intelligence": "da4d0f7d03b831bf",
    # OME-1755: the judge reads the Sample's own question; each Case's Grading Material keeps
    # it, so the Case Digest moved while every Case input and the published id stayed (owner
    # decision 2026-10-28, no leaderboard scores on them yet).
    "xstest_safe": "141b1d86dc202e60",
    "xstest_unsafe": "306cf7e61c72c919",
    "uccb": "2dbcedb55406dc6e",
    # OME-1610: every other Benchmark, at the fingerprint main computes (2026-10-22), which is
    # also the id it publishes: no change since its id was last set. EXCEPT OME-1907: the 46
    # rows graded from option marks (inspect's choice, lab_bench, cyse4, bbh) and mathvista
    # moved with the wrapped-letter rule (an answer such as `ANSWER: $B` is read), a grading
    # fix that keeps every Case, so each published id is HELD and only its literal moved here.
    "gsm8k": "7eebba58799a2f22",
    "mmlu": "4ae3b8ad8939d06a",
    "arc_easy": "6827270be201e36e",
    "arc_challenge": "09d7863273748190",
    "commonsense_qa": "c60a5ac44ac5357e",
    "mmlu_pro": "11a6d36171006ea3",
    "winogrande": "c51c8693fec65dae",
    "race_h": "1797d7bf4756c4c6",
    "musr": "810d6c7af8ff85db",
    "wmdp_bio": "93be16e1508f2c7a",
    "wmdp_chem": "9df7e2b4876aa4d8",
    "wmdp_cyber": "b38d52aceef1522f",
    "hellaswag": "727a1abc96698757",
    "lab_bench_litqa": "7b62006503185008",
    "lab_bench_suppqa": "f85ee94946e6f519",
    "lab_bench_dbqa": "b8dde2b213d81ad0",
    "lab_bench_protocolqa": "da30c0213d5177c4",
    "lab_bench_seqqa": "6ffe5f7915680322",
    "lab_bench_cloning_scenarios": "e00877f647c4aec9",
    # OME-1327: the two LAB-Bench picture subsets, imported once a Case could carry a picture.
    "lab_bench_figqa": "1273c72f5fefac97",
    "lab_bench_tableqa": "08686b3752cd5800",
    # OME-1477 PR 2: MMMU's open-answer task, judged once the judge read inspect's question.
    "mmmu_open": "8ce88e420239ae4d",
    # OME-1478: Humanity's Last Exam, the full set with its pictures, judged by glm-5.3-flash.
    "hle": "d30effc2a0698079",
    # OME-1733: LABBench2 FigQA2 and TableQA2 image, a local Task judged by Sonnet 4.5.
    "labbench2_figqa2_img": "770667413b4b1e51",
    "labbench2_tableqa2_img": "742c148e87b15f69",
    # OME-1855: ZeroBench's 100 main questions with their pictures, one-sample pass@1. Its seal
    # survived Pillow 13 (OME-1853): replayed inside the linux/amd64 image, the Case Digest
    # 7b1b680a… came back unchanged, so neither the Cases nor this fingerprint moved.
    "zerobench": "9155d9581e103c0a",
    # OME-1854: MaCBench, chemistry and materials pictures, letters graded as a set.
    "macbench": "a8d8e6ccc379924f",
    "frontierscience": "826050de44778515",
    "onet_m6": "3725511bcc4f2c71",
    "pubmedqa": "560c7b5e910df97c",
    "agieval_lsat_ar": "2c80f888b8e316b1",
    "agieval_lsat_lr": "97ed10f53180532b",
    "agieval_lsat_rc": "112349dcb1e8aef8",
    "agieval_sat_math": "8066b27c1b7d874c",
    "agieval_sat_en": "0ef6796e8320915e",
    "agieval_sat_en_without_passage": "8d25edd450b91759",
    "agieval_aqua_rat": "ed43efe0661fcc8d",
    "agieval_logiqa_en": "5581922bf4177f7c",
    "medqa": "e6e6b6fc0dd879a7",
    "mgsm_en": "eba62e86a8d689a1",
    "bbq": "9437c8c596c8d3aa",
    "piqa": "9a3d5e8d90797b77",
    "cybermetric_80": "8dc6ca0421edd545",
    "cybermetric_500": "6ea469cb4f6758ec",
    "cybermetric_2000": "991031d8489894eb",
    "cybermetric_10000": "29505d78f449de39",
    "sevenllm_mcq_zh": "2755c470a7a83521",
    "sevenllm_mcq_en": "b38509fbe12e8967",
    "worldsense": "ad49b23d305a87dd",
    "coconot_original": "0c4d77a9254ebc29",
    "coconot_contrast": "0eff77619697954b",
    "sad_facts_llms": "c55f043049f958b9",
    "sad_facts_human_defaults": "8c6160f7390d08df",
    "sad_influence": "429f77793f3a10ca",
    "sad_stages_oversight": "2d5f56c1f30ee5dd",
    "sad_stages_full": "0dcca947db2e64de",
    "cyse4_mitre_frr": "0d6a53f259f81eff",
    "pre_flight": "41d9ffdea92e6b2f",
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
    "truthfulqa_mc1": "5cd44c02275adeb2",
    "stereoset": "c2bf158bee6d5f8b",
    "cyse4_malware_analysis": "a1aa449992cf6293",
    "drop": "9be2d9ed4b5f1a67",
    "bbh": "3789614ea573c460",
    "medmcqa": "99ac043a20d7feb5",
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
