# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on, and with the extra installed
# these imports type-check normally.
"""The imported boards' asset snapshots — their formatting baked as data (spec §5.3).

INVARIANT the suite defends: prompt formatting reproduces the eval's own solver-chain
templates at bake time; the public booklet (``cases.json``) never carries a target;
the private ``targets/`` records hold exactly what the scorer shim needs (the target,
plus the choice texts for MCQ boards); and the mmlu shuffle is seeded — the baked
order is exam identity.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine_inspect.prepare import (  # noqa: E402
    SNAPSHOTS,
    PrepareError,
    SnapshotSpec,
    emit_snapshot,
    mcq_prompt,
)

_GSM8K_ROWS: list[dict[str, Any]] = [
    {"question": "What is 6 times 7?", "answer": "6 * 7 = 42\n#### 42"},
    {"question": "A train travels 30 km twice. Total?", "answer": "30 + 30 = 60\n#### 60"},
]

_MMLU_ROWS: list[dict[str, Any]] = [
    {"question": "Pick B.", "choices": ["no", "yes", "never", "maybe"], "answer": 1}
    | {"subject": "s"},
    {"question": "Pick A.", "choices": ["yes", "no", "never", "maybe"], "answer": 0}
    | {"subject": "s"},
    {"question": "Pick D.", "choices": ["no", "never", "maybe", "yes"], "answer": 3}
    | {"subject": "s"},
]


# ── gsm8k ────────────────────────────────────────────────────────────────────


def test_gsm8k_snapshot_bakes_their_template_and_the_private_target(
    tmp_path: Path,
) -> None:
    summary = emit_snapshot(SNAPSHOTS["gsm8k"], _GSM8K_ROWS, tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    assert [case["id"] for case in cases] == [1, 2]
    assert all(case["case_id"] == str(case["id"]) for case in cases)
    # Their MATH_PROMPT_TEMPLATE wraps the verbatim question (imported prompt = data).
    assert "What is 6 times 7?" in cases[0]["input"]
    assert "ANSWER: $ANSWER" in cases[0]["input"]
    # INVARIANT: the public booklet never carries the answer key.
    assert "42" not in json.dumps(cases)
    target = json.loads((tmp_path / "targets" / "1.json").read_text(encoding="utf-8"))
    # Their record_to_sample rule: the target is the text after "####", stripped.
    assert target == {"target": "42"}
    assert summary["cases"] == 2


def test_gsm8k_snapshot_refuses_a_row_without_a_target(tmp_path: Path) -> None:
    """An answer whose '####' tail is empty must fail the bake, not bake an unkeyed Case."""

    with pytest.raises(PrepareError, match="case 1"):
        emit_snapshot(
            SNAPSHOTS["gsm8k"], [{"question": "Q?", "answer": "reasoning ####   "}], tmp_path
        )


# ── mmlu ─────────────────────────────────────────────────────────────────────


def test_mcq_prompt_is_their_single_answer_template() -> None:
    prompt = mcq_prompt(_MMLU_ROWS[0]["question"], _MMLU_ROWS[0]["choices"])
    assert "ANSWER: $LETTER" in prompt
    assert "A) no" in prompt and "B) yes" in prompt and "D) maybe" in prompt
    assert "Pick B." in prompt


def test_mmlu_snapshot_bakes_letter_and_choices_privately(tmp_path: Path) -> None:
    emit_snapshot(SNAPSHOTS["mmlu"], _MMLU_ROWS, tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    assert len(cases) == 3
    targets = [
        json.loads((tmp_path / "targets" / f"{case['id']}.json").read_text(encoding="utf-8"))
        for case in cases
    ]
    for target in targets:
        assert target["target"] in "ABCD"
        assert len(target["choices"]) == 4
    # INVARIANT: the booklet carries prompts only — the key stays in targets/.
    assert "target" not in json.dumps(cases)


def test_mmlu_snapshot_shuffles_deterministically(tmp_path: Path) -> None:
    """INVARIANT: the seeded order is exam identity — same rows, same seed, same order."""

    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    emit_snapshot(SNAPSHOTS["mmlu"], _MMLU_ROWS, first_dir)
    emit_snapshot(SNAPSHOTS["mmlu"], _MMLU_ROWS, second_dir)
    first = (first_dir / "cases.json").read_text(encoding="utf-8")
    assert first == (second_dir / "cases.json").read_text(encoding="utf-8")
    # And the shuffle visibly leaves the subject-grouped dataset order.
    questions = [case["input"] for case in json.loads(first)]
    assert questions != [mcq_prompt(row["question"], row["choices"]) for row in _MMLU_ROWS]


def test_mmlu_snapshot_refuses_a_row_without_a_question(tmp_path: Path) -> None:
    """A malformed row fails the whole bake by case number, never a raw KeyError."""

    with pytest.raises(PrepareError, match="case 1"):
        emit_snapshot(
            SNAPSHOTS["mmlu"],
            [{"choices": ["a", "b", "c", "d"], "answer": 0, "subject": "s"}],
            tmp_path,
        )


def test_mmlu_snapshot_refuses_an_out_of_range_answer(tmp_path: Path) -> None:
    """The eval's own conversion blowing up on a bad row is a named bake failure."""

    row = {"question": "Q?", "choices": ["a", "b", "c", "d"], "answer": 9, "subject": "s"}
    with pytest.raises(PrepareError, match="case 1"):
        emit_snapshot(SNAPSHOTS["mmlu"], [row], tmp_path)


