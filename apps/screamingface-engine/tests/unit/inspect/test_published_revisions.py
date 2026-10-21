# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The published benchmarks' EXACT revisions — frozen as literals.

A benchmark's revision is its identity: members' published scores hang off it, and
the asset store treats a revision's prepared assets as immutable. Every revision
input so far (pins, protocol constants, the OME-1240 judge pins) is code an innocent
refactor can touch, and the uniqueness/moves tests cannot see a WHOLESALE shift —
a review probe moved all 17 revisions with a one-line change while 3575 tests
stayed green (2026-09-24). These literals make that failure loud.

When a revision here changes on purpose (a pin bump, a protocol revision bump),
updating the literal IS the review act — the diff line is the declaration that the
published benchmark moved.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402

#: key → the exact published revision, as served on main (verified 2026-09-24).
#: OME-1513 (2026-10-07): eight free-text rows moved once when their Draft Feedback offer was
#: turned off — the offer is a per-Benchmark owner decision, never a family default.
#: OME-1642 (2026-10-19): every withhold row here moved once when its score became the mean over
#: all selected Cases — the failure policy is Benchmark identity (spec R6).
_PUBLISHED_REVISIONS: dict[str, str] = {
    "gsm8k": "075954bfd63059e0",
    # OME-1268: the first two Benchmarks with Named Scores (served in inspect_evals' order).
    "squad": "5b97eeadbf95b722",
    # OME-1513: the first LOCAL Task (our own eval in inspect's shape, not an inspect_evals import).
    # OME-1527: 1ae798e073477a54 → 9ba23547b22e70ff, support F1 now raises on a missing
    # supporting_idx (the scorer source is hashed); owner-approved on OME-1527 Work order #5.
    # OME-1642: 9ba23547b22e70ff → 9ef0dcbdf3c310c6, the failure policy (withhold) joined the pin.
    "musique": "9ef0dcbdf3c310c6",
    # OME-1527: contracteval moved from its hand-built folder (f9a076a10a6ae4c6) to a local Task
    # whose metric returns the hand-built run numbers beside F1 (headline key "f1").
    "contracteval": "890889e5b2863be4",
    # OME-1527: gdpval-text moved from its hand-built folder (cacfc3e6b83765f6) to a local Task;
    # owner-accepted (no external users), the revision moves once.
    "gdpval-text": "f6ea752427e71362",
    # OME-1527: draco (62718f04ea1a980f) and draco-3pass (2634cec91fd0f19a) moved from their
    # hand-built folder to one local Task package; owner-accepted (no external users), each
    # revision moves once. The draco-3pass e2e golden replays unchanged against the new one.
    "draco": "c6fb6f500dc58622",
    "draco-3pass": "e8c3ad925dcd4d4a",
    # OME-1527: healthbench-worst30 and healthbench-professional moved from their hand-built
    # folder to one local Task package and publish their old revisions (published_revision),
    # so their leaderboard results stay visible.
    "healthbench-worst30": "39cfd96b068f7230",
    "healthbench-professional": "d8fb037307f35415",
    # OME-1527: ifeval moved from its hand-built folder to a local Task, its Case ids
    # renumbered 1..541 (owner decision 2), and publishes its old revision (published_revision),
    # so its leaderboard results stay visible.
    "ifeval": "1cba769ece27f7ef",
    # OME-1481: FRAMES with its gold articles given, a local Task judged by the paper's prompt.
    "frames_oracle": "6541f5df078dfabd",
    # OME-1696: BIG-Bench Hard, a local Task asked and graded the paper's way (two Named
    # Deviations from inspect_evals' bbh); its source is hashed, so a scorer edit moves this.
    "bbh": "467f06b54836a6f8",
    # OME-1696: MedMCQA, a local Task we wrote in inspect's shape (validation split).
    "medmcqa": "60e9f16fbe7c0227",
    # OME-1476: the first published Benchmark with Attempts and an honoured whole-run metric.
    "arc_agi_2": "4f831492ca42fdf4",
    "math": "0fb750cf19e00c11",
    "mmlu": "9d4c0946ae71f6fa",
    "arc_easy": "f7d6a5325fb0bcff",
    "arc_challenge": "810d45748fde3b18",
    "commonsense_qa": "203aa920ad7ad52b",
    "paws": "8f4e0e9c0864a6e7",
    "boolq": "00d4443ca7e66d43",
    "mmlu_pro": "145edec84bfc2324",
    "winogrande": "4eb60a70db7518d6",
    "race_h": "8c5ebb4a9d38cc6f",
    "aime24": "2e4ce70a8953233a",
    "aime25": "b207e9fe34ea7517",
    "musr": "a527e0f0db79d923",
    "wmdp_bio": "557c21ed4fcf926e",
    "wmdp_chem": "08989c0d94e03c70",
    "wmdp_cyber": "d8310da16b5e9e1c",
    "hellaswag": "9190ec85b43791e0",
    # Verified against main 2026-09-30: the inverted-grade pin (OME-1400) exists only
    # when a row sets the flag, so its uninverted sibling keeps this revision.
    "xstest_safe": "1044036b2049e623",
    # OME-1701 PR 2: first frozen here, at the revision main serves, which the rows hold.
    "chembench": "a36d91b7eb601253",
    "infinite_bench_math_find": "eb87494cb4dab437",
    # OME-1701 PR 5 (2026-10-21): first frozen here, at the move to a local Task
    # that keeps every record (inspect_evals PR #2524 adopted; 2,115 → 2,123 Cases; stereoset
    # 6fe6deab5af299e2 before it).
    "stereoset": "c2bf158bee6d5f8b",
    # OME-1701 PR 6 (2026-10-21): first frozen here, at the move that left out the
    # 18 questions v0.20.0 builds wrongly (inspect_evals PR #2590 adopted; 391 → 373 Cases;
    # onet_m6 fefdc98fb53b0777 before it).
    "onet_m6": "fa7e02ef6c82f99d",
}


