# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""A published revision that moves says why, in a note a leaderboard reader can see (OME-2001).

FEATURE: the revision note. A Benchmark's published revision moves when its Cases or its
grading change; from this file on, the new id ships with one short plain-text line saying what
changed and whether scores still compare (about 120 characters is the target, not a limit).
The Scoreboard seed carries the line to the Benchmark's page.
STORY: as a researcher holding runs under the old id, I read on the leaderboard what changed,
without asking the team.

How the check tells an old id from a new one. Every Benchmark revision is in exactly one of
two places below:

- ``_PUBLISHED_BEFORE_NOTES``: the 100 ids published on main the day this file landed
  (2026-11-23). They carry no note and nobody invents one for them. The set is FROZEN: its
  size and its sha256 are pinned, so adding an id is never a one-line edit, and the repo's
  append-only gate refuses any edit to this file without the owner's approval file.
- ``_NOTED_REVISIONS``: each id published since, with the exact note it serves. Writing the
  line here IS the review act, the same doctrine as ``test_published_revisions.py``: a
  Benchmark that moves twice cannot keep its first note, because the new id has no line here
  until someone writes one.

An id in neither place fails: that is a move (or a new Benchmark) without a note.

What this file does NOT check is the note's length. About 120 characters is the target the
author aims for, never a rule (owner decision, 2026-11-23); a longer note passes here and
wraps on the page.

