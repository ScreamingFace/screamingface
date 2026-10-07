# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The generated Task-replay declaration and its BenchmarkSpec row (spec R6).

INVARIANT: what the importer writes is Python that evaluates to exactly the declaration it
sealed. Case Sources go in as comments (the reviewer judges where the Cases come from); the
Case count and Case Digest go in as values (the code enforces what they are).
"""

from __future__ import annotations

import ast
import datetime
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine.benchmarks.definition import _WEB_URL  # noqa: E402
from screamingface_engine_inspect import task_replay_rows as rows_module  # noqa: E402
from screamingface_engine_inspect.benchmarks import BenchmarkSpec, JudgeSpec  # noqa: E402
from screamingface_engine_inspect.case_sources import CaseSource  # noqa: E402
from screamingface_engine_inspect.import_replay import (  # noqa: E402
    TaskReplayFacts,
    TaskReplayImport,
)
from screamingface_engine_inspect.importer import ImporterError  # noqa: E402
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec  # noqa: E402
from screamingface_engine_inspect.task_replay_rows import (  # noqa: E402
    TaskReplayRows,
    render_task_replay_rows,
    write_task_replay_rows,
)

_SRC_DIR: Path = Path(rows_module.__file__).resolve().parent
_COMMIT: str = "84ab72d94318290aad2e4ec820d535a95a1f7552"
_AGIEVAL_URL: str = (
    f"https://raw.githubusercontent.com/ruixiangcui/AGIEval/{_COMMIT}/data/v1_1/lsat-ar.jsonl"
)
_AGIEVAL_TASK: str = "inspect_evals.agieval.agieval:agie_lsat_ar"
_TODAY: str = datetime.date.today().isoformat()


def _facts(**overrides: Any) -> TaskReplayFacts:
    """agieval-shaped facts, as the import child reads them off the built Task."""

    values: dict[str, Any] = {
        "task_ref": _AGIEVAL_TASK,
        "task_args": None,
        "mcq": True,
        "scorer": "inspect_ai.scorer:choice",
        "scorer_kwargs": {},
        "custom_metrics": (),
        "keep_sample_metadata": False,
        **overrides,
    }
    return TaskReplayFacts(**values)


def _imported(
    *,
    sources: tuple[CaseSource, ...] | None = None,
    facts: TaskReplayFacts | None = None,
    **spec: Any,
) -> TaskReplayImport:
    """A sealed import as import_by_task_replay returns it (no child runs here)."""

    the_facts: TaskReplayFacts = facts or _facts()
    declaration: TaskReplayCasesSpec = TaskReplayCasesSpec(
        **{
            "task": the_facts.task_ref,
            "case_count": 230,
            "case_digest": "e" * 64,
            **spec,
        }
    )
    return TaskReplayImport(
        declaration=declaration,
        case_sources=sources or (CaseSource("url", _AGIEVAL_URL, f"commit {_COMMIT}"),),
        facts=the_facts,
    )


def _declared(rows: TaskReplayRows) -> dict[str, TaskReplayCasesSpec]:
    """Evaluate the generated declaration the way importing prepare.py would."""

    namespace: dict[str, Any] = {"TaskReplayCasesSpec": TaskReplayCasesSpec}
    exec("declared = {\n" + rows.cases + "}", namespace)  # noqa: S102 — our own rendered row
    return namespace["declared"]


def _benchmark(rows: TaskReplayRows) -> BenchmarkSpec:
    """Evaluate the generated BenchmarkSpec row the way importing benchmarks.py would."""

    namespace: dict[str, Any] = {"BenchmarkSpec": BenchmarkSpec, "JudgeSpec": JudgeSpec}
    exec("declared = (\n" + rows.benchmark + ")", namespace)  # noqa: S102 — our own rendered row
    return namespace["declared"][0]


@pytest.fixture
def engine_src_copy(tmp_path: Path) -> Path:
    """A working copy of the real three generated-into files."""

    # OME-1460: pins.py is gone; an import writes into these two files only.
    for name in ("prepare.py", "benchmarks.py"):
        shutil.copy(_SRC_DIR / name, tmp_path / name)
    return tmp_path


def test_task_replay_rows_carry_the_sources_as_comments_and_the_seal_as_values() -> None:
    rows: TaskReplayRows = render_task_replay_rows("agieval_lsat_ar", _imported(), "TODO")

    assert rows.cases == (
        f"    # agieval_lsat_ar — imported by Task replay on {_TODAY} from\n"
        f"    #   {_AGIEVAL_TASK}.\n"
        "    # Case Sources, as recorded at import (review them; the Case Digest pins them):\n"
        f"    #   url {_AGIEVAL_URL}\n"
        f"    #     pin commit {_COMMIT}\n"
        '    "agieval_lsat_ar": TaskReplayCasesSpec(\n'
        f'        task="{_AGIEVAL_TASK}",\n'
        "        case_count=230,\n"
        f'        case_digest="{"e" * 64}",\n'
        "        # TODO(review): no dataset card to read; the owner decides.\n"
        '        license="TODO",\n'
        "    ),\n"
    )
    assert _declared(rows)["agieval_lsat_ar"] == _imported().declaration


def test_task_args_render_as_python_that_evaluates_to_the_same_value() -> None:
    """Review Focus 6: JSON would write false/null, which parse as names and raise NameError
    when prepare.py is imported — every Benchmark down, not just this one."""

    task_args: dict[str, Any] = {
        "shuffle": False,
        "languages": ["en"],
        "limit": None,
        "nested": {"on": True, "weights": [0.5, 2]},
    }
    imported: TaskReplayImport = _imported(task_args=task_args)

    rows: TaskReplayRows = render_task_replay_rows("worldsense", imported, "TODO")

    assert _declared(rows)["worldsense"].task_args == task_args


def test_an_unpinned_source_says_the_digest_is_the_only_pin() -> None:
    source: CaseSource = CaseSource("url", "https://x/mgsm_en.tsv", "unpinned")

    rows: TaskReplayRows = render_task_replay_rows("mgsm_en", _imported(sources=(source,)), "TODO")

    assert (
        "    #     pin unpinned (no upstream hash: the Case Digest is the only pin)\n" in rows.cases
    )


def test_a_cleared_card_license_lands_as_the_license_value() -> None:
    rows: TaskReplayRows = render_task_replay_rows("medqa", _imported(), "apache-2.0")

    assert _declared(rows)["medqa"].license == "apache-2.0"
    assert "the owner decides" not in rows.cases
    assert "        # License: apache-2.0.\n" in rows.benchmark


def test_an_uncleared_card_license_stays_todo_and_names_what_the_card_says() -> None:
    """D13: written as the value, 'unknown' would pass R7's gate with nobody deciding."""

    rows: TaskReplayRows = render_task_replay_rows(
        "medqa", _imported(), "TODO", card_license="unknown"
    )

    assert _declared(rows)["medqa"].license == "TODO"
    assert (
        "        # TODO(review): the card says 'unknown', not a cleared license; "
        "the owner decides.\n" in rows.cases
    )


