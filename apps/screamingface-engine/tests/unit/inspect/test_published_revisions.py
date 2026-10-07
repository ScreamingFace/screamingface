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
_PUBLISHED_REVISIONS: dict[str, str] = {
    "gsm8k": "330615c3213bb681",
    # OME-1268: the first two Benchmarks with Named Scores (served in upstream order).
    "squad": "d0075817a5457cfb",
    # OME-1513: the first LOCAL Task (our own eval in inspect's shape, not an inspect_evals import).
    "musique": "67d3fc96ffc68e46",
    "math": "1963559fac28e4a1",
    "mmlu": "1e42325597dee3d6",
    "arc_easy": "5f063684bf708ca1",
    "arc_challenge": "b54aa46de0840b60",
    "commonsense_qa": "c133584254776a5e",
    "paws": "866ee57e62d10a88",
    "boolq": "d29adda5bb6a246c",
    "mmlu_pro": "05aaa663ac69d943",
    "winogrande": "07e46e0177ff0cb9",
    "race_h": "5ca6b26990c19643",
    "aime24": "d958c058e3f67e44",
    "aime25": "c637b487988d0753",
    "musr": "335aca22d85fd610",
    "wmdp_bio": "8b36af2e74e0c6d5",
    "wmdp_chem": "297614ecae016baa",
    "wmdp_cyber": "64c7e14444d0a4b5",
    "hellaswag": "c98211d79bcab080",
    # Verified against main 2026-09-30: the inverted-grade pin (OME-1400) exists only
    # when a row sets the flag, so its uninverted sibling keeps this revision.
    "xstest_safe": "1044036b2049e623",
}


@pytest.mark.parametrize(("key", "revision"), sorted(_PUBLISHED_REVISIONS.items()))
def test_published_benchmark_revision_is_byte_identical(key: str, revision: str) -> None:
    assert imported_benchmark(key).benchmark.revision == revision


#: OME-1460: every Task-replay Benchmark with no Hugging Face Case Source, as served on main
#: 0d1000d43 (2026-10-05). The fetch-pin enforcer adds an identity pin only to a row that
#: pins a Hub commit, so none of these may move; the five that read the Hub (medqa, bbq,
#: piqa, pre_flight, bbeh) gain their pin on purpose (spec D4) and are left out.
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
    "mgsm_en": "e96465d3247b9658",
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
