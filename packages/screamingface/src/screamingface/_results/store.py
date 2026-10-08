"""Durable completed-run tickets and verified result files."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass, replace
from decimal import InvalidOperation
from pathlib import Path
from typing import Any

from screamingface._atomic_file import _sync_directory, write_atomic
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import Candidate
from screamingface._results.codec import (
    candidate_data,
    candidate_value,
    json_default,
    outcome_data,
    outcome_value,
)
from screamingface._results.membership import membership_value
from screamingface.errors import ExecutionError

sync_directory = _sync_directory


def default_directory() -> Path:
    root = Path(os.environ.get("SCREAMINGFACE_DATA_DIR", "~/.screamingface")).expanduser()
    return Path(os.environ.get("SCREAMINGFACE_RESULTS_DIR", str(root / "results"))).expanduser()


def atomic_json(path: Path, value: object) -> None:
    atomic_bytes(path, json.dumps(value, default=json_default, ensure_ascii=False).encode("utf-8"))


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def write(stream):
        stream.write(value)

    write_atomic(path, write, private=True)


def storage_error(exc: OSError | sqlite3.Error, key: str = "") -> ExecutionError:
    return ExecutionError(
        f"Could not save evaluation results ({exc}). Free disk space or use "
        f"reports.get({key!r}, destination='/another/disk'); do not rerun models. "
        "Recovery requires saved metadata and either a local copy or an unexpired Engine result.",
        code="result_storage_failed",
    )


@dataclass(frozen=True)
class SavedRun:
    key: str
    path: Path
    engine_url: str
    candidate: Candidate
    outcome: _RunOutcome
    evaluation: dict[str, Any] | None = None

    @property
    def manifest(self) -> Path:
        return self.path.parent / "run.json"

    def persist_inline(self) -> _RunOutcome:
        body = self.outcome.result_body
        if body is not None:
            try:
                atomic_bytes(self.path, body.encode("utf-8"))
            except OSError as exc:
                raise storage_error(exc, self.key) from exc
        return replace(self.outcome, result_path=self.path)


class ResultStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = (directory or default_directory()).resolve()

    def record(
        self,
        engine_url: str,
        candidate: Candidate,
        outcome: _RunOutcome,
        evaluation: dict[str, Any] | None = None,
    ) -> SavedRun:
        key = hashlib.sha256(f"{engine_url}\n{outcome.run_id}".encode()).hexdigest()
        saved = SavedRun(
            key, self.directory / key / "result.json", engine_url, candidate, outcome, evaluation
        )
        value = {
            "schema": "screamingface.saved-run.v1",
            "engine_url": engine_url,
            "candidate": candidate_data(candidate),
            "outcome": outcome_data(outcome),
            "evaluation": evaluation,
        }
        try:
            atomic_json(saved.manifest, value)
        except OSError as exc:
            raise storage_error(exc, key) from exc
        return saved

    def copy_run(self, run: SavedRun) -> SavedRun:
        saved = self.record(run.engine_url, run.candidate, run.outcome, run.evaluation)
        if run.path == saved.path or not run.path.exists():
            return saved
        try:

            def copy(stream):
                with run.path.open("rb") as source:
                    shutil.copyfileobj(source, stream, length=65536)

            write_atomic(saved.path, copy, private=True)
        except OSError as exc:
            raise storage_error(exc, saved.key) from exc
        return saved

    def load(self, run_id: str) -> SavedRun:
        # WHY: run IDs are external identifiers, never interpreted as filesystem paths.
        if len(run_id) == 64 and all(c in "0123456789abcdef" for c in run_id):
            path = self.directory / run_id / "run.json"
            if path.exists():
                return self._load(path)
        matches = [run for run in self.list() if run.outcome.run_id == run_id]
        if len(matches) != 1:
            raise KeyError(f"Saved run {run_id!r} not found or ambiguous; use its saved key")
        return matches[0]

    def list(self) -> list[SavedRun]:
        runs = []
        for path in sorted(self.directory.glob("*/run.json")):
            try:
                runs.append(self._load(path))
            except (OSError, ExecutionError):
                logging.getLogger(__name__).warning("Could not read saved run %s", path)
        return runs

    def member_manifests(self, report_id: str) -> tuple[str, list[tuple[Path, str | None]]]:
        """Locate group members without trusting their decodable costs or membership.

        Paths come only from this store's manifest enumeration, never saved metadata.
        A saved candidate key can select its group even when that candidate is corrupt.
        """
        identities = self.identities()
        selected_id = report_id
        for identity, path, _ in identities:
            if path.parent.name == report_id:
                selected_id = identity
        # WHY: public evaluation identity takes precedence over a coincident saved key.
        if any(identity == report_id for identity, _, _ in identities):
            selected_id = report_id
        return selected_id, [
            (path, name) for identity, path, name in identities if identity == selected_id
        ]

    def identities(self) -> list[tuple[str, Path, str | None]]:
        """Enumerate known reports independently of full candidate metadata decoding."""
        identities: list[tuple[str, Path, str | None]] = []
        for path in sorted(self.directory.glob("*/run.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or data.get("schema") != "screamingface.saved-run.v1":
                    continue
                evaluation = data.get("evaluation")
                identity = evaluation.get("id") if isinstance(evaluation, dict) else None
                if evaluation is None:
                    identity = path.parent.name
                if not isinstance(identity, str) or not identity:
                    continue
                candidate = data.get("candidate")
                name = candidate.get("name") if isinstance(candidate, dict) else None
                name = name if isinstance(name, str) and name.strip() else None
                identities.append((identity, path, name))
            except (OSError, ValueError):
                logging.getLogger(__name__).warning("Could not read saved run %s", path)
        return identities

    def _load(self, path: Path) -> SavedRun:
        try:
            return self._decode_manifest(path)
        except (ValueError, KeyError, TypeError, AttributeError, InvalidOperation) as exc:
            raise ExecutionError(
                "Invalid saved run metadata", code="result_metadata_invalid"
            ) from exc

    def _decode_manifest(self, path: Path) -> SavedRun:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["schema"] != "screamingface.saved-run.v1":
            raise ExecutionError("Unsupported saved run version")
        return SavedRun(
            path.parent.name,
            path.parent / "result.json",
            data["engine_url"],
            candidate_value(data["candidate"]),
            outcome_value(data["outcome"]),
            membership_value(data["evaluation"]),
        )