WHY this file lives in tests/unit/inspect/: the imported Benchmarks join the registry only
with the inspect extra, and CI's extra-installed lane runs this directory. The hand-built
Benchmark (medxpert) is in the same registry, so one rule covers both kinds.
"""

from __future__ import annotations

import dataclasses
import hashlib

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks import Benchmark  # noqa: E402
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS  # noqa: E402
from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    BenchmarkSpec,
    _assemble,
)

#: ``<benchmark id>@<published revision>`` for every Benchmark on main before notes existed.
#: INVARIANT: never grows. A new or moved id goes in ``_NOTED_REVISIONS`` with its note.
_PUBLISHED_BEFORE_NOTES: frozenset[str] = frozenset(
    {
        "air_bench@b5d90afe0f368dab",
        "arc_agi_2@4f831492ca42fdf4",
        "bbh@c4f0aa7d023cbd2a",
        "contracteval@890889e5b2863be4",
        "draco-3pass@e8c3ad925dcd4d4a",
        "draco@c6fb6f500dc58622",
        "enigmaeval@863b8c98762520a2",
        "frames_oracle@6541f5df078dfabd",
        "futurex_past@200cf4f72481ffb0",
        "futurex_past_study@3c66e638e04516ed",
        "gdpval-text@f6ea752427e71362",
        "healthbench-professional@d8fb037307f35415",
        "healthbench-worst30@39cfd96b068f7230",
        "hle_diamond@9640c5c7e59fc61e",
        "ifeval@1cba769ece27f7ef",
        "infinite_bench_math_find@eb87494cb4dab437",
        "inspect-agieval_aqua_rat@f5aff58fd7757744",
        "inspect-agieval_logiqa_en@4603329f711a8441",
        "inspect-agieval_lsat_ar@e24c40ff7eb00ad1",
        "inspect-agieval_lsat_lr@0c55782670053db8",
        "inspect-agieval_lsat_rc@7414b6f2cd38efed",
        "inspect-agieval_sat_en@b54aa3324c5cf8e5",
        "inspect-agieval_sat_en_without_passage@67e7fac7146a8c4e",
        "inspect-agieval_sat_math@8fbe35b30bf21a7e",
        "inspect-aime24@2e4ce70a8953233a",
        "inspect-aime25@b207e9fe34ea7517",
        "inspect-aime26@c3ccaa828160f661",
        "inspect-arc_challenge@0e623d0bf152297f",
        "inspect-arc_easy@e74d42010074448c",
        "inspect-bbeh@4e98fa90e309b145",
        "inspect-bbq@bc9d396d0bb436fc",
        "inspect-boolq@00d4443ca7e66d43",
        "inspect-chembench@a36d91b7eb601253",
        "inspect-coconot_contrast@0eff77619697954b",
        "inspect-coconot_original@0c4d77a9254ebc29",
        "inspect-commonsense_qa@5b968b3e1fd93280",
        "inspect-cybermetric_10000@08174a6273d9ab85",
        "inspect-cybermetric_2000@9623777235b23ab1",
        "inspect-cybermetric_500@ad094e56d367042a",
        "inspect-cybermetric_80@a2b31b18a28e9eaf",
        "inspect-cyse4_malware_analysis@960b3cd5577db0fc",
        "inspect-cyse4_mitre_frr@0d6a53f259f81eff",
        "inspect-cyse4_threat_intelligence@80aa663a5187f5bd",
        "inspect-drop@9be2d9ed4b5f1a67",
        "inspect-fortress_benign@b04be10a93356ccd",
        "inspect-frontierscience@826050de44778515",
        "inspect-gsm8k@7eebba58799a2f22",
        "inspect-hellaswag@90eca5ef70f243e7",
        "inspect-hle@d30effc2a0698079",
        "inspect-lab_bench_cloning_scenarios@723a3f5a988ee349",
        "inspect-lab_bench_dbqa@1f9e60915b569740",
        "inspect-lab_bench_figqa@f826e8ceb03ad596",
        "inspect-lab_bench_litqa@201c79a3f2b025ca",
        "inspect-lab_bench_protocolqa@3314dda27de855f8",
        "inspect-lab_bench_seqqa@49f7f64cf6065dc0",
        "inspect-lab_bench_suppqa@3f47298ee2dc3156",
        "inspect-lab_bench_tableqa@fbace884de2f6ef5",
        "inspect-macbench@a8d8e6ccc379924f",
        "inspect-math@0fb750cf19e00c11",
        "inspect-mathvista@126be76d042c445b",
        "inspect-medqa@5524f2e397688fce",
        "inspect-mgsm_en@eba62e86a8d689a1",
        "inspect-mmlu@e6a95e4c1f1ced71",
        "inspect-mmlu_pro@4efebd6cc74c2dca",
        "inspect-mmmu_multiple_choice@c537e4e84ccb4d32",
        "inspect-mmmu_open@8ce88e420239ae4d",
        "inspect-musr@1b618ffed7ec9c4d",
        "inspect-onet_m6@f0abec484f0d9a59",
        "inspect-paws@8f4e0e9c0864a6e7",
        "inspect-piqa@4bafb8f015b6c626",
        "inspect-pre_flight@41d7f23b10379ca8",
        "inspect-pubmedqa@a1f2388c0f271b91",
        "inspect-race_h@9879ac1a4c9097e9",
        "inspect-sad_facts_human_defaults@8c6160f7390d08df",
        "inspect-sad_facts_llms@c55f043049f958b9",
        "inspect-sad_influence@429f77793f3a10ca",
        "inspect-sad_stages_full@0dcca947db2e64de",
        "inspect-sad_stages_oversight@2d5f56c1f30ee5dd",
        "inspect-sevenllm_mcq_en@c00f2228bd58360b",
        "inspect-sevenllm_mcq_zh@bf74fa7fb8723e89",
        "inspect-simpleqa@ffd3e901b78f9d0e",
        "inspect-simpleqa_verified@f2b42ba095cade8e",
        "inspect-squad@5b97eeadbf95b722",
        "inspect-strong_reject@6794ed308fafe0a6",
        "inspect-truthfulqa_mc1@60edf776837600e2",
        "inspect-uccb@022fa23a5e823aa7",
        "inspect-winogrande@539a9c0be94c8087",
        "inspect-wmdp_bio@009f4d3e7163867c",
        "inspect-wmdp_chem@deaa83e0dbf8837f",
        "inspect-wmdp_cyber@a3b56fe1a4d3355d",
        "inspect-xstest_safe@1044036b2049e623",
        "inspect-xstest_unsafe@fad9dd3ebabd84a5",
        "inspect-zerobench@9155d9581e103c0a",
        "labbench2_figqa2_img@770667413b4b1e51",
        "labbench2_tableqa2_img@742c148e87b15f69",
        "medmcqa@e9e7ca645e342f81",
        "medxpert@1e5a3b8a461a52f7",
        "musique@9ef0dcbdf3c310c6",
        "stereoset@c2bf158bee6d5f8b",
        "worldsense@ad49b23d305a87dd",
    }
)
#: The frozen set's size and sha256 (over its sorted lines joined by a newline).
_FROZEN_COUNT: int = 100
_FROZEN_SHA256: str = "c87e37675e004290be2dadf52521090b15a1d016c7fc1dac83e0e85a994ed010"

#: ``<benchmark id>@<published revision>`` → the exact note that revision serves.
#: A move adds its line here. The first two moved while this file was in review (their old
#: ids stay in the frozen set above, which is the list as it stood when the set was cut).
_NOTED_REVISIONS: dict[str, str] = {
    # OME-1998: moved from d8fb037307f35415 when the grading changed.
    "healthbench-professional@35c7d07e9058f52d": (
        "Length-adjusted score, judge at low effort, failed Cases count as 0. Not comparable "
        "with earlier results."
    ),
    # OME-1980: moved from 490235dc9a53b7d9 (itself moved from the frozen 1e5a3b8a461a52f7 by
    # OME-1786) when turn 2 became a continuation of the Candidate's own chat.
    "medxpert@952ea002b0f5e3b0": (
        "The commit turn now continues the model's own chat, as the official harness does. "
        "Not comparable with older revisions."
    ),
}


def _identity(benchmark: Benchmark) -> str:
    """One Benchmark revision as this file names it."""

    return f"{benchmark.id}@{benchmark.revision}"


def test_the_set_of_revisions_that_predate_notes_is_frozen() -> None:
    """INVARIANT: an id cannot join the no-note-needed set quietly. Adding a line also needs
    the count and the digest changed, three edits a reviewer cannot miss, on top of the owner's
    approval the append-only gate asks for."""

    digest: str = hashlib.sha256("\n".join(sorted(_PUBLISHED_BEFORE_NOTES)).encode()).hexdigest()

    assert len(_PUBLISHED_BEFORE_NOTES) == _FROZEN_COUNT
    assert digest == _FROZEN_SHA256, (
        "the set of revisions published before notes changed. It is frozen: a new or moved "
        "revision declares a note (revision_note=) and adds its line to _NOTED_REVISIONS."
    )


def test_the_registry_holds_both_kinds_of_benchmark() -> None:
    """WHY: the rule below must cover imported rows AND the hand-built Benchmark. A plugin
    that registered nothing would leave it checking one id and passing."""

    ids: set[str] = {benchmark.id for benchmark in BUILTIN_BENCHMARKS}

    assert "medxpert" in ids
    assert len(ids) > 1, "the inspect extra is installed but no imported Benchmark registered"


@pytest.mark.parametrize("benchmark", tuple(BUILTIN_BENCHMARKS), ids=lambda b: b.id)
def test_a_revision_published_after_notes_existed_carries_its_pinned_note(
    benchmark: Benchmark,
) -> None:
    """A moved id must come with a note, because the leaderboard shows the id as a bare hash
    and the reason otherwise never leaves this repository."""

    identity: str = _identity(benchmark)
    if identity in _PUBLISHED_BEFORE_NOTES:
        return

    assert identity in _NOTED_REVISIONS, (
        f"{identity} is a revision published after notes existed, and no note is pinned for "
        "it. Declare revision_note= beside the id (one short line of plain text, aim for about "
        "120 characters: what changed, and whether scores still compare), then add this id and "
        "that exact text to _NOTED_REVISIONS."
    )
    assert benchmark.revision_note == _NOTED_REVISIONS[identity], (
        f"{identity} serves a note that is not the one pinned here. A Benchmark that moved "
        "again needs a note for the new id, never the previous move's text by accident."
    )


def test_a_moved_revision_with_a_note_longer_than_the_target_passes_the_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check asks for a note, never for a short one: a moved id whose pinned note runs to
    300 characters passes, and the same moved id with no note still fails."""

    old: Benchmark = next(b for b in BUILTIN_BENCHMARKS if b.id == "medxpert")
    long_note: str = "Two-turn reasoning is sent as text only. " + "x" * 259
    moved: Benchmark = dataclasses.replace(
        old, revision="fedcba9876543210", revision_note=long_note
    )
    silent: Benchmark = dataclasses.replace(old, revision="fedcba9876543210")
    monkeypatch.setitem(_NOTED_REVISIONS, _identity(moved), long_note)

    assert len(long_note) == 300
    test_a_revision_published_after_notes_existed_carries_its_pinned_note(moved)
    with pytest.raises(AssertionError, match="not the one pinned"):
        test_a_revision_published_after_notes_existed_carries_its_pinned_note(silent)
    monkeypatch.delitem(_NOTED_REVISIONS, _identity(moved))
    with pytest.raises(AssertionError, match="no note is pinned"):
        test_a_revision_published_after_notes_existed_carries_its_pinned_note(silent)


def test_a_revision_is_never_both_old_and_noted() -> None:
    """One home per id: an id listed in both places would let either rule excuse the other."""

    assert not _PUBLISHED_BEFORE_NOTES & set(_NOTED_REVISIONS)


def test_a_catalogue_rows_note_reaches_the_benchmark_it_assembles() -> None:
    """An imported row declares its note beside ``published_revision``; assembly hands it to
    the same ``Benchmark`` field a hand-built Benchmark sets directly, so one catalogue seam
    serves both kinds."""

    row: BenchmarkSpec = next(spec for spec in BENCHMARKS if spec.key == "mmlu_pro")
    note: str = "Wrapped answer letters are read. Comparable after a re-grade."

    noted: Benchmark = _assemble(dataclasses.replace(row, revision_note=note)).benchmark
    plain: Benchmark = _assemble(row).benchmark

    assert noted.revision_note == note
    assert noted.catalog_entry()["revision_note"] == note
    # The note is prose about the revision, never part of it.
    assert noted.revision == plain.revision
    assert plain.revision_note is None