def test_the_metadata_choice_the_digest_covers_is_written() -> None:
    """D11: keep_sample_metadata is inside the seal, so the row must carry it."""

    rows: TaskReplayRows = render_task_replay_rows(
        "chembench", _imported(keep_sample_metadata=True), "TODO"
    )

    assert "        keep_sample_metadata=True,\n" in rows.cases
    assert _declared(rows)["chembench"].keep_sample_metadata is True


def test_the_declaration_carries_no_prompt_field() -> None:
    """Capture (PR #1219) renders the prompt from the Task's own solvers, so no row names a
    template; a declaration that did would describe a render nothing reads."""

    rows: TaskReplayRows = render_task_replay_rows("sad", _imported(), "TODO")

    for field in ("prompt_template", "choice_template", "system_message", "TODO(review): solver"):
        assert field not in rows.cases


@pytest.mark.parametrize(
    ("label", "imported", "license_value"),
    [
        ("license", _imported(), 'mit")\nimport os  # ("'),
        ("task", _imported(task='x:y"),\nimport os  # '), "TODO"),
        (
            "Case Source",
            _imported(sources=(CaseSource("url", 'https://x/"\nimport os', "unpinned"),)),
            "TODO",
        ),
    ],
)
def test_text_that_could_escape_the_generated_code_is_refused(
    label: str, imported: TaskReplayImport, license_value: str
) -> None:
    """Review Focus 5: these strings come from an eval or a Hub card and land in Python."""

    with pytest.raises(ImporterError, match="injection guard"):
        render_task_replay_rows("x", imported, license_value)


