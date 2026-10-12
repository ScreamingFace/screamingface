"""Discover known evaluations even when no candidate manifest fully decodes."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from screamingface._results.membership import membership_value
from screamingface._results.store import ResultStore, SavedRun, storage_error
from screamingface.errors import ExecutionError, ScreamingFaceError
from screamingface.report import Report


def evaluation_context(store: ResultStore, report_id: str, key: str = "") -> dict[str, Any] | None:
    # INVARIANT: minimal saved identities cannot redirect canonical metadata reads.
    if re.fullmatch(r"[A-Za-z0-9_-]+", report_id) is None:
        raise ExecutionError("Invalid saved evaluation identity", code="result_metadata_invalid")
    manifest = store.directory / "evaluations" / f"{report_id}.json"
    try:
        context = membership_value(json.loads(manifest.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise storage_error(exc, key) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise ExecutionError(
            "Invalid saved evaluation metadata", code="result_metadata_invalid"
        ) from exc
    if context is None or context["id"] != report_id:
        raise ExecutionError(
            "Saved evaluation manifest has conflicting identity", code="result_metadata_invalid"
        )
    return context


def unreadable_groups(
    store: ResultStore, known: set[str]
) -> Iterator[tuple[str, tuple[str, ...], list[tuple[Path, str | None]]]]:
    groups: dict[str, list[tuple[Path, str | None]]] = {}
    for identity, path, name in store.identities():
        if identity not in known:
            groups.setdefault(identity, []).append((path, name))
    for identity, members in groups.items():
        yield identity, _expected(store, identity, members), members


def _expected(
    store: ResultStore, identity: str, members: list[tuple[Path, str | None]]
) -> tuple[str, ...]:
    context = evaluation_context(store, identity)
    if context is not None:
        return tuple(context["candidates"])
    # WHY: legacy reports without canonical metadata still retain known candidate names.
    names = dict.fromkeys(_legacy_names(members))
    names.update((name, None) for _, name in members if name is not None)
    return tuple(names)


def _legacy_names(members: list[tuple[Path, str | None]]) -> Iterator[str]:
    for path, _ in members:
        try:
            context = membership_value(json.loads(path.read_text(encoding="utf-8"))["evaluation"])
            if context is not None:
                yield from context["candidates"]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # WHY: invalid embedded membership cannot erase independently known names;
            # full manifest failures are reported by candidate during recovery.
            continue


def unreadable_selection(store: ResultStore, report_id: str) -> SavedRun:
    identity, members = store.member_manifests(report_id)
    if not members:
        raise KeyError(f"Saved run {report_id!r} not found or ambiguous; use its saved key")
    expected = _expected(store, identity, members)
    errors: dict[str, ScreamingFaceError] = {}
    for path, name in members:
        try:
            # WHY: a racing repair may have made this candidate readable since selection.
            return store._load(path)
        except (OSError, sqlite3.Error) as exc:
            error = storage_error(exc, path.parent.name)
        except ScreamingFaceError as exc:
            error = exc
        if name is not None:
            errors[name] = error
    missing = {
        name: errors[name].code if name in errors else "result_not_received" for name in expected
    }
    raise incomplete_report(missing, errors) from next(iter(errors.values()), None)


def incomplete_report(
    missing: dict[str, str], errors: dict[str, ScreamingFaceError], partial: Report | None = None
) -> ExecutionError:
    details: dict[str, object] = {"failed": missing}
    if errors:
        details["failure_messages"] = {name: str(exc) for name, exc in errors.items()}
    return ExecutionError(
        "Evaluation recovery is incomplete; completed results are in "
        "partial_report. No models were rerun.",
        code="candidates_failed",
        details=details,
        partial_report=partial,
    )
