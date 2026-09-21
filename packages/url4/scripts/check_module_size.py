"""Module-size ratchet: the largest source modules may only shrink.

Run from the package root (CI does)::

    uv run python scripts/check_module_size.py

Line counts are a proxy, not a quality measure. This gate exists to keep the
reviewed hotspot splits (report.md findings H1/M1) from silently regrowing: a
module that earned a split must not creep back over its cap one import at a
time. Lower a BASELINE entry when its module shrinks for good; never raise one
to make CI pass.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Physical line count (``wc -l``) when this ratchet was added. Lower an entry
# when its module shrinks; never raise it to make CI pass.
BASELINE: dict[str, int] = {
    "core/grammar.py": 944,
    "dag/_lowering.py": 737,
    "core/render.py": 687,
    "dag/executor.py": 524,
    "peer/server.py": 501,
    "io/layer.py": 197,
    "observe.py": 483,
    "core/parser.py": 471,
    "core/builders.py": 468,
    "dag/nodes/group.py": 298,
    "dag/nodes/fetch.py": 285,
    "dag/nodes/_shared.py": 257,
    "dag/nodes/iteration.py": 218,
    "cli/_serve.py": 340,
}

_SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "url4"


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def main() -> int:
    """Print every capped module's count and fail when one exceeds its cap."""
    if not _SRC_DIR.is_dir():
        print(f"error: source directory not found: {_SRC_DIR}", file=sys.stderr)
        return 1

    failures: list[str] = []
    for rel, cap in sorted(BASELINE.items()):
        path = _SRC_DIR / rel
        if not path.is_file():
            failures.append(f"{rel}: missing — update BASELINE when a module moves")
            continue
        count = _line_count(path)
        marker = "  << over cap" if count > cap else ""
        print(f"{count:5d} / {cap:5d}  {rel}{marker}")
        if count > cap:
            failures.append(f"{rel}: {count} lines, {count - cap} over its cap of {cap}")

    if failures:
        print(f"\nerror: {len(failures)} module(s) above their size cap:", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        print(
            "Split the module by reason to change (report.md) — do not raise the cap.",
            file=sys.stderr,
        )
        return 1
    print("all capped modules within baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
