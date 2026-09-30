"""Link legacy public heads to system names, out of band (erd.md §6.4).

FEATURE: OME-1307 (E14) — heads stored before E14 have no `system_revision_id`. This command
registers each one's `spec_id` as a system name and links the head to its revision, so the
registry and the board agree. Run `--dry-run` first: it reports every action and writes nothing.

INVARIANT: it NEVER changes `spec_id`, `score`, `content_hash` or any ranked column, and NEVER
merges two heads. So `ScoreStore.leaderboard()` returns the same rows before and after (BF-4).
INVARIANT (I-N4): a head on a private board is never read.
INVARIANT: idempotent. A rerun skips linked heads and reuses registered fingerprints (BF-6).
AIDEV-NOTE: a head with no `submitted_by` (stored while production ran `disabled`, D5) is reported
`no_owner` and stays unlinked: a `System.owner` is NOT NULL and the registry has no verified owner
for it.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, cast
from uuid import UUID

from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from .adapters.url4_fingerprinter import Url4Fingerprinter
from .config import Settings
from .core.registry import (
    InvalidSystemName,
    InvalidUrl4,
    RegistryService,
    RegistryWriteConflict,
    RevisionRef,
    SystemIdentity,
    SystemRepository,
    Url4TooLarge,
    normalize_system_name,
)
from .db import close_db, init_db
from .scores.models import Score
from .scores.system_registry_store import TortoiseSystemRepository

BackfillAction = Literal[
    "claim",
    "link",
    "already_linked",
    "clash",
    "duplicate_head",
    "name_mismatch",
    "invalid_name",
    "invalid_url4",
    "no_owner",
]

DRY_RUN_BANNER = "DRY RUN — nothing written"
APPLIED_BANNER = "APPLIED"


@dataclass(frozen=True)
class BackfillRow:
    action: BackfillAction
    score_id: UUID
    benchmark_id: str
    name: str | None
    detail: str


@dataclass(frozen=True)
class _Checked:
    identity: SystemIdentity
    name: str
    owner: str


@dataclass(frozen=True)
class _Known:
    """A revision this pass knows: `ref` is None while it is only planned (a dry run)."""

    name: str
    ref: RevisionRef | None


@dataclass
class _Pass:
    apply: bool
    repository: SystemRepository
    registry: RegistryService
    # The in-memory plan of this pass, so a dry run predicts what `--apply` would do.
    names: dict[str, str] = field(default_factory=dict)  # system name -> fingerprint
    known: dict[str, _Known] = field(default_factory=dict)  # fingerprint -> revision
    linked: set[tuple[str, str | None, str]] = field(default_factory=set)

    async def run(self) -> list[BackfillRow]:
        rows: list[BackfillRow] = []
        for head in await _public_unlinked_heads():
            rows.extend(await self._head(head))
        return rows

    async def _head(self, head: Score) -> list[BackfillRow]:
        # WHY one transaction per head when applying: a head's claim and its link commit or
        # roll back together, and an early stop leaves whole heads, never half of one.
        if not self.apply:
            return await self._resolve(head)
        async with in_transaction():
            return await self._resolve(head)

    async def _resolve(self, head: Score) -> list[BackfillRow]:
        checked = self._check(head)
        if isinstance(checked, BackfillRow):
            return [checked]
        known = await self._known_revision(checked.identity.fingerprint)
        if known is None:
            return await self._claim_and_link(head, checked)
        return [await self._link_or_mismatch(head, checked, known)]

    async def _claim_and_link(self, head: Score, checked: _Checked) -> list[BackfillRow]:
        claim = await self._claim(head, checked)
        if claim.action != "claim":
            return [claim]
        return [claim, await self._link(head, checked, self.known[checked.identity.fingerprint])]

    async def _link_or_mismatch(self, head: Score, checked: _Checked, known: _Known) -> BackfillRow:
        if known.name != checked.name:
            detail = f"the fingerprint is registered as {known.name!r}, not {checked.name!r}"
            return _row("name_mismatch", head, checked.name, detail)
        return await self._link(head, checked, known)

    def _check(self, head: Score) -> _Checked | BackfillRow:
        try:
            identity = self.registry.identify(head.url4_expression)
            name = normalize_system_name(head.spec_id)
        except (InvalidUrl4, Url4TooLarge) as exc:
            return _row("invalid_url4", head, None, str(exc))
        except InvalidSystemName as exc:
            return _row("invalid_name", head, None, exc.message)
        return (
            _row("no_owner", head, name, "the head has no submitter to own the system")
            if head.submitted_by is None
            else _Checked(identity, name, head.submitted_by)
        )

    async def _known_revision(self, fingerprint: str) -> _Known | None:
        if fingerprint in self.known:
            return self.known[fingerprint]
        ref = await self.repository.find_revision_by_fingerprint(fingerprint)
        if ref is None:
            return None
        self.known[fingerprint] = _Known(ref.system.name, ref)
        return self.known[fingerprint]

    async def _claim(self, head: Score, checked: _Checked) -> BackfillRow:
        name = checked.name
        if name in self.names or await self.repository.find_system_by_name(name) is not None:
            # Report, never apply: the name belongs to another fingerprint.
            return _row("clash", head, name, "the name belongs to another fingerprint")
        ref: RevisionRef | None = None
        if self.apply:
            try:
                ref = await self.repository.create_system_with_first_revision(
                    name=name, owner=checked.owner, identity=checked.identity
                )
            except RegistryWriteConflict:
                return _row("clash", head, name, "lost a race for the name or the fingerprint")
        self.names[name] = checked.identity.fingerprint
        self.known[checked.identity.fingerprint] = _Known(name, ref)
        return _row("claim", head, name, f"system owned by {checked.owner}")

    async def _link(self, head: Score, checked: _Checked, known: _Known) -> BackfillRow:
        key = (_benchmark_id(head), head.benchmark_revision, checked.identity.fingerprint)
        if key in self.linked or await _board_has_linked_head(head, known.ref):
            # INVARIANT: at most one linked head per system revision on a board and revision
            # (the I-S1 partial unique index). The extra head stays unlinked; never merged.
            return _row("duplicate_head", head, checked.name, "another head is linked here")
        self.linked.add(key)
        if self.apply and known.ref is not None:
            await Score.filter(id=head.id, system_revision_id__isnull=True).update(
                system_revision_id=known.ref.id
            )
        return _row("link", head, checked.name, "linked to its system revision")


def _benchmark_id(head: Score) -> str:
    # WHY getattr: the FK attribute `benchmark_id` is added by Tortoise at init, so pyright cannot
    # see it (the same cast is in baseline_store.py).
    return cast(str, getattr(head, "benchmark_id"))


def _row(action: BackfillAction, head: Score, name: str | None, detail: str) -> BackfillRow:
    return BackfillRow(action, head.id, _benchmark_id(head), name, detail)


async def _public_unlinked_heads() -> list[Score]:
    # The NULL-is-public rule of store.py: a benchmark with no visibility reads public.
    public = Q(benchmark__visibility="public") | Q(benchmark__visibility__isnull=True)
    return await Score.filter(public, system_revision_id__isnull=True).order_by(
        "submitted_at", "id"
    )


async def _board_has_linked_head(head: Score, ref: RevisionRef | None) -> bool:
    if ref is None:
        return False  # a planned revision has no rows yet
    query = Score.filter(benchmark_id=_benchmark_id(head), system_revision_id=ref.id)
    if head.benchmark_revision is None:
        query = query.filter(benchmark_revision__isnull=True)
    else:
        query = query.filter(benchmark_revision=head.benchmark_revision)
    return await query.exists()


async def backfill_systems(
    *, apply: bool, repository: SystemRepository, registry: RegistryService
) -> list[BackfillRow]:
    return await _Pass(apply=apply, repository=repository, registry=registry).run()


def format_report(rows: Sequence[BackfillRow], *, applied: bool) -> str:
    lines = [APPLIED_BANNER if applied else DRY_RUN_BANNER]
    lines.extend(
        "\t".join([row.action, str(row.score_id), row.benchmark_id, row.name or "", row.detail])
        for row in rows
    )
    counts = Counter(row.action for row in rows)
    lines.append("counts:")
    lines.extend(f"{action}: {count}" for action, count in sorted(counts.items()))
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Register legacy public heads as system names and link them (erd.md §6.4).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true", help="Report every action and write nothing."
    )
    mode.add_argument("--apply", action="store_true", help="Write the claims and the links.")
    return parser


async def _run(*, apply: bool) -> str:
    # Database lifecycle only; the decisions live in `backfill_systems`.
    settings = Settings()
    await init_db(settings.database_url)
    try:
        repository = TortoiseSystemRepository()
        registry = RegistryService(repository, Url4Fingerprinter())
        rows = await backfill_systems(apply=apply, repository=repository, registry=registry)
        return format_report(rows, applied=apply)
    finally:
        await close_db()


def main(argv: Sequence[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    print(asyncio.run(_run(apply=args.apply)))


if __name__ == "__main__":
    main()
