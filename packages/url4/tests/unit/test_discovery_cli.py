"""`python -m url4.discovery` — the entry point CI and an author actually invoke.

Also the ONLY place the real `examples/` corpus is exercised. Those files are not part of
this package and are not committed, so every test here skips cleanly without them: the
suite must never depend on a directory that can disappear. An earlier version of this
walker kept its whole corpus outside the repo and was lost with it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from url4.discovery.__main__ import main

# <repo>/packages/url4/tests/unit/<this file> — four parents to `packages`, five to the
# repo root. `URL4_EXAMPLES` overrides it so the corpus can live anywhere.
EXAMPLES = Path(os.environ.get("URL4_EXAMPLES", Path(__file__).resolve().parents[4] / "examples"))
needs_examples = pytest.mark.skipif(
    not EXAMPLES.is_dir(), reason="the examples/ corpus is not present (it is not committed)"
)

CATALOG = {
    "$id": "url4-config",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "server": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "port": {"type": "integer", "x-scope": "node", "description": "Bind port."}
            },
        }
    },
}


def write(tmp_path: Path, name: str, doc: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# --- lint --------------------------------------------------------------------------


def test_a_clean_catalog_exits_zero(tmp_path: Path, capsys) -> None:
    assert main(["lint", str(write(tmp_path, "c.json", CATALOG))]) == 0
    assert "ok" in capsys.readouterr().out


def test_a_defective_catalog_exits_one_and_names_the_item(tmp_path: Path, capsys) -> None:
    broken = json.loads(json.dumps(CATALOG))
    del broken["properties"]["server"]["properties"]["port"]["description"]
    assert main(["lint", str(write(tmp_path, "c.json", broken))]) == 1
    assert "server.port" in capsys.readouterr().out


def test_the_wrong_kind_of_document_exits_two(tmp_path: Path, capsys) -> None:
    """Distinct from exit 1: the caller pointed the linter at the wrong file, which is
    not the same as a catalog having defects, and CI should tell them apart."""
    assert main(["lint", str(write(tmp_path, "m.json", {"$id": "something-else"}))]) == 2
    assert "expected a config catalog" in capsys.readouterr().err


def test_a_missing_file_exits_two(tmp_path: Path) -> None:
    assert main(["lint", str(tmp_path / "absent.json")]) == 2


def test_the_worst_result_across_several_files_wins(tmp_path: Path) -> None:
    good = write(tmp_path, "good.json", CATALOG)
    wrong = write(tmp_path, "wrong.json", {"$id": "other"})
    assert main(["lint", str(good), str(wrong)]) == 2


# --- check -------------------------------------------------------------------------


def test_a_valid_instance_exits_zero(tmp_path: Path) -> None:
    catalog = write(tmp_path, "c.json", CATALOG)
    instance = write(tmp_path, "url4.json", {"server": {"port": 4404}})
    assert main(["check", str(instance), "--catalog", str(catalog)]) == 0


def test_a_scope_violation_exits_one(tmp_path: Path, capsys) -> None:
    catalog = write(tmp_path, "c.json", CATALOG)
    instance = write(tmp_path, "url4.json", {"server": {"port": "4404"}})
    assert main(["check", str(instance), "--catalog", str(catalog)]) == 1
    assert "server.port" in capsys.readouterr().out


def test_checking_against_a_non_catalog_exits_two(tmp_path: Path) -> None:
    catalog = write(tmp_path, "m.json", {"$id": "other"})
    instance = write(tmp_path, "url4.json", {})
    assert main(["check", str(instance), "--catalog", str(catalog)]) == 2


# --- the real corpus, when it is there ----------------------------------------------


@needs_examples
def test_every_shipped_catalog_lints_clean() -> None:
    catalogs = [
        p
        for p in sorted(EXAMPLES.glob("*.schema.json"))
        if json.loads(p.read_text()).get("$id") == "url4-config"
    ]
    assert catalogs, "examples/ has no config catalogs"
    assert main(["lint", *map(str, catalogs)]) == 0


@needs_examples
def test_the_manifest_meta_schema_is_not_mistaken_for_a_catalog() -> None:
    manifest = EXAMPLES / "url4-endpoint-manifest.schema.json"
    if not manifest.is_file():
        pytest.skip("the manifest meta-schema is not in examples/")
    assert main(["lint", str(manifest)]) == 2
