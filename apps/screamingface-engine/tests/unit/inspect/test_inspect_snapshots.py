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


def _inspects_own_choice_shuffle(
    spec: SnapshotSpec, rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[Any]]:
    """The expected bake, computed through inspect's OWN mechanism: the
    row-shuffled rows and their choice-shuffled Samples, in baked case order."""

    import random
    from importlib import import_module

    from inspect_ai.dataset import MemoryDataset

    ordered = list(rows)
    if spec.shuffle_seed is not None:
        random.Random(spec.shuffle_seed).shuffle(ordered)
    module_name, _, attribute = spec.record_to_sample.partition(":")
    record_to_sample = getattr(import_module(module_name), attribute)
    samples = [record_to_sample(row) for row in ordered]
    MemoryDataset(samples).shuffle_choices(seed=spec.choice_shuffle_seed)
    return ordered, samples


def test_choice_shuffle_bakes_inspects_own_order_and_remaps_the_target(tmp_path: Path) -> None:
    """INVARIANT: a pinned choice_shuffle_seed applies inspect's OWN choice
    shuffle over THE BAKE'S pinned row order — one random stream across the
    whole dataset, target letter remapped.

    Scope of the claim (review blocker on PR #1031): the expected values below
    replay the bake's own Python row shuffle, so this test pins that the CHOICE
    stage is inspect's mechanism over our row order — not that the combined
    result matches what inspect would produce for the same seeds (it doesn't
    when a row shuffle is active; the importer refuses that combination for
    upstream-seeded evals, and ``test_hf_row_shuffle_is_not_pythons_row_shuffle``
    is the witness)."""

    from dataclasses import replace

    spec = replace(SNAPSHOTS["mmlu"], choice_shuffle_seed=7)
    emit_snapshot(spec, _MMLU_ROWS, tmp_path)
    ordered, samples = _inspects_own_choice_shuffle(spec, _MMLU_ROWS)

    shuffled_any = False
    for case_id, (row, sample) in enumerate(zip(ordered, samples, strict=True), start=1):
        baked = json.loads((tmp_path / "targets" / f"{case_id}.json").read_text(encoding="utf-8"))
        assert baked["choices"] == [str(choice) for choice in sample.choices or []]
        assert baked["target"] == sample.target
        # Grading identity conserved: the baked letter still keys the row's own
        # correct answer text, wherever the shuffle moved it.
        assert baked["choices"][ord(baked["target"]) - ord("A")] == row["choices"][row["answer"]]
        shuffled_any = shuffled_any or baked["choices"] != row["choices"]
    # And the shuffle visibly reordered at least one case (seed 7 does, pinned).
    assert shuffled_any