@pytest.mark.parametrize(("key", "revision"), sorted(_PUBLISHED_REVISIONS.items()))
def test_published_benchmark_revision_is_byte_identical(key: str, revision: str) -> None:
    assert imported_benchmark(key).benchmark.revision == revision


#: OME-1460: every Task-replay Benchmark with no Hugging Face Case Source, as served on main
#: 0d1000d43 (2026-10-05). The fetch-pin enforcer adds an identity pin only to a row that
#: pins a Hub commit, so none of these may move; the five that read the Hub (medqa, bbq,
#: piqa, pre_flight, bbeh) gain their pin on purpose (spec D4) and are left out.
#: OME-1642 (2026-10-19): all of these declare withhold, so each moved once for the failure
#: policy pin; the fetch-pin rule above still holds (no Hub pin was added).
_URL_ONLY_TASK_REPLAY_REVISIONS: dict[str, str] = {
    "agieval_aqua_rat": "2550038f01d739fb",
    "agieval_logiqa_en": "884951da7ad9e2e1",
    "agieval_lsat_ar": "13fe1a6267102769",
    "agieval_lsat_lr": "dbaf28cfdc818528",
    "agieval_lsat_rc": "7e36f14f4aec1e60",
    "agieval_sat_en": "092ea478f523193d",
    "agieval_sat_en_without_passage": "7a4baa0259c5a3b7",
    "agieval_sat_math": "098022e0b1e81f81",
    "cybermetric_10000": "9cc0058e566bc9e5",
    "cybermetric_2000": "c745e4876131fee2",
    "cybermetric_500": "c558ca68a995b0e8",
    "cybermetric_80": "8f8705617be73c5b",
    "cyse4_mitre_frr": "0d6a53f259f81eff",
    "mgsm_en": "eba62e86a8d689a1",
    "sad_facts_human_defaults": "8c6160f7390d08df",
    "sad_facts_llms": "c55f043049f958b9",
    "sad_influence": "429f77793f3a10ca",
    "sad_stages_full": "0dcca947db2e64de",
    "sad_stages_oversight": "2d5f56c1f30ee5dd",
    "sevenllm_mcq_en": "e0332fcbf2cfbded",
    "sevenllm_mcq_zh": "bf67d1707f236386",
    # OME-1701 PR 4 (2026-10-21): a2f8699ca22f49e5 → ad49b23d305a87dd, served by
    # a local Task that keeps every trial (inspect_evals PR #2507 adopted; 40,176 → 87,048
    # Cases). Still no Hub pin: the fetch-pin rule above holds.
    "worldsense": "ad49b23d305a87dd",
}


@pytest.mark.parametrize(("key", "revision"), sorted(_URL_ONLY_TASK_REPLAY_REVISIONS.items()))
def test_a_task_replay_benchmark_without_a_hub_source_keeps_its_revision(
    key: str, revision: str
) -> None:
    assert imported_benchmark(key).benchmark.revision == revision
