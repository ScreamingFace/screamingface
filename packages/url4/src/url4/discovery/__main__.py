"""`python -m url4.discovery` — lint catalogs and check node files from a shell.

A library nobody can run is a library nobody runs. This is the entry point CI calls and
an author calls while editing, and it exists here rather than as a `url4` subcommand
because it is a development tool, not part of the node's product surface.

    python -m url4.discovery lint  catalog.schema.json ...
    python -m url4.discovery check url4.json --catalog url4-node.schema.json

Exit codes: 0 clean, 1 defects found, 2 the input was not the kind of document expected.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from url4.discovery.catalog import NotACatalog, catalog_of, format_defects, lint_catalog
from url4.discovery.scope import NODE, USER, walk_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="url4.discovery", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    lint = sub.add_parser("lint", help="check that catalogs are well-formed")
    lint.add_argument("paths", nargs="+", type=Path)

    check = sub.add_parser("check", help="check a config instance against its catalog")
    check.add_argument("instance", type=Path)
    check.add_argument("--catalog", required=True, type=Path)
    check.add_argument(
        "--as",
        dest="actor",
        default=NODE,
        choices=[NODE, USER],
        help="who is writing (default: node, i.e. a node file or a mount's config)",
    )

    args = parser.parse_args(argv)
    return _lint(args.paths) if args.command == "lint" else _check(args)


def _lint(paths: list[Path]) -> int:
    worst = 0
    for path in paths:
        try:
            defects = lint_catalog(_load(path))
        except NotACatalog as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            worst = max(worst, 2)
            continue
        except OSError as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            worst = max(worst, 2)
            continue
        if defects:
            print(f"{path}: {len(defects)} defect(s)")
            print(format_defects(defects))
            worst = max(worst, 1)
        else:
            print(f"{path}: ok")
    return worst


def _check(args: argparse.Namespace) -> int:
    catalog = catalog_of(_load(args.catalog))
    if catalog is None:
        print(f"{args.catalog}: not a config catalog", file=sys.stderr)
        return 2
    violations = walk_config(_load(args.instance), catalog, actor=args.actor)
    if not violations:
        print(f"{args.instance}: ok")
        return 0
    print(f"{args.instance}: {len(violations)} violation(s)")
    for violation in violations:
        print(f"  - {violation.pointer}: {violation.detail} [{violation.code}]")
    return 1


def _load(path: Path) -> object:
    with path.open("rb") as handle:
        return json.load(handle)


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