def test_task_replay_benchmark_row_points_at_the_first_web_source() -> None:
    rows: TaskReplayRows = render_task_replay_rows("agieval_lsat_ar", _imported(), "TODO")
    benchmark: BenchmarkSpec = _benchmark(rows)

    assert benchmark.key == "agieval_lsat_ar"
    assert benchmark.dataset_url == _AGIEVAL_URL
    assert benchmark.scorer == "inspect_ai.scorer:choice"
    assert benchmark.with_check_surface is False  # MCQ (OME-796)
    assert "        # License: TODO.\n" in rows.benchmark


def test_task_replay_benchmark_row_builds_for_a_hugging_face_source() -> None:
    """Review Focus 8: BenchmarkSpec registration refuses any dataset_url but a web URL."""

    source: CaseSource = CaseSource("hugging-face", "bigbio/med_qa", "revision " + "d" * 40)

    rows: TaskReplayRows = render_task_replay_rows("medqa", _imported(sources=(source,)), "TODO")

    url: str = _benchmark(rows).dataset_url
    assert url == "https://huggingface.co/datasets/bigbio/med_qa"
    assert _WEB_URL.fullmatch(url)


def test_a_source_with_no_web_page_leaves_the_dataset_url_for_review() -> None:
    """No browsable Case Source: the literal TODO is refused at registration, like difficulty."""

    source: CaseSource = CaseSource("file", "inspect_evals/x/data.jsonl", "inspect_evals==0.20.0")

    rows: TaskReplayRows = render_task_replay_rows("x", _imported(sources=(source,)), "TODO")

    assert _benchmark(rows).dataset_url == "TODO"
    assert "TODO(review): no Case Source has a web page" in rows.benchmark


def test_a_free_text_task_offers_the_check_surface() -> None:
    facts: TaskReplayFacts = _facts(
        task_ref="inspect_evals.mgsm.mgsm:mgsm",
        mcq=False,
        scorer="inspect_ai.scorer:match",
        scorer_kwargs={"numeric": True},
    )

    rows: TaskReplayRows = render_task_replay_rows("mgsm_en", _imported(facts=facts), "TODO")
    benchmark: BenchmarkSpec = _benchmark(rows)

    assert benchmark.scorer_kwargs == {"numeric": True}
    assert benchmark.with_check_surface is True


def test_write_task_replay_rows_lands_in_prepare_and_benchmarks_only(
    engine_src_copy: Path,
) -> None:
    write_task_replay_rows(
        "stand_in_replay", _imported(), engine_src=engine_src_copy, license="TODO"
    )

    prepare_text: str = (engine_src_copy / "prepare.py").read_text()
    benchmarks_text: str = (engine_src_copy / "benchmarks.py").read_text()
    assert '"stand_in_replay": TaskReplayCasesSpec(' in prepare_text
    assert prepare_text.index('"stand_in_replay": TaskReplayCasesSpec(') > prepare_text.index(
        "TASK_REPLAY_CASES: dict[str, TaskReplayCasesSpec] = {"
    )
    assert 'key="stand_in_replay"' in benchmarks_text
    # OME-1460: pins.py is gone; the import still writes no third file.
    assert sorted(path.name for path in engine_src_copy.iterdir()) == [
        "benchmarks.py",
        "prepare.py",
    ]
    for name in ("prepare.py", "benchmarks.py"):
        ast.parse((engine_src_copy / name).read_text())


def test_write_task_replay_rows_refuses_a_key_already_declared(engine_src_copy: Path) -> None:
    write_task_replay_rows(
        "stand_in_replay", _imported(), engine_src=engine_src_copy, license="TODO"
    )

    with pytest.raises(ImporterError, match="already exists"):
        write_task_replay_rows(
            "stand_in_replay", _imported(), engine_src=engine_src_copy, license="TODO"
        )


def test_write_task_replay_rows_refuses_a_key_the_hugging_face_path_declared(
    engine_src_copy: Path,
) -> None:
    """One key, one Benchmark: gsm8k already has a CasesSpec row."""

    with pytest.raises(ImporterError, match="already exists"):
        write_task_replay_rows("gsm8k", _imported(), engine_src=engine_src_copy, license="TODO")


# ── the license the importer can read off a Hugging Face card (spec R7, D13) ─────

import types  # noqa: E402

from screamingface_engine_inspect.task_replay_rows import CardLicense, card_license_of  # noqa: E402


