# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Every Benchmark's computed fingerprint — frozen as a literal (OME-1610).

A Benchmark's fingerprint is the hash of everything that defines it: its Cases, its scorer's
source, its judge and the pinned packages. It is an alarm, never published: every row sets
``published_revision`` and the Engine publishes that id, and nothing compares the two at run
time (owner decision, 2026-10-15). ``test_published_revisions.py`` pins the id a Benchmark
publishes; this file pins what its inputs compute. So a code move or a package bump turns a
literal here red while the published id, and every leaderboard result under it, stays where it
is; a grading change turns it red and also moves the published id (owner decision, 2026-11-17).

AIDEV-NOTE: a red literal here is NEVER a reason to change ``published_revision``. Read the
rule in ``docs/adding-an-imported-benchmark.md`` ("Changing a Benchmark's published
revision") first. Only code moved, every grade the same (a refactor, a code move, a package
bump): update only the literal here. Changed Cases, changed grading or a new Benchmark: run
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
    # OME-1998: worst-30's published id HELD at 39cfd96b068f7230 (fingerprint was
    # f12c3e30661ea9d3). The Task package's source is hashed and gained professional's length
    # adjustment, which worst-30 never turns on: its scorer arguments, judge params, failure
    # policy and every number in test_local_task_healthbench.py are unchanged.
    "healthbench-worst30": "75cdc1d5086ae220",
    # OME-1998: the grading changed (length adjustment, judge reasoning_effort=low, a failed
    # Case counts 0), so the published id moved to 35c7d07e9058f52d, the fingerprint when the
    # grading changed (it was 44ddda05be338699 before). The literal here is one step on: a
    # review round reworded docstrings in the hashed Task package, every grade the same, so
    # the published id held.
    "healthbench-professional": "b46faf98e52d7a35",
    # OME-1853: published id HELD at 1cba769ece27f7ef (fingerprint was ada07458a23c55ab); the
    # row now declares nltk and langdetect as scorer dependencies, so their installed versions
    # (nltk 3.10.4 after the security bump, langdetect 1.0.9) pin into the fingerprint.
    "ifeval": "29daaba023020d0a",
    # OME-1853: Pillow 13 re-encoded every picture of the three picture Benchmarks and pypdf
    # 6.21 re-extracted cyse4's report text, so their Cases and fingerprints moved; each
    # published id HELD by owner ruling 2026-11-09 (no official leaderboard runs on them yet).
    # OME-1958 then moved all three for OME-1907's grading change; each old id spans both Case
    # sets, so an entry from before OME-1853 misses its pinned cache and needs a fresh run.
    # mmmu_multiple_choice: published id 5b008891134ef4c1 (fingerprint was the same).
    "mmmu_multiple_choice": "c537e4e84ccb4d32",
    # mathvista: published id ca4cd0f692d18f0e (fingerprint was the same).
    "mathvista": "126be76d042c445b",
    # cyse4_threat_intelligence: published id 92558cfb773e64d2 (fingerprint was the same).
    "cyse4_threat_intelligence": "80aa663a5187f5bd",
    # OME-1755: the judge reads the Sample's own question; each Case's Grading Material keeps
    # it, so the Case Digest moved while every Case input and the published id stayed (owner
    # decision 2026-10-28, no leaderboard scores on them yet).
    "xstest_safe": "141b1d86dc202e60",
    "xstest_unsafe": "306cf7e61c72c919",
    "uccb": "2dbcedb55406dc6e",
    # OME-1939: the judge's max_tokens rose from 32768 to 131072, so a judge that reasons long
    # still writes its grade; every Case kept, published ids HELD (owner decision 2026-11-17,
    # a re-grade and revision bump follow in their own PR).
    # hle: published id d30effc2a0698079 (fingerprint was the same).
    "hle": "6bf010527abe2411",
    # hle_diamond: published id 9640c5c7e59fc61e (fingerprint was the same).
    "hle_diamond": "7261715107987e29",
    # FutureX-Past Judge bug (2026-11-19): the Judge no longer pins temperature 0, which no
    # OpenRouter endpoint for gpt-5.4 accepts, so every level-3/4 Judge call failed. Same Cases,
    # a grading fix: published id HELD at 200cf4f72481ffb0 (owner decision 2026-11-19; the
    # fingerprint was the same).
    "futurex_past": "cbf11bdc4466620e",
    # OME-1610: every other Benchmark, at the fingerprint main computes (2026-10-22), which is
    # also the id it publishes: no change since its id was last set. EXCEPT OME-1907: the 46
    # rows graded from option marks (inspect's choice, lab_bench, cyse4, bbh) and mathvista
    # moved with the wrapped-letter rule (an answer such as `ANSWER: $B` is read), a grading
    # fix that keeps every Case. #1783 held each published id; OME-1958 then moved each one to
    # the fingerprint below (old ids in test_published_revisions.py), under the 2026-11-17 rule.
    "gsm8k": "7eebba58799a2f22",
    "mmlu": "e6a95e4c1f1ced71",
    "arc_easy": "e74d42010074448c",
    "arc_challenge": "0e623d0bf152297f",
    "commonsense_qa": "5b968b3e1fd93280",
    "mmlu_pro": "4efebd6cc74c2dca",
    "winogrande": "539a9c0be94c8087",
    "race_h": "9879ac1a4c9097e9",
    "musr": "1b618ffed7ec9c4d",
    "wmdp_bio": "009f4d3e7163867c",
    "wmdp_chem": "deaa83e0dbf8837f",
    "wmdp_cyber": "a3b56fe1a4d3355d",
    "hellaswag": "90eca5ef70f243e7",
    "lab_bench_litqa": "201c79a3f2b025ca",
    "lab_bench_suppqa": "3f47298ee2dc3156",
    "lab_bench_dbqa": "1f9e60915b569740",
    "lab_bench_protocolqa": "3314dda27de855f8",
    "lab_bench_seqqa": "49f7f64cf6065dc0",
    "lab_bench_cloning_scenarios": "723a3f5a988ee349",
    # OME-1327: the two LAB-Bench picture subsets, imported once a Case could carry a picture.
    "lab_bench_figqa": "f826e8ceb03ad596",
    "lab_bench_tableqa": "fbace884de2f6ef5",
    # OME-1477 PR 2: MMMU's open-answer task, judged once the judge read inspect's question.
    "mmmu_open": "8ce88e420239ae4d",
    # OME-1733: LABBench2 FigQA2 and TableQA2 image, a local Task judged by Sonnet 4.5.
    "labbench2_figqa2_img": "770667413b4b1e51",
    "labbench2_tableqa2_img": "742c148e87b15f69",
    # OME-1855: ZeroBench's 100 main questions with their pictures, one-sample pass@1. Its seal
    # survived Pillow 13 (OME-1853): replayed inside the linux/amd64 image, the Case Digest
    # 7b1b680a… came back unchanged, so neither the Cases nor this fingerprint moved.
    "zerobench": "9155d9581e103c0a",
    # OME-1854: MaCBench, chemistry and materials pictures, letters graded as a set.
    "macbench": "a8d8e6ccc379924f",
    # OME-1874: EnigmaEval, a local Task; its source is hashed, so an edit to the prompt
    # builder or the copied marking moves this.
    "enigmaeval": "863b8c98762520a2",
    "frontierscience": "826050de44778515",
    "onet_m6": "f0abec484f0d9a59",
    "pubmedqa": "a1f2388c0f271b91",
    "agieval_lsat_ar": "e24c40ff7eb00ad1",
    "agieval_lsat_lr": "0c55782670053db8",
    "agieval_lsat_rc": "7414b6f2cd38efed",
    "agieval_sat_math": "8fbe35b30bf21a7e",
    "agieval_sat_en": "b54aa3324c5cf8e5",
    "agieval_sat_en_without_passage": "67e7fac7146a8c4e",
    "agieval_aqua_rat": "f5aff58fd7757744",
    "agieval_logiqa_en": "4603329f711a8441",
    "medqa": "5524f2e397688fce",
    "mgsm_en": "eba62e86a8d689a1",
    "bbq": "bc9d396d0bb436fc",
    "piqa": "4bafb8f015b6c626",
    "cybermetric_80": "a2b31b18a28e9eaf",
    "cybermetric_500": "ad094e56d367042a",
    "cybermetric_2000": "9623777235b23ab1",
    "cybermetric_10000": "08174a6273d9ab85",
    "sevenllm_mcq_zh": "bf74fa7fb8723e89",
    "sevenllm_mcq_en": "c00f2228bd58360b",
    "worldsense": "ad49b23d305a87dd",
    "coconot_original": "0c4d77a9254ebc29",
    "coconot_contrast": "0eff77619697954b",
    "sad_facts_llms": "c55f043049f958b9",
    "sad_facts_human_defaults": "8c6160f7390d08df",
    "sad_influence": "429f77793f3a10ca",
    "sad_stages_oversight": "2d5f56c1f30ee5dd",
    "sad_stages_full": "0dcca947db2e64de",
    "cyse4_mitre_frr": "0d6a53f259f81eff",
    "pre_flight": "41d7f23b10379ca8",
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
    "truthfulqa_mc1": "60edf776837600e2",
    "stereoset": "c2bf158bee6d5f8b",
    "cyse4_malware_analysis": "960b3cd5577db0fc",
    "drop": "9be2d9ed4b5f1a67",
    "bbh": "c4f0aa7d023cbd2a",
    "medmcqa": "e9e7ca645e342f81",
    "futurex_past_study": "3c66e638e04516ed",
    # The hand-built Benchmark (screamingface_engine.benchmarks.medxpert).
    # Moved from 1e5a3b8a461a52f7 (OME-1786): turn 2 carries turn 1's answer text, not its record.
    # Moved from 490235dc9a53b7d9 (OME-1980): turn 2 continues the Candidate's own chat.
    # Moved from 952ea002b0f5e3b0 (OME-2018): turn 2 states its reply rule, the option letter only.
    "medxpert": "5f6e01e4fa673215",
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
        "Do NOT change published_revision to make this green. Only code moved, every grade "
        "the same (a refactor, a code move, a package bump): update only this literal. "
        f"Changed Cases or changed grading: run `just engine benchmark-bump {key}` and follow "
        "its checklist; "
        "the published id moves only with the owner's sign-off. Rule: "
        "docs/adding-an-imported-benchmark.md, 'Changing a Benchmark's published revision'."
    )


def test_every_benchmark_has_a_pinned_fingerprint() -> None:
    """A new row joins this file in the PR that adds it, so no Benchmark is ever unalarmed."""

    keys: set[str] = {spec.key for spec in BENCHMARKS} | {"medxpert"}

    assert keys == set(_FINGERPRINTS)
