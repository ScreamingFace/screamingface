"""Baking ContractEval: the public contract question and the private gold spans."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.contracteval.pins import MAX_CONTEXT_TOKENS
from screamingface_engine.benchmarks.contracteval.prepare import (
    PrepareError,
    case_records,
    emit,
)


def _row(
    row_id: str = "Doc__Governing Law",
    *,
    context: str = "1. Governing Law. This Agreement is governed by Delaware law.",
    question: str = "Which state's law governs this contract?",
    spans: list[str] | None = None,
    title: str = "Doc",
) -> dict[str, object]:
    return {
        "id": row_id,
        "title": title,
        "context": context,
        "question": question,
        "answers": {"text": list(spans or []), "answer_start": [0] * len(spans or [])},
    }


class TestCaseRecords:
    def test_the_public_case_carries_the_contract_and_the_question(self) -> None:
        cases, _ = case_records([_row()])

        assert cases[0]["id"] == 1
        assert "Governing Law" in str(cases[0]["input"])
        assert "Which state's law governs" in str(cases[0]["input"])

    def test_the_public_case_never_reveals_WHICH_sentences_are_the_answer(self) -> None:
        """INVARIANT: what stays private here is the LOCATION of the answer, not its text.

        Unlike MedXpertQA — where the gold letter must never appear in the prompt — a CUAD gold
        span is by construction a quotation FROM the contract, so its text is unavoidably inside
        the public input; that is the task. The leak to guard against is any marker saying which
        sentences those are: a `gold_spans` list, an `answer_start` offset, or highlighting.
        """

        cases, _ = case_records([_row(spans=["governed by Delaware law"])])

        assert set(cases[0]) == {"id", "input"}
        for leaked in ("gold_spans", "answers", "answer_start", "is_positive"):
            assert leaked not in str(cases[0])

    def test_the_private_record_carries_the_gold_spans_and_polarity(self) -> None:
        _, answers = case_records([_row(spans=["governed by Delaware law"])])

        assert answers[1]["gold_spans"] == ["governed by Delaware law"]
        assert answers[1]["is_positive"] is True
        assert answers[1]["source_id"] == "Doc__Governing Law"

    def test_a_row_with_no_gold_spans_is_marked_negative(self) -> None:
        _, answers = case_records([_row(spans=[])])

        assert answers[1]["gold_spans"] == []
        assert answers[1]["is_positive"] is False

    def test_case_ids_are_one_based_and_follow_row_order(self) -> None:
        """WHY pinned: aggregate indexes rows BY POSITION against the selected case ids."""

        cases, answers = case_records([_row("a"), _row("b"), _row("c")])

        assert [c["id"] for c in cases] == [1, 2, 3]
        assert sorted(answers) == [1, 2, 3]

    def test_a_gold_span_that_is_not_a_string_is_refused(self) -> None:
        row = _row()
        row["answers"] = {"text": [17], "answer_start": [0]}

        with pytest.raises(PrepareError, match="gold span"):
            case_records([row])

    def test_an_empty_contract_is_refused(self) -> None:
        with pytest.raises(PrepareError, match="context"):
            case_records([_row(context="   ")])

    def test_an_empty_question_is_refused(self) -> None:
        with pytest.raises(PrepareError, match="question"):
            case_records([_row(question="")])

    def test_an_over_budget_contract_fails_the_build(self) -> None:
        """PROTOCOL (spec D-7): there is NO truncation path. The largest real contract is
        63,389 tokens against a 120,000 budget, so this guard never fires on the pinned
        revision — it exists so a future revision that grew a document fails the BUILD instead
        of silently scoring a model against text it never saw."""

        oversized = "word " * (MAX_CONTEXT_TOKENS + 1000)

        with pytest.raises(PrepareError, match="exceeds the context budget"):
            case_records([_row(context=oversized)])


class TestEmit:
    def test_writes_the_public_file_and_one_private_record_per_case(self, tmp_path: Path) -> None:
        summary = emit([_row("a", spans=["x"]), _row("b", spans=[])], tmp_path)

        cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
        assert len(cases) == 2
        assert (tmp_path / "answers" / "1.json").exists()
        assert (tmp_path / "answers" / "2.json").exists()
        assert summary["cases"] == 2

    def test_the_audit_summary_reports_the_polarity_split(self, tmp_path: Path) -> None:
        """WHY it matters: the negative share drives the laziness denominator and is the number
        that tells a reader an always-abstaining model would score 70% accuracy."""

        summary = emit([_row("a", spans=["x"]), _row("b"), _row("c")], tmp_path)

        assert summary["positive_cases"] == 1
        assert summary["negative_cases"] == 2

    def test_the_audit_summary_names_the_pinned_revision(self, tmp_path: Path) -> None:
        summary = emit([_row()], tmp_path)

        assert summary["dataset_revision"]
        assert summary["split"] == "test"


class TestModuleEntryPoint:
    def test_prepare_is_runnable_as_a_module(self) -> None:
        """REGRESSION: the SDK bakes assets by spawning
        `python -m screamingface_engine.benchmarks.contracteval.prepare --out <dir>`, so a
        missing `main` fails only at bake time with "prepared output is missing [...]", which
        names the symptom and hides the cause. The family guard in test_benchmark_deployment
        checks that the command STRING matches its regex — not that the module answers it.
        """

        from screamingface_engine.benchmarks.contracteval import prepare as module

        assert callable(module.main)

    def test_the_entry_point_reports_a_prepare_failure_as_exit_1(self, tmp_path: Path) -> None:
        from screamingface_engine.benchmarks.contracteval import prepare as module

        def _boom() -> list[dict[str, object]]:
            raise PrepareError("dataset unavailable")

        original = module.load_rows
        module.load_rows = _boom  # type: ignore[assignment]
        try:
            assert module.main(["--out", str(tmp_path)]) == 1
        finally:
            module.load_rows = original  # type: ignore[assignment]


class TestPreflight:
    def test_the_cases_route_refuses_to_serve_when_an_answer_key_is_missing(
        self, tmp_path: Path
    ) -> None:
        """REVIEW (PR #865): the cases route served candidate inputs without preflighting, so a
        missing answer file was discovered only AFTER inference had been paid for. Preflight
        runs before the booklet is handed out, so a broken bundle costs nothing.
        """

        from screamingface_engine.benchmarks.contracteval.runtime import _cases
        from url4.core.errors import ResolutionError

        emit([_row("a", spans=["x"]), _row("b", spans=[])], tmp_path)
        (tmp_path / "answers" / "2.json").unlink()

        with pytest.raises(ResolutionError, match="failed preflight"):
            _cases(tmp_path)()

    def test_a_healthy_bundle_serves_the_booklet(self, tmp_path: Path) -> None:
        from screamingface_engine.benchmarks.contracteval.runtime import _cases

        emit([_row("a", spans=["x"]), _row("b", spans=[])], tmp_path)

        served = json.loads(_cases(tmp_path)())

        assert [row["id"] for row in served] == [1, 2]


class TestContextGuardHeadroom:
    def test_a_contract_at_the_real_dataset_maximum_still_bakes(self) -> None:
        """The other half of "the guard both ways" (review, PR #984) — the guard must not fire
        on real data, and this test is what says so in CI rather than in a spec sentence.

        The largest CUAD contract measured 300,768 characters and 63,389 tokens by
        `tiktoken cl100k_base`. Against `MAX_CONTEXT_TOKENS = 120_000` and the deliberately
        pessimistic `_CHARS_PER_TOKEN = 4` estimate, that row is charged ~75,192 tokens — so
        the real headroom is a factor of ~1.6, and this test fails the day a revision halves it.
        """

        from screamingface_engine.benchmarks.contracteval.prepare import _CHARS_PER_TOKEN

        real_max_chars = 300_768
        charged = real_max_chars // _CHARS_PER_TOKEN

        assert charged < MAX_CONTEXT_TOKENS
        cases, _ = case_records([_row(context="x" * real_max_chars)])

        assert len(cases) == 1


class TestCasesRouteMemo:
    def test_a_broken_bundle_re_fails_on_every_call_not_just_the_first(
        self, tmp_path: Path
    ) -> None:
        """Spec §5 promises "only a successful pass is cached, so a broken bundle re-fails on
        every call". Both earlier preflight tests built a fresh closure and called it ONCE, so
        hoisting the memo assignment above `preflight` would have kept them green while a
        broken bundle got served on call 2. This binds one closure and calls it twice.
        """

        from screamingface_engine.benchmarks.contracteval.runtime import _cases
        from url4.core.errors import ResolutionError

        emit([_row("a", spans=["x"]), _row("b", spans=[])], tmp_path)
        (tmp_path / "answers" / "2.json").unlink()
        served = _cases(tmp_path)

        with pytest.raises(ResolutionError, match="failed preflight"):
            served()
        with pytest.raises(ResolutionError, match="failed preflight"):
            served()

    def test_preflight_runs_once_across_repeated_serves(self, tmp_path: Path) -> None:
        """The expensive check is still paid once — that is what the memo is for.

        WHY the memo no longer holds the PAYLOAD (review of PR #984): measured on the real
        bundle, `cases.json` is 201.5 MB and the serialized booklet is ~403 MB resident. Caching
        that for the process lifetime is a permanent cost in a mode where one process serves
        many runs, so only the preflight verdict is remembered and the bytes are rebuilt per
        call — which is what `medxpert/runtime.py` already does.
        """

        from screamingface_engine.benchmarks.contracteval import runtime

        emit([_row("a", spans=["x"]), _row("b", spans=[])], tmp_path)
        calls: list[int] = []
        original = runtime.preflight

        def counting(root: Path, case_ids: tuple[int, ...]) -> None:
            calls.append(len(case_ids))
            original(root, case_ids)

        runtime.preflight = counting  # type: ignore[assignment]
        try:
            served = runtime._cases(tmp_path)
            first = served()
            second = served()
        finally:
            runtime.preflight = original  # type: ignore[assignment]

        assert calls == [2]  # preflighted once, for both cases
        assert json.loads(first) == json.loads(second)
        # The bytes are REBUILT, not handed back from a cache — the distinction the 403 MB
        # measurement makes matter. Identical content, different object.
        assert first is not second


class TestRowCountGuard:
    def test_a_resized_split_fails_the_bake(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """REVIEW (PR #984): the captured count used to be a bare literal in `definition.py`,
        outside the revision hash and compared to nothing. Bump the dataset revision against a
        split of a different size and the bake succeeded while the expression still declared
        4,182 — so coverage percentages divided by a denominator nobody had verified.
        """

        from screamingface_engine.benchmarks.contracteval import prepare as module

        class _Fake:
            @staticmethod
            def load_dataset(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
                return [
                    {
                        "id": "a",
                        "title": "t",
                        "context": "c",
                        "question": "q",
                        "answers": {"text": [], "answer_start": []},
                    }
                ]

        monkeypatch.setattr(module.importlib, "import_module", lambda _n: _Fake)

        with pytest.raises(PrepareError, match="pinned split holds 1 rows"):
            module.load_rows()

    def test_the_declared_count_and_the_pin_are_one_value(self) -> None:
        """Two literals would be two things to forget."""

        from screamingface_engine.benchmarks.contracteval import definition, pins

        assert definition.CASE_COUNT is pins.EXPECTED_CASES