def _card(license_value: object) -> Any:
    """A stand-in for HfApi().dataset_info(...): only its card's license is read."""

    return types.SimpleNamespace(card_data={"license": license_value})


def test_a_cleared_license_comes_from_the_card_of_the_one_hugging_face_source() -> None:
    seen: list[tuple[str, str | None]] = []

    def dataset_info(dataset: str, revision: str | None) -> Any:
        """Record which card was read, at which revision."""

        seen.append((dataset, revision))
        return _card("Apache-2.0")

    source: CaseSource = CaseSource("hugging-face", "bigbio/med_qa/main", "revision " + "d" * 40)

    license_read: CardLicense = card_license_of((source,), dataset_info=dataset_info)

    assert license_read == CardLicense(value="apache-2.0", card_says=None)
    assert seen == [("bigbio/med_qa", "d" * 40)]


def test_an_uncleared_card_license_is_written_as_todo() -> None:
    """D13: medqa's card says UNKNOWN; as a value it would pass R7's gate undecided."""

    source: CaseSource = CaseSource("hugging-face", "bigbio/med_qa", "unpinned")

    license_read: CardLicense = card_license_of(
        (source,), dataset_info=lambda dataset, revision: _card("UNKNOWN")
    )

    assert license_read == CardLicense(value="TODO", card_says="unknown")


def test_no_card_speaks_for_a_url_source_or_several_hugging_face_sources() -> None:
    def never(dataset: str, revision: str | None) -> Any:
        """No card should be read here."""

        raise AssertionError("no card to read")

    url_only: tuple[CaseSource, ...] = (CaseSource("url", "https://x", "unpinned"),)
    two_repos: tuple[CaseSource, ...] = (
        CaseSource("hugging-face", "a/b", "unpinned"),
        CaseSource("hugging-face", "c/d", "unpinned"),
    )

    assert card_license_of(url_only, dataset_info=never) == CardLicense("TODO", None)
    assert card_license_of(two_repos, dataset_info=never) == CardLicense("TODO", None)


def test_a_card_with_no_license_is_todo() -> None:
    source: CaseSource = CaseSource("hugging-face", "a/b", "unpinned")

    assert card_license_of((source,), dataset_info=lambda d, r: _card(None)) == CardLicense(
        "TODO", None
    )


def test_a_metric_name_with_a_parenthesis_lands_as_a_comment() -> None:
    """A custom metric name is written only into a comment, so only a line break could
    escape it."""

    facts: TaskReplayFacts = _facts(custom_metrics=("inspect_evals/f1 (macro)",))

    rows: TaskReplayRows = render_task_replay_rows("agieval", _imported(facts=facts), "TODO")

    assert "inspect_evals/f1 (macro)" in rows.benchmark
    assert _declared(rows)["agieval"].task == _AGIEVAL_TASK


def test_a_comment_string_with_a_line_break_is_refused() -> None:
    """A newline would end the comment and start a line of code (injection guard)."""

    facts: TaskReplayFacts = _facts(custom_metrics=("x\nimport os",))

    with pytest.raises(ImporterError, match="injection guard"):
        render_task_replay_rows("x", _imported(facts=facts), "TODO")


# ── the two declarations the importing agent passes in (spec R18, R19) ─────────


def test_excluded_ids_are_written_with_a_reason_left_for_review() -> None:
    """Spec R18: the ids land in the row so every build drops them; WHY they are dropped is
    the reviewer's to write, so the row carries a TODO(review) where the reason goes."""

    rows: TaskReplayRows = render_task_replay_rows(
        "sad_stages_full",
        _imported(case_count=797, excluded_sample_ids=("stages_full:14", "stages_full:58")),
        "TODO",
    )

    assert (
        "        # NAMED DEVIATION — TODO(review): say why upstream's Samples\n"
        "        # below are left out.\n"
        "        excluded_sample_ids=(\n"
        '            "stages_full:14",\n'
        '            "stages_full:58",\n'
        "        ),\n"
    ) in rows.cases
    assert _declared(rows)["sad_stages_full"].excluded_sample_ids == (
        "stages_full:14",
        "stages_full:58",
    )


def test_a_benchmark_without_an_answer_key_says_so_in_its_row() -> None:
    """Spec R19: the empty keys are inside the seal, so the row must carry the opt-in."""

    rows: TaskReplayRows = render_task_replay_rows(
        "cyse4_mitre_frr", _imported(has_answer_key=False), "TODO"
    )

    assert "        has_answer_key=False,\n" in rows.cases
    assert _declared(rows)["cyse4_mitre_frr"].has_answer_key is False


