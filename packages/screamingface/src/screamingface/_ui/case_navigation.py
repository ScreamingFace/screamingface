"""Compact case identity and position navigation, independent of retained payloads."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, overload

from screamingface._report_primitives import CaseId

if TYPE_CHECKING:
    from screamingface.case_result import CaseResult
    from screamingface.report import CandidateResult, Report

PAGE_SIZE = 25


class CaseEntries(Sequence[tuple["CandidateResult", "CaseResult"]]):
    """Flatten candidate positions without retaining their cases."""

    def __init__(self, report: Report) -> None:
        self.owners = report.candidates
        self.total = sum(len(owner.cases) for owner in self.owners)

    def __len__(self) -> int:
        return self.total

    @overload
    def __getitem__(self, index: int) -> tuple[CandidateResult, CaseResult]: ...

    @overload
    def __getitem__(self, index: slice) -> list[tuple[CandidateResult, CaseResult]]: ...

    def __getitem__(self, index: int | slice):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(self.total))]
        position = index + self.total if index < 0 else index
        if not 0 <= position < self.total:
            raise IndexError(index)
        for owner in self.owners:
            if position < len(owner.cases):
                return owner, owner.cases[position]
            position -= len(owner.cases)
        raise IndexError(index)


class CaseNavigation:
    def __init__(self, owners: Sequence[CandidateResult]) -> None:
        self.identities = tuple(tuple(owner.cases._identities()) for owner in owners)
        self.offsets: list[int] = []
        self.groups: dict[CaseId, list[int]] = {}
        offset = 0
        for ids in self.identities:
            self.offsets.append(offset)
            for position, case_id in enumerate(ids):
                self.groups.setdefault(case_id, []).append(offset + position)
            offset += len(ids)
        self.combined = tuple(index for indices in self.groups.values() for index in indices)
        self.case_positions = {}
        for position, index in enumerate(self.combined):
            self.case_positions[index] = position
        self.select(-1)

    def select(self, candidate: int) -> None:
        if candidate < -1 or candidate >= len(self.identities):
            raise ValueError("unknown Candidate")
        self.selected = candidate
        if candidate == -1:
            self.pages: Sequence[Sequence[int]] = tuple(
                self.combined[start : start + PAGE_SIZE]
                for start in range(0, len(self.combined), PAGE_SIZE)
            )
        else:
            start, count = self.offsets[candidate], len(self.identities[candidate])
            self.pages = tuple(
                range(start + index, start + min(index + PAGE_SIZE, count))
                for index in range(0, count, PAGE_SIZE)
            )

    def indices(self, page: int) -> Sequence[int]:
        return self.pages[page]

    def focused_id(self, page: int) -> CaseId:
        index = self.indices(page)[0]
        for start, ids in reversed(tuple(zip(self.offsets, self.identities, strict=True))):
            if index >= start:
                return ids[index - start]
        raise IndexError(index)

    def resolve(self, query: str) -> CaseId:
        ids = self.groups if self.selected == -1 else self.identities[self.selected]
        # INVARIANT: whitespace is part of retained string identity, never presentation padding.
        if query in ids:
            return query
        text = query.strip()
        try:
            case_id: CaseId = int(text)
        except ValueError:
            case_id = query
        if case_id not in ids:
            raise ValueError(f"Case {text} not found. This selection contains {len(ids)} cases.")
        return case_id

    def locate(self, query: str) -> int:
        return self.locate_id(self.resolve(query))

    def locate_id(self, case_id: CaseId) -> int:
        if case_id not in self.groups:
            raise ValueError(f"Case {case_id} not found")
        if self.selected == -1:
            return self.case_positions[self.groups[case_id][0]] // PAGE_SIZE
        return self.identities[self.selected].index(case_id) // PAGE_SIZE

    def caption(self, page: int) -> str:
        total = len(self.combined) if self.selected == -1 else len(self.identities[self.selected])
        start = page * PAGE_SIZE
        return f"{start + 1}–{start + len(self.indices(page))} of {total}"
