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
_PUBLISHED_REVISIONS: dict[str, str] = {
    "gsm8k": "df52a7b257fe8701",
    "mmlu": "49ee9af05fb6e15f",
    "arc_easy": "b65db0c432a718aa",
    "arc_challenge": "a08708c1ab765cff",
    "commonsense_qa": "4a4e8e12ff7a112d",
    "paws": "82d6b39c271cbdd1",
    "boolq": "e1d1ca4f97ea32f0",
    "mmlu_pro": "41ebb1f731886df8",
    "winogrande": "22fd4c35111f2d7d",
    "race_h": "619493b3ea10bbb0",
    "aime24": "fe26f860bc661efe",
    "aime25": "94a6b9ead168a622",
    "musr": "6cfb64a1c68595cb",
    "wmdp_bio": "d2c264d42b33ce58",
    "wmdp_chem": "c1052f7956dd9bb6",
    "wmdp_cyber": "dbb68d47d68f4e09",
    "hellaswag": "b3f504a886222b6a",
    # Verified against main 2026-09-30: the inverted-grade pin (OME-1400) exists only
    # when a row sets the flag, so its uninverted sibling keeps this revision.
    "xstest_safe": "97047574a6efa53a",
}


@pytest.mark.parametrize(("key", "revision"), sorted(_PUBLISHED_REVISIONS.items()))
def test_published_benchmark_revision_is_byte_identical(key: str, revision: str) -> None:
    assert imported_benchmark(key).benchmark.revision == revision


#: OME-1460: every Task-replay Benchmark with no Hugging Face Case Source, as served on main
#: 0d1000d43 (2026-10-05). The fetch-pin enforcer adds an identity pin only to a row that
#: pins a Hub commit, so none of these may move; medqa, bbq and piqa gain their pin on
#: purpose (spec D4) and are left out.
_URL_ONLY_TASK_REPLAY_REVISIONS: dict[str, str] = {
    "agieval_aqua_rat": "878ad44393d431a4",
    "agieval_logiqa_en": "2e1f1c960caa7a0f",
    "agieval_lsat_ar": "017a3493849e9bf3",
    "agieval_lsat_lr": "633ce0a2c3f1e4fa",
    "agieval_lsat_rc": "d15fdabe16971db5",
    "agieval_sat_en": "0dd4b206f7f3787b",
    "agieval_sat_en_without_passage": "05d42ff073975ee3",
    "agieval_sat_math": "71f3e7b2ddfa58e9",
    "cybermetric_10000": "1174c252ffaebfab",
    "cybermetric_2000": "4d53683a812ef2c5",
    "cybermetric_500": "9ff30cf33ee155e4",
    "cybermetric_80": "6cfebaf54236f398",
    "cyse4_mitre_frr": "0d6a53f259f81eff",
    "mgsm_en": "773b5e835820032d",
    "sad_facts_human_defaults": "0a90cd743e4e33a7",
    "sad_facts_llms": "6e0763d561439f9a",
    "sad_influence": "c6124a6e15dcdef7",
    "sad_stages_full": "a548998184f8fe54",
    "sad_stages_oversight": "ad42c0f4e66ad0cf",
    "sevenllm_mcq_en": "c8ef9b7c8db97e9a",
    "sevenllm_mcq_zh": "a8177911cb41f07e",
    "worldsense": "e30c575f1b740fae",
}


@pytest.mark.parametrize(("key", "revision"), sorted(_URL_ONLY_TASK_REPLAY_REVISIONS.items()))
def test_a_task_replay_benchmark_without_a_hub_source_keeps_its_revision(
    key: str, revision: str
) -> None:
    assert imported_benchmark(key).benchmark.revision == revision