# ── exam-size and re-bake guards (shared by both boards) ─────────────────────


@pytest.mark.parametrize(("board", "rows"), [("gsm8k", _GSM8K_ROWS), ("mmlu", _MMLU_ROWS)])
def test_wrong_sized_dataset_refuses_the_bake(board: str, rows: Any, tmp_path: Path) -> None:
    """INVARIANT: the pinned case count is exam identity — a config/revision typo that
    yields the wrong number of rows (0 included) must fail loudly, never bake a
    smaller exam with a green build."""

    with pytest.raises(PrepareError, match="pinned case count"):
        emit_snapshot(SNAPSHOTS[board], rows, tmp_path, expected_cases=len(rows) + 1)


def test_rebake_into_a_used_directory_is_refused(tmp_path: Path) -> None:
    """INVARIANT: no orphan answer keys — a second bake into the same directory could
    leave stale targets/*.json from a previous, larger bake, so it is refused."""

    emit_snapshot(SNAPSHOTS["gsm8k"], _GSM8K_ROWS, tmp_path)
    with pytest.raises(PrepareError, match="non-empty"):
        emit_snapshot(SNAPSHOTS["gsm8k"], _GSM8K_ROWS, tmp_path)


# ── mutable-ref refusal (review round 2026-09-17 on the pin generator) ───────


def _spec_with_revision(revision: str) -> Any:
    from dataclasses import replace

    return replace(SNAPSHOTS["gsm8k"], dataset_revision=revision)


@pytest.mark.parametrize("mutable_ref", ["main", "refs/tags/v1.0", "HEAD", ""])
def test_bake_refuses_a_mutable_revision_ref(mutable_ref: str, tmp_path: Path) -> None:
    """INVARIANT: only a 40-hex commit sha is exam identity. A branch/tag ref would
    let upstream silently change a published board while its revision hash — built
    from the unchanging ref STRING — stayed the same."""

    with pytest.raises(PrepareError, match="commit sha"):
        emit_snapshot(_spec_with_revision(mutable_ref), _GSM8K_ROWS, tmp_path)


