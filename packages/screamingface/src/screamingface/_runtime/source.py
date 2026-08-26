"""Where the runtime's application code comes from — live checkout or installed package.

Think of `screamingface up` as one command with two code sources. A user who
`pip install screamingface` runs the build-time copies vendored into the wheel; a
developer inside the ScreamingFace monorepo must run the live `apps/` and
`packages/url4` code, or the stack quietly tests a stale snapshot (OME-1001). This
module answers "which source?" once, in three stages:

1. **Detect** — `checkout_root` walks a fixed number of directories up from this very
   file and demands the full repo marker set (SDK pyproject, all three app source
   trees, the engine's `url4.toml`, the url4 package). All markers or nothing: a pip
   install never sits inside that layout, so it resolves to "bundled".
2. **Resolve** — `resolve_source` lets `SCREAMINGFACE_RUNTIME_SOURCE=checkout|bundled`
   force either mode (forcing `checkout` outside a checkout is an error), otherwise
   trusts detection.
3. **Activate** — `activate` prepends the checkout's source directories to
   `sys.path` so live code shadows any stale copy in site-packages;
   `child_environment` does the same for child interpreters via `PYTHONPATH`.

Worked example: a dev edits `apps/aigateway/src/aigateway/main.py` and runs
`screamingface up` from the repo. Detection finds the checkout, activation puts
`<repo>/apps/aigateway/src` ahead of the venv's stale `aigateway` copy, and the
restarted gateway serves the edit — the same command a user runs, one code path
earlier.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# INVARIANT: one spelling of the forcing variable — `resolve_source` reads it, boot
# logging and docs name it.
SOURCE_ENVIRONMENT_VARIABLE = "SCREAMINGFACE_RUNTIME_SOURCE"
MODE_CHECKOUT = "checkout"
MODE_BUNDLED = "bundled"

# WHY these four: exactly the trees the wheel vendors at build time
# (scripts/runtime_build_hook.py) — what the bundle copies is what the checkout must
# serve live.
_SOURCE_DIRECTORIES = (
    Path("apps") / "aigateway" / "src",
    Path("apps") / "scoreboard" / "src",
    Path("apps") / "screamingface-engine" / "src",
    Path("packages") / "url4" / "src",
)

# INVARIANT: detection matches the real ScreamingFace repo only — every marker must
# exist, so a stray `apps/` folder near site-packages can never flip a pip install
# into checkout mode (OME-1001 don't-regress).
_CHECKOUT_MARKERS = (
    Path("packages") / "screamingface" / "pyproject.toml",
    Path("apps") / "aigateway" / "src" / "aigateway" / "__init__.py",
    Path("apps") / "scoreboard" / "src" / "scoreboard" / "__init__.py",
    Path("apps") / "screamingface-engine" / "src" / "screamingface_engine" / "__init__.py",
    Path("apps") / "screamingface-engine" / "url4.toml",
    Path("packages") / "url4" / "src" / "url4" / "__init__.py",
)

# <root>/packages/screamingface/src/screamingface/_runtime/source.py — five parents
# between this file and the checkout root (matches config.py's resource fallbacks).
_ANCHOR_DEPTH = 5


@dataclass(frozen=True, slots=True)
class RuntimeSource:
    mode: str
    root: Path | None

    def describe(self) -> str:
        if self.mode == MODE_CHECKOUT:
            return f"checkout ({self.root})"
        return "bundled"


def checkout_root(anchor: Path | None = None) -> Path | None:
    """The surrounding ScreamingFace checkout root, or None when installed elsewhere."""

    location = (anchor if anchor is not None else Path(__file__)).resolve()
    parents = location.parents
    if len(parents) <= _ANCHOR_DEPTH:
        return None
    candidate = parents[_ANCHOR_DEPTH]
    if all((candidate / marker).exists() for marker in _CHECKOUT_MARKERS):
        return candidate
    return None


def resolve_source(environment: Mapping[str, str], anchor: Path | None = None) -> RuntimeSource:
    forced = environment.get(SOURCE_ENVIRONMENT_VARIABLE)
    if forced not in (None, MODE_CHECKOUT, MODE_BUNDLED):
        raise RuntimeError(
            f"{SOURCE_ENVIRONMENT_VARIABLE} must be '{MODE_CHECKOUT}' or '{MODE_BUNDLED}', "
            f"got {forced!r}"
        )
    if forced == MODE_BUNDLED:
        return RuntimeSource(mode=MODE_BUNDLED, root=None)
    root = checkout_root(anchor)
    if forced == MODE_CHECKOUT and root is None:
        raise RuntimeError(
            f"{SOURCE_ENVIRONMENT_VARIABLE}={MODE_CHECKOUT} but no ScreamingFace checkout "
            "surrounds this installation"
        )
    if root is None:
        return RuntimeSource(mode=MODE_BUNDLED, root=None)
    return RuntimeSource(mode=MODE_CHECKOUT, root=root)


def source_directories(source: RuntimeSource) -> tuple[str, ...]:
    if source.mode != MODE_CHECKOUT or source.root is None:
        return ()
    return tuple(str(source.root / directory) for directory in _SOURCE_DIRECTORIES)


def activate(source: RuntimeSource) -> None:
    """Make the checkout's live code win over any installed build-time copy."""

    # INVARIANT: precedence, not mere presence — an editable install's .pth can put a
    # source dir on sys.path already, but BEHIND site-packages where the stale
    # vendored copy still wins. Idempotent: repeated activation never accumulates
    # duplicates.
    for entry in reversed(source_directories(source)):
        while entry in sys.path:
            sys.path.remove(entry)
        sys.path.insert(0, entry)


def verify_live_modules(source: RuntimeSource, modules: Mapping[str, object]) -> None:
    """Fail loudly if checkout mode imported anything outside the checkout.

    WHY: the boot log claims "runtime source: checkout" — if a stale installed copy
    slipped past activation, benchmarks would silently test the wrong code, which is
    the exact failure OME-1001 exists to kill.
    """

    if source.mode != MODE_CHECKOUT or source.root is None:
        return
    prefix = str(source.root) + os.sep
    stale = {
        name: file
        for name, module in modules.items()
        if (file := getattr(module, "__file__", None)) and not str(Path(file)).startswith(prefix)
    }
    if stale:
        raise RuntimeError(
            f"checkout mode is active but stale installed copies were imported: {stale}"
        )


def child_environment(source: RuntimeSource, environment: Mapping[str, str]) -> dict[str, str]:
    """An environment for a fresh child interpreter that must see the same source."""

    passed = dict(environment)
    entries = source_directories(source)
    if not entries:
        return passed
    existing = passed.get("PYTHONPATH")
    combined = (*entries, existing) if existing else entries
    passed["PYTHONPATH"] = os.pathsep.join(combined)
    return passed


def state_record(source: RuntimeSource) -> dict[str, str | None]:
    """The identity `screamingface up` compares before adopting a running stack."""

    return {"mode": source.mode, "root": str(source.root) if source.root else None}


__all__: list[str] = []
