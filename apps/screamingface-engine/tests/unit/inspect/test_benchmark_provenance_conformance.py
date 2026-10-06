"""Every registered Benchmark declares its provenance, or says why none exists (OME-1455, box ⑨).

FEATURE: Benchmark Provenance on every served catalogue entry.
STORY: as the dev onboarding a Benchmark, CI tells me by name which cover-sheet fact I forgot,
before any paid run and before any page shows a gap.

WHY this file lives in tests/unit/inspect/: the 57 imported Benchmarks join the registry only
when the inspect extra is installed, and CI's extra-installed lane runs exactly this
directory. In the extra-less lane the registry holds the 8 home-grown Benchmarks, so a strict
test there would let an import land with every field silent (review finding on PR 1236).
``test_the_registry_holds_imported_benchmarks`` keeps this lane honest: it cannot go green
by the plugin failing to register anything.

The grandfather allowlist. The Benchmarks registered on main the day this test landed were
written before the fields existed. They are listed here BY ID, once, and the only edit this
set ever takes is removal: the values PR (OME-1455 PR 3) empties it. A Benchmark whose id is
not on the list must comply today, so an eval onboarded between the two PRs cannot ship
without its provenance. Think of it as a grandfather clause for a named set, not a disabled
rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks import Benchmark  # noqa: E402
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS  # noqa: E402
from screamingface_engine.benchmarks.provenance import provenance_gaps  # noqa: E402

#: Emptied by the values PR (OME-1455 PR 3, 2026-10-06): every registered Benchmark now carries
#: its provenance. INVARIANT: stays empty. A new Benchmark declares its fields or says why not.
GRANDFATHERED: frozenset[str] = frozenset()

# parents[4] = apps/, so its parent is the monorepo root (the vocabulary twin's idiom).
_REPO_ROOT = Path(__file__).resolve().parents[4].parent
_SDK_EXAMPLES = _REPO_ROOT / "packages" / "screamingface" / "examples"

_REGISTERED: frozenset[str] = frozenset(benchmark.id for benchmark in BUILTIN_BENCHMARKS)


def test_the_registry_holds_imported_benchmarks() -> None:
    # INVARIANT: this lane exists to check the imported Benchmarks. A plugin that registers
    # none would make every parametrized test below a vacuous pass over the 8 home-grown
    # ids, so the absence is a failure here, never a skip.
    imported: set[str] = {name for name in _REGISTERED if name.startswith("inspect-")}
    assert imported, "the inspect extra is installed but no imported Benchmark registered"


@pytest.mark.parametrize("benchmark", tuple(BUILTIN_BENCHMARKS), ids=lambda b: b.id)
def test_every_registered_benchmark_declares_its_provenance_or_is_grandfathered(
    benchmark: Benchmark,
) -> None:
    # INVARIANT (spec rule 3): a silent gap is a failing test, from this PR on. A
    # NotPublished with a reason passes; None does not.
    if benchmark.id in GRANDFATHERED:
        pytest.skip("grandfathered until the values PR (OME-1455 PR 3) fills it")
    gaps: list[str] = provenance_gaps(benchmark)
    assert not gaps, (
        f"{benchmark.id} declares no {', '.join(gaps)}: fill each one, or declare it "
        "NotPublished(reason=...) where none exists"
    )


def test_the_allowlist_names_only_benchmarks_that_still_register() -> None:
    # WHY: the list is removal-only. An id that no longer registers is a stale entry that
    # would quietly grandfather a renamed Benchmark; delete it instead.
    stale: frozenset[str] = GRANDFATHERED - _REGISTERED
    assert not stale, f"allowlist names Benchmarks that no longer register: {sorted(stale)}"


@pytest.mark.parametrize("benchmark", tuple(BUILTIN_BENCHMARKS), ids=lambda b: b.id)
def test_every_declared_notebook_names_a_real_sdk_notebook(benchmark: Benchmark) -> None:
    # F10: the Run it link follows main, so the stem must be a file in the SDK's examples
    # folder. WHY read by path and never import: the two apps have separate virtualenvs;
    # this is the one place an Engine test crosses the app boundary, and it reads names only.
    if benchmark.notebook is None:
        return
    assert _SDK_EXAMPLES.exists(), "SDK examples folder moved — update the bind"
    stems: set[str] = {path.stem for path in _SDK_EXAMPLES.glob("*.ipynb")}
    assert benchmark.notebook in stems, (
        f"{benchmark.id} links notebook {benchmark.notebook!r}, which is not in {sorted(stems)}"
    )
