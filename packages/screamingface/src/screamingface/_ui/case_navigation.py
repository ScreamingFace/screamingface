"""Compact case identity and position navigation, independent of retained payloads."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from screamingface._report_primitives import CaseId

if TYPE_CHECKING:
    from screamingface.report import CandidateResult

PAGE_SIZE = 25


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
        self.comparison_pages = tuple(
            tuple(indices[start : start + PAGE_SIZE])
            for indices in self.groups.values()
            for start in range(0, len(indices), PAGE_SIZE)
        )
        self.page_ids = tuple(
            case_id
            for case_id, indices in self.groups.items()
            for _ in range(0, len(indices), PAGE_SIZE)
        )
        self.select(-1)

    @property
    def comparing(self) -> bool:
        return self.selected == -1 and len(self.identities) > 1

    def select(self, candidate: int) -> None:
        if candidate < -1 or candidate >= len(self.identities):
            raise ValueError("unknown Candidate")
        self.selected = candidate
        if self.comparing:
            self.pages: Sequence[Sequence[int]] = self.comparison_pages
        else:
            owner = max(candidate, 0)
            start, count = self.offsets[owner], len(self.identities[owner])
            self.pages = tuple(
                range(start + index, start + min(index + PAGE_SIZE, count))
                for index in range(0, count, PAGE_SIZE)
            )

    def indices(self, page: int) -> Sequence[int]:
        return self.pages[page]

    def focused_id(self, page: int) -> CaseId:
        if self.comparing:
            return self.page_ids[page]
        return self.identities[max(self.selected, 0)][page * PAGE_SIZE]

    def resolve(self, query: str) -> CaseId:
        text = query.strip()
        try:
            case_id: CaseId = int(text)
        except ValueError:
            case_id = text
        ids = tuple(self.groups) if self.comparing else self.identities[max(self.selected, 0)]
        if case_id not in ids and text in ids:
            case_id = text
        if case_id not in ids:
            raise ValueError(f"Case {text} not found. This selection contains {len(ids)} cases.")
        return case_id

    def locate(self, query: str) -> int:
        case_id = self.resolve(query)
        ids = self.identities[max(self.selected, 0)]
        return self.page_ids.index(case_id) if self.comparing else ids.index(case_id) // PAGE_SIZE

    def caption(self, page: int) -> str:
        indices = self.indices(page)
        if not self.comparing:
            total = len(self.identities[max(self.selected, 0)])
            start = page * PAGE_SIZE
            return f"{start + 1}–{start + len(indices)} of {total}"
        case_id = self.page_ids[page]
        total = len(self.groups[case_id])
        if total <= PAGE_SIZE:
            return f"Case {case_id} · {total} candidate" + ("" if total == 1 else "s")
        start = self.groups[case_id].index(indices[0])
        return f"Case {case_id} · {start + 1}–{start + len(indices)} of {total} candidates"
