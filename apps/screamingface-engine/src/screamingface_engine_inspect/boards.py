"""The plugin's board table — every imported benchmark is a ROW here, never a file.

A board is two data rows: its :class:`~screamingface_engine_inspect.prepare.SnapshotSpec`
(dataset pins, in ``prepare.SNAPSHOTS``) and its :class:`BoardSpec` below (catalogue
metadata + a dotted reference to the eval's own scorer). One generic assembler turns
the pair into a registered board, so importing benchmark #13 adds two rows and zero
functions (owner decision 2026-09-16; OME-1115's per-file boards #955/#956 were closed
unmerged in favor of this).

Imported ONLY behind :func:`screamingface_engine_inspect.deployment.inspect_available`,
and every inspect import below is lazy, so the module itself stays extra-free.

STORY: as a researcher, I run a fusion (or a corrective_loop) against a benchmark we
never hand-built, from the same notebook as any home-grown board.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from importlib import import_module
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.deployment import BenchmarkRegistration
from screamingface_engine_inspect.prepare import (
    SNAPSHOTS,
    SnapshotSpec,
    prepare_snapshot,
    require_commit_sha,
)
from screamingface_engine_inspect.single_shot import (
    ImportedBoard,
    install_imported_board,
    single_shot_board,
)
from url4.peer.server import Url4Node


@dataclass(frozen=True)
class BoardSpec:
    """One imported board's catalogue row — pure data, paired with its SnapshotSpec.

    ``scorer`` is a dotted ``"module:attr"`` reference to the eval's own scorer
    constructor (the same convention SnapshotSpec uses for ``record_to_sample``),
    called with ``scorer_kwargs`` — provenance lives in the row, resolution is lazy.
    """

    key: str
    title: str
    description: str
    focus: str
    dataset_url: str
    scorer: str
    scorer_kwargs: Mapping[str, Any] = field(default_factory=dict)
    #: §4 dual registration; False for MCQ boards — pass/fail feedback over a
    #: handful of options is an elimination attack (OME-796).
    with_check_surface: bool = False
    multiple_correct: bool = False


#: Every imported board, in catalogue order. Importing another eval = one row here
#: plus its SnapshotSpec row — never a new module.
BOARDS: tuple[BoardSpec, ...] = (
    BoardSpec(
        key="gsm8k",
        title="GSM8K",
        description=(
            "1,319 grade-school math word problems (the GSM8K test split), imported "
            "from inspect_evals. The model reasons step by step and commits a final "
            "numeric answer; grading is inspect's own numeric match against the "
            "published solution, so no judge tokens are spent. Benchmark score = "
            "plain accuracy over the cases run."
        ),
        focus="Grade-school math word problems",
        dataset_url="https://huggingface.co/datasets/openai/gsm8k",
        # Provenance: inspect_evals.gsm8k.gsm8k's Task declares scorer=match(numeric=True).
        scorer="inspect_ai.scorer:match",
        scorer_kwargs={"numeric": True},
        # Free-form answers make mid-run feedback legitimate: the same scorer serves
        # the corrective loop (spec §4; owner decision on OME-1115, 2026-09-15).
        with_check_surface=True,
    ),
    BoardSpec(
        key="mmlu",
        title="MMLU",
        description=(
            "14,042 multiple-choice questions across 57 subjects (the MMLU test "
            "split, 0-shot), imported from inspect_evals. The model answers with one "
            "lettered choice; grading is inspect's own choice scorer against the "
            "published key, so no judge tokens are spent. Cases are served in a "
            "fixed seeded shuffle so a limited run spans subjects. Benchmark score = "
            "plain accuracy over the cases run. No mid-run check surface: pass/fail "
            "feedback over four options would let a loop eliminate choices rather "
            "than improve answers."
        ),
        focus="Broad multi-subject knowledge (multiple choice)",
        dataset_url="https://huggingface.co/datasets/cais/mmlu",
        # Provenance: inspect_evals.mmlu.mmlu's Task declares scorer=choice().
        scorer="inspect_ai.scorer:choice",
    ),
    BoardSpec(
        key="arc_easy",
        title="ARC-Easy",
        description=(
            "2,376 grade-school science multiple-choice questions (the AI2 ARC "
            "Easy test split), imported from inspect_evals. The model answers "
            "with one lettered choice; grading is inspect's own choice scorer "
            "against the published key, so no judge tokens are spent. Benchmark "
            "score = plain accuracy over the cases run. No mid-run check surface: "
            "pass/fail feedback over a handful of options would let a loop "
            "eliminate choices rather than improve answers."
        ),
        focus="Grade-school science (multiple choice)",
        dataset_url="https://huggingface.co/datasets/allenai/ai2_arc",
        # Provenance: this scorer is declared by the Task of
        #   inspect_evals.arc.arc:arc_easy. License: cc-by-sa-4.0.
        scorer="inspect_ai.scorer:choice",
    ),
    BoardSpec(
        key="arc_challenge",
        title="ARC-Challenge",
        description=(
            "1,172 hard grade-school science questions (the AI2 ARC Challenge "
            "test split — the subset both retrieval and word co-occurrence "
            "baselines get wrong), imported from inspect_evals. The model "
            "answers with one lettered choice; grading is inspect's own choice "
            "scorer against the published key, so no judge tokens are spent. "
            "Benchmark score = plain accuracy over the cases run. No mid-run "
            "check surface (elimination attack over few options)."
        ),
        focus="Hard science reasoning (multiple choice)",
        dataset_url="https://huggingface.co/datasets/allenai/ai2_arc",
        # Provenance: this scorer is declared by the Task of
        #   inspect_evals.arc.arc:arc_challenge. License: cc-by-sa-4.0.
        scorer="inspect_ai.scorer:choice",
    ),
    BoardSpec(
        key="commonsense_qa",
        title="CommonsenseQA",
        description=(
            "1,221 five-option questions built from ConceptNet relations, each "
            "needing everyday commonsense to separate the answer from four "
            "distractors (the CommonsenseQA validation split — test answers are "
            "withheld upstream), imported from inspect_evals. Grading is "
            "inspect's own choice scorer against the published key; benchmark "
            "score = plain accuracy over the cases run, served in a fixed seeded "
            "shuffle (the upstream eval randomizes order per run). No mid-run "
            "check surface (elimination attack over few options)."
        ),
        focus="Everyday commonsense reasoning (multiple choice)",
        dataset_url="https://huggingface.co/datasets/tau/commonsense_qa",
        # Provenance: this scorer is declared by the Task of
        #   inspect_evals.commonsense_qa.commonsense_qa:commonsense_qa. License: mit.
        scorer="inspect_ai.scorer:choice",
    ),
    BoardSpec(
        key="paws",
        title="PAWS",
        description=(
            "8,000 sentence pairs asking whether aggressive word reordering "
            "preserved the meaning (the PAWS labeled_final test split), imported "
            "from inspect_evals. The model answers Yes or No through the eval's "
            "own prompt template; grading is inspect's own includes scorer "
            "against the published label, so no judge tokens are spent. Cases are "
            "served in a fixed seeded shuffle (the upstream eval randomizes "
            "order per run); benchmark score = plain accuracy over the cases "
            "run. Free-form replies make the mid-run check surface legitimate "
            "(corrective loop)."
        ),
        focus="Paraphrase adjudication (yes/no)",
        dataset_url="https://huggingface.co/datasets/google-research-datasets/paws",
        # Provenance: this scorer is declared by the Task of
        #   inspect_evals.paws.paws:paws. License: other.
        scorer="inspect_ai.scorer:includes",
        # Free-form answers make mid-run feedback legitimate (spec §4);
        # MCQ boards must NOT set this (OME-796).
        with_check_surface=True,
    ),
    BoardSpec(
        key="boolq",
        title="BoolQ",
        description=(
            "3,270 naturally-occurring yes/no questions, each answered from a "
            "given Wikipedia passage (the BoolQ validation split — test answers "
            "are withheld upstream), imported from inspect_evals. Grading is "
            "inspect's own pattern scorer over the reply's final Yes/No, so no "
            "judge tokens are spent. Cases are served in a fixed seeded shuffle "
            "(the upstream eval randomizes order per run); benchmark score = "
            "plain accuracy over the cases run. Free-form replies make the "
            "mid-run check surface legitimate (corrective loop)."
        ),
        focus="Yes/no reading comprehension",
        dataset_url="https://huggingface.co/datasets/google/boolq",
        # Provenance: this scorer is declared by the Task of
        #   inspect_evals.boolq.boolq:boolq. License: cc-by-sa-3.0.
        scorer="inspect_ai.scorer:pattern",
        scorer_kwargs={"pattern": "(Yes|No).?\\Z"},
        # Free-form answers make mid-run feedback legitimate (spec §4);
        # MCQ boards must NOT set this (OME-796).
        with_check_surface=True,
    ),
    BoardSpec(
        key="mmlu_pro",
        title="MMLU-Pro",
        description=(
            "12,032 ten-option questions across 14 disciplines (the MMLU-Pro "
            "test split), imported from inspect_evals. Prompts render through "
            "the eval's own chain-of-thought template; grading is inspect's own "
            "choice scorer against the published key, so no judge tokens are "
            "spent. Cases are served in a fixed seeded shuffle so a limited run "
            "spans disciplines. Benchmark score = plain accuracy over the cases "
            "run. No mid-run check surface (elimination attack over options)."
        ),
        focus="Harder multi-discipline knowledge, ten options (multiple choice)",
        dataset_url="https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro",
        # Provenance: this scorer is declared by the Task of
        #   inspect_evals.mmlu_pro.mmlu_pro:mmlu_pro. License: mit.
        scorer="inspect_ai.scorer:choice",
    ),
    BoardSpec(
        key="winogrande",
        title="WinoGrande",
        description=(
            "1,267 sentences where a [BLANK] must be resolved to one of two "
            "candidates using commonsense about the situation (the WinoGrande "
            "XL validation split, 0-shot), imported from inspect_evals. Prompts "
            "render through the eval's own template; grading is inspect's own "
            "choice scorer against the published key, so no judge tokens are "
            "spent. Benchmark score = plain accuracy over the cases run. No "
            "mid-run check surface: pass/fail feedback over two options is a "
            "coin-flip oracle (OME-796)."
        ),
        focus="Commonsense pronoun resolution (binary choice)",
        dataset_url="https://huggingface.co/datasets/allenai/winogrande",
        # Provenance: this scorer is declared by the Task of
        #   inspect_evals.winogrande.winogrande:winogrande. License: UNKNOWN.
        scorer="inspect_ai.scorer:choice",
    ),
    BoardSpec(
        key="race_h",
        title="RACE-H",
        description=(
            "3,498 reading-comprehension questions over English-exam passages "
            "written for Chinese high-school students (the RACE high test "
            "split), imported from inspect_evals. Each prompt renders the "
            "passage and question through the eval's own template; grading is "
            "inspect's own choice scorer against the published key, so no judge "
            "tokens are spent. Cases are served in a fixed seeded shuffle so a "
            "limited run spans passages. Benchmark score = plain accuracy over "
            "the cases run. No mid-run check surface (elimination attack)."
        ),
        focus="Long-passage reading comprehension (multiple choice)",
        dataset_url="https://huggingface.co/datasets/ehovy/race",
        # Provenance: this scorer is declared by the Task of
        #   inspect_evals.race_h.race_h:race_h. License: other.
        scorer="inspect_ai.scorer:choice",
    ),
    BoardSpec(
        key="aime24",
        title="AIME 2024",
        description=(
            "All 30 problems of the 2024 American Invitational Mathematics "
            "Examination (AIME I and II), imported from inspect_evals. Every "
            "answer is an integer from 0 to 999; the model solves step by step "
            "and commits its final answer on a closing 'ANSWER:' line. Grading "
            "is the eval's own scorer — a numeric match of the reply's final "
            "line against the answer key — so no judge tokens are spent. Cases "
            "are served in a fixed seeded shuffle so a limited run spans both "
            "exams and the difficulty range. Benchmark score = plain accuracy "
            "over the cases run. Free-form replies make the mid-run check "
            "surface legitimate (corrective loop)."
        ),
        focus="Competition mathematics (AIME 2024)",
        dataset_url="https://huggingface.co/datasets/Maxwell-Jia/AIME_2024",
        # Provenance: this scorer is declared by the Task of
        #   inspect_evals.aime2024.aime2024:aime2024.
        # License: mit.
        scorer="inspect_evals.aime2024.aime2024:aime_scorer",
        # Free-form answers make mid-run feedback legitimate (spec §4);
        # MCQ boards must NOT set this (OME-796).
        with_check_surface=True,
    ),
    BoardSpec(
        key="aime25",
        title="AIME 2025",
        description=(
            "All 30 problems of the 2025 American Invitational Mathematics "
            "Examination (AIME I and II), imported from inspect_evals. Every "
            "answer is an integer from 0 to 999; the model solves step by step "
            "and commits its final answer on a closing 'ANSWER:' line. Grading "
            "is the eval's own scorer — a numeric match of the reply's final "
            "line against the answer key — so no judge tokens are spent. Cases "
            "are served in a fixed seeded shuffle so a limited run spans both "
            "exams and the difficulty range. Benchmark score = plain accuracy "
            "over the cases run. Free-form replies make the mid-run check "
            "surface legitimate (corrective loop)."
        ),
        focus="Competition mathematics (AIME 2025)",
        dataset_url="https://huggingface.co/datasets/math-ai/aime25",
        # Provenance: this scorer is declared by the Task of
        #   inspect_evals.aime2025.aime2025:aime2025.
        # License: apache-2.0.
        scorer="inspect_evals.aime2025.aime2025:aime_scorer",
        # Free-form answers make mid-run feedback legitimate (spec §4);
        # MCQ boards must NOT set this (OME-796).
        with_check_surface=True,
    ),
    BoardSpec(
        key="musr",
        title="MuSR",
        description=(
            "250 machine-generated murder mysteries (the MuSR murder_mysteries "
            "split — the upstream eval's default domain), each a ~1,000-word "
            "narrative whose whodunit question takes multi-step soft reasoning "
            "over the story, imported from inspect_evals. The model picks a "
            "suspect through the eval's own choice prompt; grading is inspect's "
            "own choice scorer against the published key, so no judge tokens "
            "are spent. Cases are served in a fixed seeded shuffle (the "
            "upstream eval randomizes order per run); benchmark score = plain "
            "accuracy over the cases run. No mid-run check surface "
            "(elimination attack over few options)."
        ),
        focus="Long-narrative multi-step reasoning (multiple choice)",
        dataset_url="https://huggingface.co/datasets/TAUR-Lab/MuSR",
        # Provenance: this scorer is declared by the Task of
        #   inspect_evals.musr.musr:musr.
        # License: cc-by-4.0.
        scorer="inspect_ai.scorer:choice",
    ),
    BoardSpec(
        key="wmdp_bio",
        title="WMDP-Bio",
        description=(
            "1,273 four-option questions probing hazardous biosecurity "
            "knowledge (the WMDP wmdp-bio test split), written by experts as a "
            "proxy measure of weapons-of-mass-destruction-relevant capability, "
            "imported from inspect_evals. Grading is inspect's own choice "
            "scorer against the published key, so no judge tokens are spent; "
            "cases are served in the upstream order (the eval does not "
            "shuffle); benchmark score = plain accuracy over the cases run. No "
            "mid-run check surface (elimination attack over few options)."
        ),
        focus="Hazardous biosecurity knowledge probe (multiple choice)",
        dataset_url="https://huggingface.co/datasets/cais/wmdp",
        # Provenance: this scorer is declared by the Task of
        #   inspect_evals.wmdp.wmdp:wmdp_bio.
        # License: mit.
        scorer="inspect_ai.scorer:choice",
    ),
    BoardSpec(
        key="wmdp_chem",
        title="WMDP-Chem",
        description=(
            "408 four-option questions probing hazardous chemical-security "
            "knowledge (the WMDP wmdp-chem test split), written by experts as "
            "a proxy measure of weapons-of-mass-destruction-relevant "
            "capability, imported from inspect_evals. Grading is inspect's own "
            "choice scorer against the published key, so no judge tokens are "
            "spent; cases are served in the upstream order (the eval does not "
            "shuffle); benchmark score = plain accuracy over the cases run. No "
            "mid-run check surface (elimination attack over few options)."
        ),
        focus="Hazardous chemical-security knowledge probe (multiple choice)",
        dataset_url="https://huggingface.co/datasets/cais/wmdp",
        # Provenance: this scorer is declared by the Task of
        #   inspect_evals.wmdp.wmdp:wmdp_chem.
        # License: mit.
        scorer="inspect_ai.scorer:choice",
    ),
    BoardSpec(
        key="wmdp_cyber",
        title="WMDP-Cyber",
        description=(
            "1,987 four-option questions probing hazardous cybersecurity "
            "knowledge (the WMDP wmdp-cyber test split), written by experts as "
            "a proxy measure of weapons-of-mass-destruction-relevant "
            "capability, imported from inspect_evals. Grading is inspect's own "
            "choice scorer against the published key, so no judge tokens are "
            "spent; cases are served in the upstream order (the eval does not "
            "shuffle); benchmark score = plain accuracy over the cases run. No "
            "mid-run check surface (elimination attack over few options)."
        ),
        focus="Hazardous cybersecurity knowledge probe (multiple choice)",
        dataset_url="https://huggingface.co/datasets/cais/wmdp",
        # Provenance: this scorer is declared by the Task of
        #   inspect_evals.wmdp.wmdp:wmdp_cyber.
        # License: mit.
        scorer="inspect_ai.scorer:choice",
    ),
    BoardSpec(
        key="hellaswag",
        title="HellaSwag",
        description=(
            "10,042 everyday scenarios (the HellaSwag validation split — test "
            "labels are withheld upstream), each a story context with four "
            "candidate continuations where only one is plausible; the wrong "
            "ones are adversarially machine-generated, imported from "
            "inspect_evals. One named deviation: the eval sends its task "
            "instruction ('Choose the most plausible continuation for the "
            "story.') as a system message, while this board delivers it as the "
            "leading text of the candidate input, because a benchmark cannot "
            "address a candidate's system role. Grading is inspect's own "
            "choice scorer against the published key, so no judge tokens are "
            "spent; cases are served in the upstream order (the eval does not "
            "shuffle by default); benchmark score = plain accuracy over the "
            "cases run. No mid-run check surface (elimination attack over few "
            "options)."
        ),
        focus="Commonsense sentence continuation (multiple choice)",
        dataset_url="https://huggingface.co/datasets/Rowan/hellaswag",
        # Provenance: this scorer is declared by the Task of
        #   inspect_evals.hellaswag.hellaswag:hellaswag.
        # License: UNKNOWN on the HF card; MIT per the upstream source repo
        # (owner-approved 2026-09-22 — see pins.py).
        scorer="inspect_ai.scorer:choice",
    ),
    # --- importer: generated BoardSpec rows land above this line ---
)


def imported_board(key: str) -> ImportedBoard:
    """The assembled board for one table row — assembled once, then cached."""

    if key not in _ASSEMBLED:
        specs: dict[str, BoardSpec] = {spec.key: spec for spec in BOARDS}
        if key not in specs:
            raise KeyError(f"no imported board row with key {key!r}")
        _ASSEMBLED[key] = _assemble(specs[key])
    return _ASSEMBLED[key]


def board_registrations() -> tuple[BenchmarkRegistration, ...]:
    """Every imported board, in catalogue order — the plugin's entry-point payload."""

    return tuple(imported_board(spec.key).registration for spec in BOARDS)


