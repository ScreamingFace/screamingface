"""Suppression ratchet: the count of ``# type: ignore`` / ``# noqa`` may only go down.

Run from the package root (CI does)::

    uv run python scripts/check_suppressions.py

CI counts every suppression under ``src/url4`` and fails when the total rises
above :data:`BASELINE`. Remove the suppression instead of raising the baseline;
when one is removed for good, lower :data:`BASELINE` to the new count.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Count measured when this ratchet was added. Lower it when a suppression goes
# away; never raise it to make CI pass.
BASELINE = 9

_SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "url4"

_PATTERNS: dict[str, re.Pattern[str]] = {
    "type: ignore": re.compile(r"#\s*type:\s*ignore"),
    "noqa": re.compile(r"#\s*noqa"),
}


def _count_suppressions(root: Path) -> dict[str, int]:
    """Count each suppression pattern in every ``*.py`` file under *root*."""
    counts = {name: 0 for name in _PATTERNS}
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for name, pattern in _PATTERNS.items():
            counts[name] += len(pattern.findall(text))
    return counts


def main() -> int:
    """Print the suppression counts and enforce the baseline."""
    if not _SRC_DIR.is_dir():
        print(f"error: source directory not found: {_SRC_DIR}", file=sys.stderr)
        return 1

    counts = _count_suppressions(_SRC_DIR)
    total = sum(counts.values())

    for name, count in counts.items():
        print(f"{name}: {count}")
    print(f"total: {total} (baseline {BASELINE})")

    if total > BASELINE:
        print(
            f"error: {total - BASELINE} suppression(s) above the baseline of {BASELINE}. "
            "Remove the new '# type: ignore' or '# noqa'; lower BASELINE when you remove one.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