def test_board_assembly_refuses_a_mutable_revision_ref(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The same refusal fires at board-assembly time (CI), not only at image build —
    a mutable pin lands in a red test suite, never in a published catalogue."""

    from screamingface_engine_inspect import boards

    monkeypatch.setitem(SNAPSHOTS, "gsm8k", _spec_with_revision("main"))
    monkeypatch.setattr(boards, "_ASSEMBLED", {})
    with pytest.raises(PrepareError, match="commit sha"):
        boards.imported_board("gsm8k")


# ── custom choice template (the family renderer mmlu_pro / winogrande / race_h
#    force — OME-1116 milestone C) ────────────────────────────────────────────


def test_mcq_prompt_accepts_the_evals_own_template() -> None:
    """INVARIANT: a board whose eval passes a custom template to multiple_choice
    must render THAT template — the default SINGLE_ANSWER render would silently
    change the imported exam."""

    template = "Choose one of {letters}.\n{question}\n{choices}\nReply with the letter."
    prompt = mcq_prompt("Pick B.", ["no", "yes"], template=template)
    assert prompt.startswith("Choose one of A,B.")
    assert "Pick B." in prompt
    assert "A) no" in prompt and "B) yes" in prompt
    # The default render stays untouched when no template is given.
    assert "ANSWER: $LETTER" in mcq_prompt("Pick B.", ["no", "yes"])


def test_snapshot_with_choice_template_bakes_it(tmp_path: Path) -> None:
    """A SnapshotSpec pointing at the eval's own choice template renders through it."""

    from dataclasses import replace

    spec = replace(
        SNAPSHOTS["mmlu"],
        choice_template="inspect_evals.mmlu_pro.mmlu_pro:USER_PROMPT_TEMPLATE",
        shuffle_seed=None,
    )
    emit_snapshot(spec, _MMLU_ROWS[:1], tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    # mmlu_pro's own template carries its CoT instruction — absent from the
    # default SINGLE_ANSWER render the no-template path produces.
    assert "Think step by step before answering." in cases[0]["input"]
    assert "Pick B." in cases[0]["input"]
    assert "A) no" in cases[0]["input"]


# ── aime24 ───────────────────────────────────────────────────────────────────

_AIME24_ROWS: list[dict[str, Any]] = [
    {
        "ID": "2024-I-1",
        "Problem": "Find the sum of 3 and 4.",
        "Answer": 7,
        "Solution": "3 + 4 = 7.",
    },
    {
        "ID": "2024-I-2",
        "Problem": "Compute 10 times 10.",
        "Answer": 100,
        "Solution": "10 * 10 = 100.",
    },
]


def test_aime24_snapshot_bakes_the_shared_template_and_integer_target(
    tmp_path: Path,
) -> None:
    """OME-1238: the aime24 rows point at a template OUTSIDE the task module
    (utils.aime_common) and an integer answer the row rule stringifies — the bake
    must render the shared template verbatim and keep the key private."""

    summary = emit_snapshot(SNAPSHOTS["aime24"], _AIME24_ROWS, tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    # The spec's policy shuffle (seed 20260922) happens to leave a 2-row fixture
    # in place, so the assertions below still address rows by original order.
    assert [case["id"] for case in cases] == [1, 2]
    # Their USER_PROMPT_TEMPLATE wraps the verbatim problem (imported prompt = data).
    assert "Find the sum of 3 and 4." in cases[0]["input"]
    assert 'form "ANSWER: $ANSWER"' in cases[0]["input"]
    # INVARIANT: the public booklet never carries the answer key.
    assert "100" not in json.dumps(cases)
    target = json.loads((tmp_path / "targets" / "1.json").read_text(encoding="utf-8"))
    # Their record_to_sample rule: target=str(record["Answer"]).
    assert target == {"target": "7"}
    assert summary["cases"] == 2


# ── aime25 ───────────────────────────────────────────────────────────────────

_AIME25_ROWS: list[dict[str, Any]] = [
    {"id": "2025-I-1", "problem": "Find the sum of 5 and 6.", "answer": "11"},
    {"id": "2025-I-2", "problem": "Compute 20 times 20.", "answer": "400"},
]


def test_aime25_snapshot_bakes_their_row_rule_and_private_target(
    tmp_path: Path,
) -> None:
    """OME-1238: aime25's row rule uses lowercase field names and a string
    answer (unlike aime24's uppercase fields + integer answer) — the bake must
    read the right fields and keep the key private."""

    summary = emit_snapshot(SNAPSHOTS["aime25"], _AIME25_ROWS, tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    # The spec's policy shuffle (seed 20260922) happens to leave a 2-row fixture
    # in place, so the assertions below still address rows by original order.
    assert [case["id"] for case in cases] == [1, 2]
    # The shared USER_PROMPT_TEMPLATE wraps the verbatim problem.
    assert "Find the sum of 5 and 6." in cases[0]["input"]
    assert 'form "ANSWER: $ANSWER"' in cases[0]["input"]
    # INVARIANT: the public booklet never carries the answer key.
    assert "400" not in json.dumps(cases)
    target = json.loads((tmp_path / "targets" / "2.json").read_text(encoding="utf-8"))
    assert target == {"target": "400"}
    assert summary["cases"] == 2


# ── musr ─────────────────────────────────────────────────────────────────────

_MUSR_ROWS: list[dict[str, Any]] = [
    {
        "narrative": "A short mystery story.",
        "question": "Who did it?",
        "choices": "['The butler', 'The gardener']",
        "answer_index": 1,
    },
    {
        "narrative": "Another short mystery.",
        "question": "Who is guilty?",
        "choices": "['Alice', 'Bob']",
        "answer_index": 0,
    },
]


def test_musr_snapshot_parses_stringified_choices_and_their_template(
    tmp_path: Path,
) -> None:
    """OME-1253: musr stores choices as a STRINGIFIED Python list its row rule
    ast.literal_eval's, and the prompt is the eval's own REGULAR_PROMPT — the
    bake must parse the choices into real options and render that template,
    keeping the key private."""

    summary = emit_snapshot(SNAPSHOTS["musr"], _MUSR_ROWS, tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    # The spec's policy shuffle (seed 20260922) happens to leave a 2-row fixture
    # in place, so the assertions below still address rows by original order.
    assert [case["id"] for case in cases] == [1, 2]
    # Narrative and question are joined, choices rendered as lettered options.
    assert "A short mystery story.\n\nWho did it?" in cases[0]["input"]
    assert "A) The butler" in cases[0]["input"] and "B) The gardener" in cases[0]["input"]
    # REGULAR_PROMPT's own answer-format instruction, not our MCQ default.
    assert "ANSWER: (your answer here, include the choice letter)" in cases[0]["input"]
    # INVARIANT: the public booklet never carries the answer key.
    assert "target" not in json.dumps(cases)
    target = json.loads((tmp_path / "targets" / "1.json").read_text(encoding="utf-8"))
    assert target == {"target": "B", "choices": ["The butler", "The gardener"]}
    assert summary["cases"] == 2


# ── wmdp ─────────────────────────────────────────────────────────────────────

_WMDP_ROWS: list[dict[str, Any]] = [
    {"question": "Pick B.", "choices": ["no", "yes", "never", "maybe"], "answer": 1},
    {"question": "Pick A.", "choices": ["yes", "no", "never", "maybe"], "answer": 0},
]


def test_wmdp_snapshot_bakes_letter_target_in_upstream_order(tmp_path: Path) -> None:
    """OME-1253: wmdp's row rule maps an integer answer index to a letter and
    the eval serves upstream order (no shuffle, no seed) — the bake must keep
    both, with the key private. One config stands for all three: the wmdp_*
    snapshots share record_to_sample and differ only in pins."""

    summary = emit_snapshot(SNAPSHOTS["wmdp_bio"], _WMDP_ROWS, tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    # No shuffle seed: rows keep the upstream order.
    assert [case["id"] for case in cases] == [1, 2]
    assert "Pick B." in cases[0]["input"]
    assert "A) no" in cases[0]["input"] and "D) maybe" in cases[0]["input"]
    # INVARIANT: the public booklet never carries the answer key.
    assert "target" not in json.dumps(cases)
    target = json.loads((tmp_path / "targets" / "1.json").read_text(encoding="utf-8"))
    assert target == {"target": "B", "choices": ["no", "yes", "never", "maybe"]}
    assert summary["cases"] == 2


# ── system message as leading input text ─────────────────────────────────────


def test_snapshot_with_system_message_bakes_it_as_leading_input_text(
    tmp_path: Path,
) -> None:
    """OME-1253: a benchmark cannot address a candidate's system role, so an
    eval's system instruction is delivered as the LEADING TEXT of the candidate
    input (contracteval precedent) — stripped, once, ahead of the untouched
    render — and it never leaks into the private targets."""

    spec = SnapshotSpec(
        dataset="acme/sums",
        config="",
        split="test",
        dataset_revision="deadbeef" * 5,
        case_count=2,
        record_to_sample="inspect_evals.wmdp.wmdp:record_to_sample",
        system_message="inspect_evals.hellaswag.hellaswag:SYSTEM_MESSAGE",
    )
    emit_snapshot(spec, _WMDP_ROWS, tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    # Leading text: the eval's instruction (stripped of its surrounding
    # newlines), a blank line, then the normal MCQ render.
    assert cases[0]["input"].startswith("Choose the most plausible continuation for the story.\n\n")
    assert "A) no" in cases[0]["input"] and "Pick B." in cases[0]["input"]
    target = json.loads((tmp_path / "targets" / "1.json").read_text(encoding="utf-8"))
    assert target == {"target": "B", "choices": ["no", "yes", "never", "maybe"]}


# ── hellaswag ────────────────────────────────────────────────────────────────

_HELLASWAG_ROWS: list[dict[str, Any]] = [
    {
        "ctx": "She cracks the eggs into a bowl and",
        "endings": ["whisks them.", "paints the wall.", "drives away.", "sings."],
        "label": "0",
        "source_id": "activitynet~v_1",
    },
    {
        "ctx": "He laces up his running shoes and",
        "endings": ["eats the laces.", "heads out the door.", "melts.", "sleeps."],
        "label": "1",
        "source_id": "activitynet~v_2",
    },
]


def test_hellaswag_snapshot_leads_with_their_instruction(tmp_path: Path) -> None:
    """OME-1253 (owner-approved): hellaswag's task instruction lives in a SYSTEM
    message upstream; the board delivers it as the input's leading text (named
    deviation — a benchmark cannot address a candidate's system role), ahead of
    the untouched MCQ render, with the key private."""

    summary = emit_snapshot(SNAPSHOTS["hellaswag"], _HELLASWAG_ROWS, tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    # The spec's policy shuffle (seed 20260922, domain-grouped split) happens to
    # leave a 2-row fixture in place, so assertions address rows by original order.
    assert [case["id"] for case in cases] == [1, 2]
    assert cases[0]["input"].startswith("Choose the most plausible continuation for the story.\n\n")
    assert "She cracks the eggs into a bowl and" in cases[0]["input"]
    assert "A) whisks them." in cases[0]["input"]
    # INVARIANT: the public booklet never carries the answer key.
    assert "target" not in json.dumps(cases)
    target = json.loads((tmp_path / "targets" / "2.json").read_text(encoding="utf-8"))
    assert target["target"] == "B" and target["choices"][1] == "heads out the door."
    assert summary["cases"] == 2


def test_system_message_resolving_to_a_non_string_refuses_the_bake(
    tmp_path: Path,
) -> None:
    """Review finding on PR #1018: a mispointed system_message landing on a
    function must refuse the bake — str() would silently bake its repr into
    every case of the exam."""

    from dataclasses import replace

    spec = replace(
        SNAPSHOTS["hellaswag"],
        # A real module attribute that is a function, not text.
        system_message="inspect_evals.hellaswag.hellaswag:record_to_sample",
    )
    with pytest.raises(PrepareError, match="must resolve to text"):
        emit_snapshot(spec, _HELLASWAG_ROWS, tmp_path)
