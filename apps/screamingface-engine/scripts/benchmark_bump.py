"""OME-1610: print what moving a Benchmark's published revision costs, and the lines to edit.

    just engine benchmark-bump <key>                                # from the repo root
    uv run --isolated --extra inspect python scripts/benchmark_bump.py <key>  # from the Engine

Think of it as the form a developer reads before signing: it shows the id the Benchmark
publishes, the fingerprint its inputs compute now, the WARNING (a move hides every leaderboard
result under the old id) and the hand edits for each of the two paths. It never edits a file:
the move happens by hand, in a reviewed PR, with the owner's sign-off. The rule it prints lives
in ``docs/adding-an-imported-benchmark.md`` ("Changing a Benchmark's published revision").

Exit status: 0 when the key is a Benchmark, 2 when it is not.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import NamedTuple

#: The one Benchmark with no catalogue row: its ids live in its own definition module.
MEDXPERT_KEY: str = "medxpert"
_ENGINE: str = "apps/screamingface-engine"
_ROWS: str = f"{_ENGINE}/src/screamingface_engine_inspect/benchmarks.py"
_MEDXPERT: str = f"{_ENGINE}/src/screamingface_engine/benchmarks/medxpert/definition.py"
_PUBLISHED_PINS: str = f"{_ENGINE}/tests/unit/inspect/test_published_revisions.py"
_MEDXPERT_GOLDEN: str = f"{_ENGINE}/tests/unit/test_medxpert_migration_golden.py"
_EARLY_GRADE_FIXTURE: str = f"{_ENGINE}/tests/fixtures/early_grade_compatibility.json"
_FIXTURE_EDIT: str = 'every {old} becomes {new}: medxpert\'s "revision" and each of its routes'
_ROW_PIN_EDIT: str = '"{key}": "{{new}}",  with a comment naming the old id {{old}} and why'
_FINGERPRINT_PINS: str = f"{_ENGINE}/tests/unit/inspect/test_benchmark_fingerprints.py"
_CHANGELOG: str = f"{_ENGINE}/CHANGELOG.md"
_EXIT_UNKNOWN_KEY: int = 2


class _Ids(NamedTuple):
    """A Benchmark's two ids, and the one line that hand-sets the published one.

    WHY a NamedTuple: the test loads this file by path, outside ``sys.modules``, where a
    dataclass cannot resolve its own module.
    """

    published: str
    fingerprint: str
    #: Where the published id is written, and the line as it reads there.
    home: str
    line: str
    #: Where the published id is pinned in tests: (file, the edit with {old} and {new}).
    #: WHY per Benchmark: test_published_revisions.py reads catalogue rows only, so medxpert's
    #: id is pinned by its migration golden and the early-grade fixture instead.
    published_pins: tuple[tuple[str, str], ...]
    #: False for a new row that sets no ``published_revision`` yet: it serves its fingerprint.
    hand_set: bool = True


def _ids(key: str) -> _Ids:
    """Read a Benchmark's published id and computed fingerprint; KeyError for an unknown key."""

    if key == MEDXPERT_KEY:
        from screamingface_engine.benchmarks.medxpert import definition

        return _Ids(
            definition.REVISION,
            definition.FINGERPRINT,
            _MEDXPERT,
            'REVISION = "{}"',
            (
                (_MEDXPERT_GOLDEN, '_GOLDEN_REVISION = "{new}"'),
                (_EARLY_GRADE_FIXTURE, _FIXTURE_EDIT),
            ),
        )

    from screamingface_engine_inspect import benchmarks

    imported = benchmarks.imported_benchmark(key)
    spec = next(row for row in benchmarks.BENCHMARKS if row.key == key)
    return _Ids(
        str(imported.benchmark.revision),
        imported.fingerprint,
        f"{_ROWS}, the {key} row",
        'published_revision="{}"',
        ((_PUBLISHED_PINS, _ROW_PIN_EDIT.format(key=key)),),
        hand_set=spec.published_revision is not None,
    )


def _report(key: str, ids: _Ids) -> str:
    """The WARNING and both checklists, with the exact old and new lines filled in."""

    if not ids.hand_set:
        # WHY first: an unset row serves its fingerprint, so the two ids match, but the row is
        # new and needs its id written down, not told that nothing changed.
        return (
            f"{key} sets no published_revision yet, so it serves its fingerprint "
            f"{ids.fingerprint}. Write the id down by hand, in the PR that adds the row:\n"
            f"  1. {ids.home}:\n      {ids.line.format(ids.fingerprint)}\n"
            f'  2. {_PUBLISHED_PINS}:\n      "{key}": "{ids.fingerprint}",\n'
            f'  3. {_FINGERPRINT_PINS}:\n      "{key}": "{ids.fingerprint}",\n'
        )
    if ids.published == ids.fingerprint:
        return (
            f"{key} publishes {ids.published} and computes the same fingerprint: nothing to "
            f"bump. Its exam has not changed since the id was set (the id: {ids.home}).\n"
        )
    old_line: str = ids.line.format(ids.published)
    new_line: str = ids.line.format(ids.fingerprint)
    # The numbered move checklist: the id's home, then each place a test pins it, then the
    # fingerprint, the CHANGELOG and the team; numbered here because medxpert has two pins.
    steps: list[str] = [f"{ids.home}:\n      {old_line}  ->  {new_line}"]
    steps += [
        f"{path}:\n      {edit.format(old=ids.published, new=ids.fingerprint)}"
        for path, edit in ids.published_pins
    ]
    steps += [
        f'{_FINGERPRINT_PINS}:\n      "{key}": "{ids.fingerprint}",',
        f"{_CHANGELOG}: one line naming {key}, the old and new id, and why it moved.",
        "Tell the team (a post in the team channel) and name who signed off in the PR body.",
    ]
    checklist: str = "".join(f"  {number}. {step}\n" for number, step in enumerate(steps, 1))
    return f"""\
WARNING: moving {key}'s published revision hides every leaderboard result under
{ids.published} and marks every submission to it outdated.
Move it ONLY on a fundamental change: a changed Case set, or a new Benchmark. A refactor, a
grading fix or a package bump that keeps the same Cases is NOT a reason to move it.
A move needs the owner's sign-off before it merges. This command edits nothing.

{key}
  publishes (hand-set):        {ids.published}
  computes (fingerprint now):  {ids.fingerprint}

Same Cases? Keep the id. Edit only:
  {_FINGERPRINT_PINS}
      "{key}": "{ids.fingerprint}",

Fundamental change, and the owner signed off? Edit by hand, in one PR:
{checklist}"""


def main(argv: Sequence[str]) -> int:
    """Print the report for one Benchmark key; refuse an unknown key with exit status 2."""

    if len(argv) != 1:
        print("usage: benchmark_bump.py <benchmark key>", file=sys.stderr)
        return _EXIT_UNKNOWN_KEY
    key: str = argv[0]
    try:
        ids: _Ids = _ids(key)
    except KeyError:
        print(f"{key!r} is not a Benchmark key (a catalogue row or medxpert)", file=sys.stderr)
        return _EXIT_UNKNOWN_KEY
    print(_report(key, ids), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
