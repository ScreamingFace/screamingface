"""Tests for the catalog gate (.github/scripts/lint_catalogs.py).

A gate nobody tests is a gate that reports green when it is broken. These exist mostly to
pin the ONE property that is hard to see in CI output: that a clean run means the linter
actually ran, rather than that it found nothing to run on.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "lint_catalogs", Path(__file__).parent / "lint_catalogs.py"
)
assert _SPEC and _SPEC.loader
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("url4") is None,
    reason="the url4 package is not installed in this environment",
)

GOOD: dict[str, Any] = {
    "$id": "url4-config",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "server": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "port": {
                    "type": "integer",
                    "x-scope": "node",
                    "description": "Bind port.",
                }
            },
        }
    },
}


def write(root: Path, name: str, doc: object) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# --- the self-check ----------------------------------------------------------------


def test_the_known_bad_fixture_really_is_bad() -> None:
    """THE PROPERTY THE WHOLE GATE RESTS ON. If this fixture ever lints clean, a clean
    result from the gate means nothing — so the gate proves itself against it before
    trusting any real catalog."""
    from url4.discovery.catalog import lint_catalog

    assert lint_catalog(gate.SELF_CHECK), (
        "the self-check fixture no longer has a defect"
    )


def test_the_gate_fails_loudly_when_the_linter_is_broken(monkeypatch, capsys) -> None:
    """A linter that returns nothing must produce a RED build, not a green one reading
    '0 catalogs, all fine'."""
    import url4.discovery.catalog as catalog_module

    monkeypatch.setattr(catalog_module, "lint_catalog", lambda _doc: [])
    assert gate.main(["--root", "."]) == gate.GATE_BROKEN
    assert "GATE BROKEN" in capsys.readouterr().err


# --- discovery ----------------------------------------------------------------------


def test_a_catalog_is_found_by_its_id_not_its_filename(tmp_path: Path) -> None:
    """Keying on a naming convention would silently skip a catalog that did not follow
    it, and a skipped catalog is exactly what this gate exists to notice."""
    write(tmp_path, "nested/deeply/anything-at-all.json", GOOD)
    assert [p.name for p in gate.discover(tmp_path)] == ["anything-at-all.json"]


def test_other_json_is_ignored(tmp_path: Path) -> None:
    write(tmp_path, "package.json", {"name": "x"})
    write(tmp_path, "manifest.json", {"$id": "https://url4.ai/schemas/manifest/1"})
    assert gate.discover(tmp_path) == []


def test_unreadable_json_is_someone_elses_problem(tmp_path: Path) -> None:
    """A malformed package.json is not this gate's to report — the owner of that file
    has a better error than 'could not parse while looking for catalogs'."""
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert gate.discover(tmp_path) == []


def test_vendored_and_build_directories_are_skipped(tmp_path: Path) -> None:
    write(tmp_path, ".venv/lib/whatever.json", GOOD)
    write(tmp_path, "node_modules/pkg/schema.json", GOOD)
    write(tmp_path, "dist/schema.json", GOOD)
    assert gate.discover(tmp_path) == []


# --- outcomes -------------------------------------------------------------------------


def test_a_clean_catalog_passes(tmp_path: Path, capsys) -> None:
    write(tmp_path, "good.schema.json", GOOD)
    assert gate.main(["--root", str(tmp_path)]) == 0
    assert "all catalogs well-formed" in capsys.readouterr().out


def test_a_defective_catalog_fails_and_names_the_item(tmp_path: Path, capsys) -> None:
    broken = json.loads(json.dumps(GOOD))
    del broken["properties"]["server"]["properties"]["port"]["x-scope"]
    write(tmp_path, "bad.schema.json", broken)
    assert gate.main(["--root", str(tmp_path)]) == gate.DEFECTS_FOUND
    assert "server.port" in capsys.readouterr().out


def test_finding_none_is_reported_rather_than_passing_quietly(
    tmp_path: Path, capsys
) -> None:
    """Exit 0 is correct today — no catalog is committed — but the COUNT must be printed
    so a drop from N to 0 is visible in the log rather than invisible."""
    assert gate.main(["--root", str(tmp_path)]) == 0
    assert "catalogs found: 0" in capsys.readouterr().out


def test_require_at_least_turns_a_disappearance_into_a_failure(
    tmp_path: Path, capsys
) -> None:
    """The switch to flip once catalogs are committed: after that, finding none means
    discovery broke or someone deleted them, and both should be red."""
    assert (
        gate.main(["--root", str(tmp_path), "--require-at-least", "1"])
        == gate.GATE_BROKEN
    )
    assert "expected at least 1" in capsys.readouterr().err


def test_one_bad_catalog_fails_the_whole_run(tmp_path: Path) -> None:
    write(tmp_path, "good.schema.json", GOOD)
    broken = json.loads(json.dumps(GOOD))
    del broken["properties"]["server"]["additionalProperties"]
    write(tmp_path, "bad.schema.json", broken)
    assert gate.main(["--root", str(tmp_path)]) == gate.DEFECTS_FOUND


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
