# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The generated board rows — every imported board's catalogue contract, in one place.

INVARIANT the suite defends: a board is two data rows the importer generated and a
human reviewed — so each row pair must (1) register under its `inspect-<key>` id,
(2) pin a 40-hex dataset revision and a positive case count (exam identity), (3)
declare the check surface by family — free-text boards carry it, MCQ boards are
refused it (OME-796) — and (4) point at a scorer and templates that actually
resolve inside the pinned eval package. Catalogue prose is filled (never TODO):
onboarding is AI-first, and unreviewed placeholder prose must fail CI, not ship.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

from importlib import import_module

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine_inspect.boards import (  # noqa: E402
    BOARDS,
    board_registrations,
    imported_board,
)
from screamingface_engine_inspect.prepare import SNAPSHOTS  # noqa: E402

#: Every imported board key and its family: "mcq" (choice scorer, check surface
#: refused per OME-796), "free_text" (check surface ON, spec §4), or "judged"
#: (LLM-judged — check surface refused until the check-cost knob, OME-1116/OME-1240).
_EXPECTED_FAMILIES: dict[str, str] = {
    "gsm8k": "free_text",
    "mmlu": "mcq",
    "arc_easy": "mcq",
    "arc_challenge": "mcq",
    "commonsense_qa": "mcq",
    "mmlu_pro": "mcq",
    "winogrande": "mcq",
    "race_h": "mcq",
    "paws": "free_text",
    "boolq": "free_text",
    "aime24": "free_text",
    "aime25": "free_text",
    "musr": "mcq",
    "wmdp_bio": "mcq",
    "wmdp_chem": "mcq",
    "wmdp_cyber": "mcq",
    "hellaswag": "mcq",
    "frontierscience": "judged",
}

_NEW_KEYS: tuple[str, ...] = tuple(k for k in _EXPECTED_FAMILIES if k not in ("gsm8k", "mmlu"))


def test_catalogue_holds_every_imported_board() -> None:
    """OME-1116 acceptance: ≥10 imported boards; the row table IS the catalogue."""

    assert {spec.key for spec in BOARDS} == set(_EXPECTED_FAMILIES)
    assert set(SNAPSHOTS) == set(_EXPECTED_FAMILIES)
    ids = [registration.benchmark.id for registration in board_registrations()]
    assert len(ids) == len(set(ids)) == len(_EXPECTED_FAMILIES)
    assert all(board_id.startswith("inspect-") for board_id in ids)


def test_every_board_from_this_plugin_names_inspect_evals_as_its_source() -> None:
    """The catalogue must name the collection each board came FROM, not this repo.

    INVARIANT: `origin` defaults to "screamingface" (a true fact for boards authored
    here), so an import lane has to pass its own collection explicitly — the default is
    silently wrong for any board we merely brought in. The listing groups by this field,
    so a defaulted row makes the imported shelf disappear into our own group.

    Scope: `inspect_evals` is *this plugin's* source, not what "imported" means in
    general — a future collection arrives as its own plugin stamping its own origin,
    and would carry its own copy of this assertion. Asserted over the REAL
    registrations: a synthetic benchmark constructed with the origin passed by hand
    proves the wire format, never the board factory.
    """

    origins = {
        registration.benchmark.id: registration.benchmark.origin
        for registration in board_registrations()
    }
    assert set(origins.values()) == {"inspect_evals"}, origins


def test_board_revisions_are_distinct() -> None:
    """Two boards must never share a revision — the revision addresses the exam."""

    revisions = {imported_board(key).benchmark.revision for key in _EXPECTED_FAMILIES}
    assert len(revisions) == len(_EXPECTED_FAMILIES)


@pytest.mark.parametrize("key", sorted(_NEW_KEYS))
def test_snapshot_row_pins_exam_identity(key: str) -> None:
    snapshot = SNAPSHOTS[key]
    assert len(snapshot.dataset_revision) == 40
    int(snapshot.dataset_revision, 16)
    assert snapshot.case_count > 0
    assert snapshot.dataset and snapshot.split


@pytest.mark.parametrize("key", sorted(_NEW_KEYS))
def test_snapshot_row_references_resolve_inside_the_pinned_eval(key: str) -> None:
    """The rows POINT at the eval's own code; a dangling reference must fail CI,
    not the image build."""

    snapshot = SNAPSHOTS[key]
    references: list[str] = [snapshot.record_to_sample]
    if snapshot.prompt_template is not None:
        references.append(snapshot.prompt_template)
    if snapshot.choice_template is not None:
        references.append(snapshot.choice_template)
    if snapshot.system_message is not None:
        references.append(snapshot.system_message)
    for reference in references:
        module_name, _, attribute = reference.partition(":")
        assert hasattr(import_module(module_name), attribute), reference