def test_choice_shuffle_failure_is_a_named_bake_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bake's failure contract is uniform: eval code blowing up inside
    inspect's choice shuffle (a non-letter target meeting the letter remap) must
    surface as a PrepareError naming the stage, never a raw TypeError (review
    finding on PR #1031)."""

    import sys
    import types

    from inspect_ai.dataset import Sample

    def bad_target_sample(row: dict[str, Any]) -> Sample:
        return Sample(input="q", target="yes", choices=["a", "b"])

    module = types.ModuleType("fake_bake_eval")
    module.bad_target_sample = bad_target_sample  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fake_bake_eval", module)
    spec = SnapshotSpec(
        dataset="acme/quiz",
        config="",
        split="test",
        dataset_revision="c" * 40,
        case_count=1,
        record_to_sample="fake_bake_eval:bad_target_sample",
        choice_shuffle_seed=7,
    )

    with pytest.raises(PrepareError, match="choice shuffle"):
        emit_snapshot(spec, [{"q": "?"}], tmp_path)


def test_choice_shuffled_bake_is_deterministic(tmp_path: Path) -> None:
    """INVARIANT: the pinned choice order is exam identity — same rows, same
    seed, byte-identical assets across bakes (OME-1264)."""

    from dataclasses import replace

    spec = replace(SNAPSHOTS["mmlu"], choice_shuffle_seed=7)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    emit_snapshot(spec, _MMLU_ROWS, first_dir)
    emit_snapshot(spec, _MMLU_ROWS, second_dir)

    assert (first_dir / "cases.json").read_text(encoding="utf-8") == (
        second_dir / "cases.json"
    ).read_text(encoding="utf-8")
    assert (first_dir / "targets" / "1.json").read_text(encoding="utf-8") == (
        second_dir / "targets" / "1.json"
    ).read_text(encoding="utf-8")


def test_hf_row_shuffle_is_not_pythons_row_shuffle() -> None:
    """The witness behind the importer's combined-shuffle refusal (review blocker
    on PR #1031): upstream shuffles rows with HF's ``Dataset.shuffle(seed)``, the
    bake with ``random.Random(seed)`` — same seed, DIFFERENT order. The choice
    shuffle draws each case's permutation from one stream in row order, so an
    upstream-seeded exam combined with any row shuffle cannot be reproduced.
    Asserted through the real datasets API, never a copy of production's shuffle
    — if the two orders ever converged, the refusal could be revisited."""

    import random

    datasets = pytest.importorskip("datasets")

    rows = [{"i": i} for i in range(8)]
    hf_order = [row["i"] for row in datasets.Dataset.from_list(rows).shuffle(seed=42)]
    python_order = list(range(8))
    random.Random(42).shuffle(python_order)

    assert hf_order != python_order


def test_load_rows_forwards_data_files_and_the_resolved_features_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OME-1264 extension 2: the bake loads with the SAME data_files + features
    pair the eval declares — data_files forwarded verbatim, features resolved
    from its dotted pointer to the eval's own Features schema."""

    import sys
    import types

    import datasets

    from screamingface_engine_inspect.prepare import _load_rows

    schema = datasets.Features({"q": datasets.Value("string")})
    module = types.ModuleType("fake_bake_eval2")
    module.FT = schema  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fake_bake_eval2", module)
    seen: dict[str, Any] = {}

    def fake_load(path: str, name: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        seen.update({"path": path, "name": name, **kwargs})
        return [{"q": "?"}]

    monkeypatch.setattr(datasets, "load_dataset", fake_load)
    spec = SnapshotSpec(
        dataset="acme/quiz",
        config="default",
        split="test",
        dataset_revision="c" * 40,
        case_count=1,
        record_to_sample="fake_bake_eval2:FT",
        data_files={"test": "test.jsonl"},
        features="fake_bake_eval2:FT",
    )

    rows = _load_rows(spec)

    assert rows == [{"q": "?"}]
    assert seen["data_files"] == {"test": "test.jsonl"}
    # Identity, not equality: the bake must use the eval's OWN schema object.
    assert seen["features"] is schema


def test_load_rows_refuses_a_features_pointer_that_is_not_a_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mispointed features reference (landing on a string, a function) must
    refuse the bake by name — loading with a junk schema would corrupt every
    row silently or crash deep inside `datasets`."""

    import sys
    import types

    from screamingface_engine_inspect.prepare import _load_rows

    module = types.ModuleType("fake_bake_eval3")
    module.NOT_A_SCHEMA = "hello"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fake_bake_eval3", module)
    spec = SnapshotSpec(
        dataset="acme/quiz",
        config="default",
        split="test",
        dataset_revision="c" * 40,
        case_count=1,
        record_to_sample="fake_bake_eval3:NOT_A_SCHEMA",
        features="fake_bake_eval3:NOT_A_SCHEMA",
    )

    with pytest.raises(PrepareError, match="features"):
        _load_rows(spec)


def test_without_a_choice_shuffle_seed_the_choice_order_is_upstreams(tmp_path: Path) -> None:
    """The new field defaults to None — boards without it keep baking the
    dataset's own choice order (append-only behavior for every existing board)."""

    emit_snapshot(SNAPSHOTS["mmlu"], _MMLU_ROWS, tmp_path)
    baked_choices = {
        tuple(
            json.loads((tmp_path / "targets" / f"{case_id}.json").read_text(encoding="utf-8"))[
                "choices"
            ]
        )
        for case_id in (1, 2, 3)
    }
    assert baked_choices == {tuple(row["choices"]) for row in _MMLU_ROWS}


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


# ── sample metadata rides the private target (OME-1240, opt-in) ──────────────


def test_opted_in_sample_metadata_is_baked_into_the_target(tmp_path: Path) -> None:
    """A metadata-dispatching scorer (frontierscience) reads sample metadata at
    grade time — a row that opts in bakes it into the private target record."""

    from dataclasses import replace

    spec = replace(SNAPSHOTS["gsm8k"], keep_sample_metadata=True)
    emit_snapshot(spec, _GSM8K_ROWS, tmp_path)
    target = json.loads((tmp_path / "targets" / "1.json").read_text(encoding="utf-8"))
    # gsm8k's record_to_sample attaches {"reasoning": ...} to every Sample.
    assert target["metadata"] == {"reasoning": "6 * 7 = 42"}


def test_without_the_opt_in_no_metadata_is_baked(tmp_path: Path) -> None:
    """INVARIANT (published-snapshot immutability): a default row bakes byte-identical
    assets to the pre-OME-1240 bake — metadata lands only behind the opt-in."""

    emit_snapshot(SNAPSHOTS["gsm8k"], _GSM8K_ROWS, tmp_path)
    target = json.loads((tmp_path / "targets" / "1.json").read_text(encoding="utf-8"))
    assert "metadata" not in target


def test_the_metadata_opt_in_is_exam_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flipping the opt-in changes what the bake ships, so the revision must move."""

    from dataclasses import replace

    from screamingface_engine_inspect import boards, single_shot

    monkeypatch.setattr(boards, "_ASSEMBLED", {})
    monkeypatch.setattr(single_shot, "_BOARDS_BY_ID", {})
    base = boards.imported_board("gsm8k").benchmark.revision

    monkeypatch.setitem(SNAPSHOTS, "gsm8k", replace(SNAPSHOTS["gsm8k"], keep_sample_metadata=True))
    monkeypatch.setattr(boards, "_ASSEMBLED", {})
    monkeypatch.setattr(single_shot, "_BOARDS_BY_ID", {})
    assert boards.imported_board("gsm8k").benchmark.revision != base


def test_non_json_sample_metadata_refuses_the_bake(tmp_path: Path) -> None:
    """The target file is JSON — an unserializable metadata value must fail the bake
    by case number, never truncate or coerce an exam asset silently."""

    import sys
    import types
    from dataclasses import replace

    from inspect_ai.dataset import Sample

    module = types.ModuleType("fake_metadata_eval")

    def record_to_sample(record: dict[str, Any]) -> Sample:
        return Sample(
            input=record["question"],
            target="42",
            metadata={"weird": object()},
        )

    module.record_to_sample = record_to_sample  # type: ignore[attr-defined]
    sys.modules["fake_metadata_eval"] = module
    try:
        spec = replace(
            SNAPSHOTS["gsm8k"],
            record_to_sample="fake_metadata_eval:record_to_sample",
            keep_sample_metadata=True,
        )
        with pytest.raises(PrepareError, match="case 1"):
            emit_snapshot(spec, _GSM8K_ROWS[:1], tmp_path)
    finally:
        del sys.modules["fake_metadata_eval"]