def test_an_excluded_id_that_could_escape_the_generated_code_is_refused() -> None:
    """The ids come from the eval's own Samples and land in Python, like the task reference."""

    imported: TaskReplayImport = _imported(excluded_sample_ids=('x"),\nimport os  # ',))

    with pytest.raises(ImporterError, match="injection guard"):
        render_task_replay_rows("x", imported, "TODO")


# --- OME-1460: the generated row carries the Hub pins, the seeds and the gate --------------

_MEDQA_SHA: str = "ddef95d268cdad413693d634279a9a679d468469"


def test_the_hub_pins_seeds_and_gate_are_written_and_evaluate_back() -> None:
    """Every image build reads these off the row, so a row that dropped one would replay
    unpinned (or be refused) at the first build after import."""

    imported: TaskReplayImport = _imported(
        source_pins={"bigbio/med_qa": _MEDQA_SHA},
        shuffle_seed=1234,
        choice_shuffle_seed=7,
        needs_hf_token=True,
    )

    rows: TaskReplayRows = render_task_replay_rows("medqa", imported, "TODO")

    assert f'            "bigbio/med_qa": "{_MEDQA_SHA}",\n' in rows.cases
    assert "        shuffle_seed=1234,\n" in rows.cases
    assert "        choice_shuffle_seed=7,\n" in rows.cases
    assert "        needs_hf_token=True,\n" in rows.cases
    assert _declared(rows)["medqa"] == imported.declaration


def test_several_hub_pins_are_written_sorted() -> None:
    imported: TaskReplayImport = _imported(source_pins={"b/b": "1" * 40, "a/a": "2" * 40})

    rows: TaskReplayRows = render_task_replay_rows("k", imported, "TODO")

    assert rows.cases.index('"a/a"') < rows.cases.index('"b/b"')
    assert _declared(rows)["k"] == imported.declaration


@pytest.mark.parametrize(
    "source_pins",
    [
        {'x/y"\nimport os': "1" * 40},
        {"x/y": 'abc"\nimport os'},
    ],
    ids=["repo id", "commit"],
)
def test_a_hub_pin_that_could_escape_the_generated_code_is_refused(
    source_pins: dict[str, str],
) -> None:
    """Review Focus 5: a repo id comes from the eval's own call, a commit from the Hub."""

    with pytest.raises(ImporterError, match="injection guard"):
        render_task_replay_rows("x", _imported(source_pins=source_pins), "TODO")


def test_a_non_ascii_excluded_sample_id_is_written_and_evaluates_back() -> None:
    """onet_m6's Named Deviation names Thai ids (2019_10ข_6985). The id lands inside a JSON
    string literal, which escapes every quote, backslash and line break, so the guard need
    only refuse what a reviewer cannot read (OME-1460)."""

    imported: TaskReplayImport = _imported(excluded_sample_ids=("2019_10ข_6985", "2021_4_b447"))

    rows: TaskReplayRows = render_task_replay_rows("onet_m6", imported, "TODO")

    assert '            "2019_10ข_6985",\n' in rows.cases
    assert _declared(rows)["onet_m6"] == imported.declaration


@pytest.mark.parametrize("sample_id", ['a"\nimport os', "a‮b"], ids=["line break", "bidi"])
def test_an_excluded_sample_id_a_reviewer_cannot_read_is_refused(sample_id: str) -> None:
    with pytest.raises(ImporterError, match="injection guard"):
        render_task_replay_rows("x", _imported(excluded_sample_ids=(sample_id,)), "TODO")


def test_an_import_with_a_case_set_digest_writes_it_on_the_row(engine_src_copy: Path) -> None:
    """OME-1492: the order-blind seal sits beside the Case Digest on the declaration, so a
    later broken seal can say "order only"."""

    imported: TaskReplayImport = _imported()
    sealed: TaskReplayImport = replace(
        imported, declaration=replace(imported.declaration, case_set_digest="d" * 64)
    )

    write_task_replay_rows("stand_in_replay", sealed, engine_src=engine_src_copy, license="TODO")

    prepare_text: str = (engine_src_copy / "prepare.py").read_text()
    assert f'case_set_digest="{"d" * 64}",' in prepare_text