@pytest.mark.parametrize("key", sorted(_NEW_KEYS))
def test_board_row_declares_its_family_check_surface(key: str) -> None:
    """OME-796: pass/fail feedback over a handful of options is an elimination
    attack — MCQ boards are refused the surface, free-text boards carry it."""

    board = imported_board(key).benchmark
    if _EXPECTED_FAMILIES[key] == "free_text":
        assert board.check_surface is not None
    else:
        # "mcq" (elimination attack) and "judged" (no check-cost knob yet) alike.
        assert board.check_surface is None


@pytest.mark.parametrize("key", sorted(_NEW_KEYS))
def test_board_row_scorer_resolves_and_constructs(key: str) -> None:
    spec = next(spec for spec in BOARDS if spec.key == key)
    module_name, _, attribute = spec.scorer.partition(":")
    constructor = getattr(import_module(module_name), attribute)
    assert constructor(**dict(spec.scorer_kwargs)) is not None


@pytest.mark.parametrize("key", sorted(_NEW_KEYS))
def test_board_row_prose_is_filled_not_todo(key: str) -> None:
    """AI-first onboarding: the importing agent writes the catalogue prose; a
    leftover TODO placeholder means the diff was never finished."""

    spec = next(spec for spec in BOARDS if spec.key == key)
    for prose in (spec.title, spec.description, spec.focus, spec.dataset_url):
        assert prose and "TODO" not in prose
    assert spec.dataset_url.startswith("https://huggingface.co/datasets/")


def test_boards_whose_eval_shuffles_carry_a_pinned_seed() -> None:
    """The upstream evals of these boards randomize exam order per run
    (hf_dataset shuffle=True); an import must pin one order — a dropped shuffle
    was the 2026-09-17 review blocker, and this set is its regression pin."""

    seeded: set[str] = {key for key, spec in SNAPSHOTS.items() if spec.shuffle_seed is not None}
    # aime24/aime25: OURS policy seed (owner-approved 2026-09-22) — upstream serves
    # dataset order (AIME I then II, roughly ascending difficulty within each), so an
    # unseeded import would give a limited run only the easier AIME I half.
    # musr: upstream shuffles per run (hf_dataset shuffle=True, no seed), so the
    # import pins one order. wmdp boards serve upstream order — no seed.
    # hellaswag: OURS policy seed (review finding on PR #1018) — the pinned
    # validation split is domain-grouped (3,243 ActivityNet rows then 6,799
    # WikiHow), so an unshuffled limit ≤ 3243 run would examine zero WikiHow.
    assert seeded == {
        "mmlu",
        "commonsense_qa",
        "mmlu_pro",
        "race_h",
        "paws",
        "boolq",
        "aime24",
        "aime25",
        "musr",
        "hellaswag",
        # frontierscience: mixed formats/subjects in dataset order — OURS policy
        # seed so a limited run spans both formats (sweep 2026-09-22, OME-1240).
        "frontierscience",
    }


def test_aime24_pin_tracks_upstreams_own_revision_constant() -> None:
    """The aime24 sha is COPIED from the eval's own pinned constant (upstream pins
    win at import time) — a dependency bump that moves upstream's pin must fail
    here instead of silently serving a different exam than the eval means."""

    from inspect_evals.aime2024.aime2024 import AIME2024_DATASET_REVISION

    from screamingface_engine_inspect.pins import AIME24_DATASET_REVISION

    assert AIME24_DATASET_REVISION == AIME2024_DATASET_REVISION


def test_aime25_pin_tracks_upstreams_own_revision_constant() -> None:
    """Same drift guard as aime24: the sha is copied from the eval's own pinned
    constant — a dependency bump that moves upstream's pin must fail here."""

    from inspect_evals.aime2025.aime2025 import AIME2025_DATASET_REVISION

    from screamingface_engine_inspect.pins import AIME25_DATASET_REVISION

    assert AIME25_DATASET_REVISION == AIME2025_DATASET_REVISION


def test_hellaswag_pin_tracks_upstreams_own_revision_constant() -> None:
    """Same drift guard as aime24/25: the sha is COPIED from the eval's own
    pinned constant — a dependency bump that moves upstream's pin must fail
    here, never leave us baking the old sha with the new scorer."""

    from inspect_evals.hellaswag.hellaswag import HELLASWAG_DATASET_REVISION as UPSTREAM

    from screamingface_engine_inspect.pins import HELLASWAG_DATASET_REVISION

    assert HELLASWAG_DATASET_REVISION == UPSTREAM


def test_system_message_pointer_rides_exam_identity() -> None:
    """Review finding on PR #1018: adding or dropping the leading instruction
    changes the exam a candidate sits, so the pointer must move the board's
    revision identity — a re-import that lost it cannot keep the revision."""

    from screamingface_engine_inspect.boards import _revision_pins

    pins = _revision_pins(SNAPSHOTS["hellaswag"])
    assert "system_message=inspect_evals.hellaswag.hellaswag:SYSTEM_MESSAGE" in pins
    # And a board without one carries no such pin (the field is conditional).
    assert not any(p.startswith("system_message=") for p in _revision_pins(SNAPSHOTS["musr"]))
