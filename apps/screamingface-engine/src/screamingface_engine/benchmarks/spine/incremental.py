"""Bind a board's canonical grading to early execution and final reduction."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from screamingface_engine.benchmarks.aggregation import SelectedCase, finalize_candidate_result
from screamingface_engine.benchmarks.contract import CaseResult
from screamingface_engine.benchmarks.graded_results import decode_results, encode_result
from screamingface_engine.benchmarks.progress import ScoreCases, completed_case, grading_progress
from screamingface_engine.benchmarks.spine.scored import ScoredPath


@dataclass(frozen=True)
class Scoring:
    path: ScoredPath
    benchmark_id: str
    revision: str
    selected: Sequence[SelectedCase]
    material: Callable[[int], object | None]
    scorer: ScoreCases
    metadata: Callable[[int], Mapping[str, Any]] | None = None

    def aggregate(self, raw: str) -> dict[str, Any]:
        return self.path.aggregate(
            raw,
            benchmark_id=self.benchmark_id,
            benchmark_revision=self.revision,
            selected_cases=self.selected,
            grading_material=self.material,
            scorer=self.scorer,
            case_metadata=self.metadata,
        )

    async def grade_row(self, raw: str, index: int) -> str:
        selected = self.selected[index]
        result = await self.path.case_result(
            selected,
            index,
            self.path.reader.index(json.dumps([raw]), (int(selected.case_id),)),
            self.material,
            self.metadata,
        )
        if result is None:
            raise ValueError("completed execution must produce a Case result")
        completed_case(self.benchmark_id, self.revision, result, self.scorer)
        return encode_result(result, benchmark_id=self.benchmark_id, revision=self.revision)

    async def finish(self, raw: str) -> dict[str, Any]:
        with grading_progress(self.benchmark_id, self.revision, self.scorer):
            rows = json.loads(raw)
            if not isinstance(rows, list) or len(rows) > len(self.selected):
                raise ValueError("graded results must be an array within the selected Case count")
            results: list[CaseResult] = []
            for index, selected in enumerate(self.selected):
                row = rows[index] if index < len(rows) else None
                row = json.loads(row) if isinstance(row, str) else row
                if index < len(rows) and row is None:
                    raise ValueError("invalid graded Case result envelope")
                result = await self._completed_row(row, selected, index)
                if result is not None:
                    results.append(result)
            finalized = finalize_candidate_result(
                benchmark_id=self.benchmark_id,
                benchmark_revision=self.revision,
                selected_cases=self.selected,
                cases=results,
                scorer=self.scorer,
            )
            observed = {case.case_id for case in results}
            for case in finalized.cases:
                if case.case_id not in observed:
                    completed_case(self.benchmark_id, self.revision, case, self.scorer)
            return finalized.as_payload()

    async def _completed_row(self, row, selected, index) -> CaseResult | None:
        if (
            isinstance(row, Mapping)
            and isinstance(row.get("error"), Mapping)
            and row["error"].get("kind") == "CaseFinalizationError"
        ):
            raise ValueError("invalid completed Case result")
        if row is None or isinstance(row, Mapping) and "error" in row:
            # WHY: only absent/failed execution uses the failure ladder. A completed
            # grade is never sent to the grader a second time.
            indexed = self.path.reader.index(
                json.dumps([] if row is None else [row]), (int(selected.case_id),)
            )
            result = await self.path.case_result(
                selected, index, indexed, self.material, self.metadata
            )
            if result is not None:
                # WHY: these terminal failures had no early grade to publish.
                # The run observer deduplicates retries of the same canonical result.
                completed_case(self.benchmark_id, self.revision, result, self.scorer)
            return result
        result = decode_results(
            json.dumps([row]),
            benchmark_id=self.benchmark_id,
            revision=self.revision,
            selected=[selected],
            failure=_unexpected_failure,
            allow_extra_metadata=True,
        )[0]
        if self.metadata is not None:
            # WHY: canonical grading failures retain selected metadata but may never
            # acquire grading enrichment. Supplied tags must still be authoritative.
            unscored_failure = bool(result.failures) and (
                result.grade is None or result.grade.score is None
            )
            for key, value in self.metadata(int(selected.case_id)).items():
                if key not in result.metadata and unscored_failure:
                    continue
                if key not in result.metadata or result.metadata[key] != value:
                    raise ValueError("graded result metadata does not match the selected Case")
        return result


def _unexpected_failure(*args) -> CaseResult:
    raise ValueError("unexpected collected failure")
