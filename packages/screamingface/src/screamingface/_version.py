"""Where `sf.__version__` gets its answer.

Mental model: the version number is written in exactly ONE place — `pyproject.toml`. Rather than
keeping a second copy in the source (which drifts the moment a release bumps one and not the
other), the package asks the installer at import time: "what did you record for the
`screamingface` distribution?"

Stages, in execution order:

1. Ask `importlib.metadata` for the version of the installed `screamingface` distribution. In any
   normal install — a wheel, an sdist, or an editable `uv sync` — this is the string that was
   copied out of `pyproject.toml` when the distribution was built.
2. If no such distribution is registered, the package is being imported straight off a source tree
   on `sys.path` with nothing installed. Report `SOURCE_TREE_VERSION` instead of letting
   `PackageNotFoundError` escape.

Worked example: `pyproject.toml` says `version = "0.1.1.post5"`, so the install records
`0.1.1.post5` in its metadata, stage 1 reads that back, and `sf.__version__` is `"0.1.1.post5"`.
Delete the install and the same import yields `"0.0.0+source"` — a marker, not a traceback.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version

# WHY: this is the *distribution* name from pyproject's `[project] name`, which happens to spell
# the same as the import package. They are separate namespaces, and only the distribution name is
# what `importlib.metadata` can look up.
DISTRIBUTION_NAME = "screamingface"

# INVARIANT: the fallback is never mistaken for a release. A bug report quoting a release-shaped
# string would send a maintainer hunting for a tag that was never cut, so the marker stays pinned
# at 0.0.0 with a local-version segment naming where it came from.
SOURCE_TREE_VERSION = "0.0.0+source"


def resolve_version() -> str:
    """Read the installed distribution's version, or the source-tree marker if there is none.

    Returns:
        The version string recorded for the installed `screamingface` distribution — the value
        `sf.__version__` reports — or `SOURCE_TREE_VERSION` when the package is imported from a
        source tree that was never installed.
    """

    try:
        return distribution_version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        # INVARIANT: a missing version *label* must never be the reason `import screamingface`
        # fails. Failing closed here would turn "I cannot tell you the version" into "the library
        # will not load", for an attribute nothing else depends on.
        return SOURCE_TREE_VERSION