def _assemble(spec: BoardSpec) -> ImportedBoard:
    """Row pair in, registered board out — the whole per-board 'code' path."""

    snapshot: SnapshotSpec = SNAPSHOTS[spec.key]
    return single_shot_board(
        board_key=spec.key,
        title=spec.title,
        description=spec.description,
        focus=spec.focus,
        dataset_url=spec.dataset_url,
        case_count=snapshot.case_count,
        revision_pins=_revision_pins(snapshot),
        scorer_factory=_scorer_factory(spec),
        prepare=partial(prepare_snapshot, snapshot),
        install=_installer(f"inspect-{spec.key}"),
        with_check_surface=spec.with_check_surface,
        multiple_correct=spec.multiple_correct,
    )


def _revision_pins(snapshot: SnapshotSpec) -> tuple[str, ...]:
    """Exam-identity pins derived from the board's snapshot row — never duplicated."""

    pins: list[str] = [
        snapshot.dataset,
        snapshot.config,
        snapshot.split,
        # Assembly-time backstop: a mutable ref must never become exam identity.
        require_commit_sha(snapshot.dataset_revision),
    ]
    if snapshot.shuffle_seed is not None:
        pins.append(f"shuffle_seed={snapshot.shuffle_seed}")
    return tuple(pins)


def _scorer_factory(spec: BoardSpec) -> Callable[[], Any]:
    """Resolve the eval's own scorer from the row's dotted reference, lazily."""

    def factory() -> Any:
        module_name, _, attribute = spec.scorer.partition(":")
        constructor: Any = getattr(import_module(module_name), attribute)
        return constructor(**dict(spec.scorer_kwargs))

    return factory


def _installer(benchmark_id: str) -> Callable[[Url4Node, Path], None]:
    """One installer per board, carrying the bundle id ON the function.

    WHY the attribute: the deployment conformance check reads the asset directory a
    board's installer actually opens from the installer itself; with boards as rows
    in ONE module, a per-module ``ASSET_BUNDLE_ID`` constant cannot work, so the
    installer function carries it (owner-approved conformance-rule amendment,
    2026-09-16).
    """

    def install(node: Url4Node, assets: Path) -> None:
        install_imported_board(node, assets, benchmark_id)

    install.ASSET_BUNDLE_ID = benchmark_id  # type: ignore[attr-defined]
    return install


_ASSEMBLED: dict[str, ImportedBoard] = {}


__all__ = ["BOARDS", "BoardSpec", "board_registrations", "imported_board"]
