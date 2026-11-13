#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Audit the `ignore:` rules in .github/dependabot.yml so they expire instead of rotting.

An ignore rule is a promise that something upstream is broken. Promises rot: when the blocker
lifts, nothing notices, and a tree stays pinned majors behind for a reason that expired. This
re-checks every promise against live data.

Two checks, with DELIBERATELY different severities:

  DRIFT  -> exit 1.  An ignore with no registry entry, or an entry with no ignore, is OUR OWN
                     inconsistency and is always fixable on the spot. Failing here is what stops
                     an undocumented ignore ever landing.

  LIFTED -> exit 0.  A blocker that has cleared only WARNS. Failing a PR because upstream shipped
                     a release would train people to disable the check, which is strictly worse
                     than the rot it was meant to catch. The weekly scheduled run is what makes
                     these visible.

Usage:
    uv run .claude/scripts/audit_dependabot_ignores.py [--offline]

`--offline` skips registry lookups (drift checks still run) so the audit is usable without
network — e.g. in a pre-commit hook.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

try:
    import yaml
except ImportError:
    sys.exit(
        "ERROR: PyYAML required. Run via `uv run .claude/scripts/audit_dependabot_ignores.py`"
    )

CONFIG = pathlib.Path(".github/dependabot.yml")
REGISTRY = pathlib.Path(".github/dependabot-ignores.yml")

GREEN, RED, WARN = "✓", "✗", "!"


# --- version reasoning ---------------------------------------------------------------
#
# AIDEV-NOTE: this compares MAJORS only, not full semver. That is a deliberate limit, not an
# oversight — every ignore we write is a major-boundary hold (">=6", ">=10", ">=3.14"), and a
# full semver implementation would be a lot of surface area to get subtly wrong for no gain.
# If a future ignore needs minor-level precision, this is the function to replace, and the test
# to write first is the one that proves the old logic gets it wrong.


def ignored_floor(spec: str) -> tuple[int, int | None] | None:
    """The (major, minor) an ignore starts at. `">=3.14"` -> (3, 14); `">=6"` -> (6, None)."""
    m = re.search(r"(\d+)(?:\.(\d+))?", spec)
    if not m:
        return None
    return int(m.group(1)), (int(m.group(2)) if m.group(2) else None)


def range_admits_major(npm_range: str, major: int) -> bool:
    """Does this npm peer range admit any version of `major`?

    Handles the shapes that actually occur in our blockers:
        "^5.x"                        -> {5}
        "^3 || ^4 || ... || ^9.7"     -> {3..9}
        ">=4.8.4 <6.1.0"              -> {4,5,6}   (6 only because the bound is 6.1, not 6.0)
    Anything unrecognised returns True — i.e. "assume liftable, make a human look". A false
    warning costs a glance; a false silence costs the whole point of this script.
    """
    admitted: set[int] = set()
    recognised = False

    for clause in npm_range.split("||"):
        clause = clause.strip()
        if not clause:
            continue

        caret = re.fullmatch(r"\^\s*(\d+)(?:\.[\dx*]+)*", clause)
        if caret:
            admitted.add(int(caret.group(1)))
            recognised = True
            continue

        dotx = re.fullmatch(r"(\d+)\.[x*]", clause)
        if dotx:
            admitted.add(int(dotx.group(1)))
            recognised = True
            continue

        lo = re.search(r">=?\s*(\d+)(?:\.(\d+))?", clause)
        hi = re.search(r"<=?\s*(\d+)(?:\.(\d+))?", clause)
        if lo or hi:
            start = int(lo.group(1)) if lo else 0
            if hi:
                hi_major, hi_minor = int(hi.group(1)), hi.group(2)
                # "<6.1.0" admits some of major 6; "<6.0.0" admits none of it.
                end = hi_major if (hi_minor and int(hi_minor) > 0) else hi_major - 1
            else:
                end = max(start, major)  # open upper bound
            admitted.update(range(start, end + 1))
            recognised = True
            continue

        exact = re.fullmatch(r"(\d+)(?:\.\d+)*", clause)
        if exact:
            admitted.add(int(exact.group(1)))
            recognised = True

    if not recognised:
        return True
    return major in admitted


# --- blocker probes ------------------------------------------------------------------


def probe_npm_peer(blocker: dict, floor: tuple[int, int | None]) -> tuple[bool, str]:
    """Returns (lifted, detail). Reads the blocking package's CURRENT peer range."""
    pkg, peer = blocker["package"], blocker["peer"]
    r = subprocess.run(
        ["npm", "view", pkg, "peerDependencies", "--json"],
        capture_output=True,
        text=True,
        timeout=90,
        # check=False deliberately: a registry lookup failing (network, renamed package) must
        # NOT crash the audit. It is handled below as "treated as still blocking", which is the
        # safe direction — a transient npm hiccup should never look like a lifted blocker.
        check=False,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return (
            False,
            f"could not read {pkg} peerDependencies (treated as still blocking)",
        )
    try:
        peers = json.loads(r.stdout) or {}
    except json.JSONDecodeError:
        return False, f"unparseable peerDependencies for {pkg}"
    rng = peers.get(peer)
    if rng is None:
        # The blocker no longer declares this peer at all — the constraint is gone.
        return True, f"{pkg} no longer declares a `{peer}` peer at all"
    lifted = range_admits_major(rng, floor[0])
    return lifted, f"{pkg} peer {peer}: {rng!r}"


def probe_ci_matrix(blocker: dict, floor: tuple[int, int | None]) -> tuple[bool, str]:
    """Returns (lifted, detail). Reads a workflow's version matrix from disk."""
    wf = pathlib.Path(blocker["workflow"])
    if not wf.exists():
        return False, f"{wf} not found (treated as still blocking)"
    key = blocker["matrix_key"]
    found: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == key:
                    # AIDEV-NOTE: both shapes occur and BOTH must be read. The test
                    # matrices use a list ["3.12","3.13"]; a scalar "3.12" still appears on
                    # single-version jobs (screamingface-engine's conformance job, and any workflow
                    # that pins one interpreter deliberately). An earlier version handled
                    # only the list and fell through to "no matrix -> still blocking",
                    # which was the right answer by accident.
                    #
                    # Corrected in OME-750: this note used to cite scoreboard as THE
                    # scalar case, and that PR is what gave scoreboard a list. The scalar
                    # branch is still needed — just not for that reason.
                    vals = v if isinstance(v, list) else [v]
                    for x in vals:
                        s = str(x)
                        # `python-version: ${{ matrix.python-version }}` is the CONSUMER of the
                        # matrix, not a version. Keeping it would clutter the report and could
                        # never match a real version anyway.
                        if "${{" not in s:
                            found.add(s)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(yaml.safe_load(wf.read_text()))
    if not found:
        return False, f"no `{key}` found in {wf.name} (treated as still blocking)"
    target = f"{floor[0]}.{floor[1]}" if floor[1] is not None else str(floor[0])
    lifted = any(v == target or v.startswith(target + ".") for v in found)
    return lifted, f"{wf.name} {key} = {sorted(found)}"


PROBES = {"npm_peer": probe_npm_peer, "ci_matrix": probe_ci_matrix}


# --- main ----------------------------------------------------------------------------


def key_of(directory: str, dep: str, versions) -> tuple[str, str, str]:
    v = versions if isinstance(versions, str) else ",".join(versions or [])
    return (directory, dep.lower(), v)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offline", action="store_true", help="skip registry lookups")
    args = ap.parse_args()

    for f in (CONFIG, REGISTRY):
        if not f.exists():
            print(f"{RED} {f} not found — run from the repo root")
            return 1

    cfg = yaml.safe_load(CONFIG.read_text())
    reg = yaml.safe_load(REGISTRY.read_text()) or {}

    actual = {}
    for entry in cfg.get("updates", []):
        for ig in entry.get("ignore") or []:
            actual[
                key_of(entry["directory"], ig["dependency-name"], ig.get("versions"))
            ] = ig

    declared = {}
    for item in reg.get("ignores", []):
        declared[key_of(item["directory"], item["dependency"], item["versions"])] = item

    # --- drift: strict 1:1, both directions ---
    undocumented = sorted(set(actual) - set(declared))
    orphaned = sorted(set(declared) - set(actual))

    print(f"dependabot.yml ignores : {len(actual)}")
    print(f"registry entries       : {len(declared)}\n")

    if undocumented or orphaned:
        for d, dep, v in undocumented:
            print(f"{RED} UNDOCUMENTED  {d}  {dep} {v}")
            print("    every ignore needs an entry in .github/dependabot-ignores.yml")
        for d, dep, v in orphaned:
            print(f"{RED} ORPHANED      {d}  {dep} {v}")
            print("    registry entry has no matching ignore in .github/dependabot.yml")
        print("\nDRIFT — the two files disagree. This is ours to fix; failing.")
        return 1
    print(f"{GREEN} no drift — every ignore is documented, every entry is live\n")

    if args.offline:
        print("(--offline: blocker probes skipped)")
        return 0

    # --- are any blockers now lifted? ---
    lifted_any = False
    for k in sorted(actual):
        item = declared[k]
        directory, dep, versions = k
        floor = ignored_floor(versions)
        if floor is None:
            print(f"{WARN} {directory}  {dep} {versions}: cannot parse a version floor")
            continue
        blocker = item.get("blocker")
        if (
            blocker is None
        ):  # no probe applies (e.g. an upstream data regression): the note says why
            print(
                f"{WARN} {directory}  {dep} {versions}: no blocker probe; lift by hand"
            )
            continue
        probe = PROBES.get(blocker.get("kind"))
        if probe is None:
            print(
                f"{RED} unknown blocker kind {blocker.get('kind')!r} for {dep} in {directory}"
            )
            return 1
        try:
            lifted, detail = probe(blocker, floor)
        except (subprocess.TimeoutExpired, OSError) as exc:
            print(
                f"{WARN} {directory}  {dep} {versions}: probe failed ({exc}); skipping"
            )
            continue

        ticket = item.get("ticket") or "no ticket"
        if lifted:
            lifted_any = True
            print(f"{WARN} LIFTABLE   {directory}  {dep} {versions}   [{ticket}]")
            print(f"      {detail}")
            print("      the blocker has cleared — this ignore can probably be removed")
        else:
            print(f"{GREEN} blocking   {directory}  {dep} {versions}   [{ticket}]")
            print(f"      {detail}")

    if lifted_any:
        print(
            "\n"
            + WARN
            + " one or more ignores look liftable. NOT failing the build: upstream shipping a"
            "\n  release should not break an unrelated PR. Open a ticket and remove the ignore."
        )
        # GitHub Actions annotation so it surfaces in the run summary.
        print(
            "::warning title=Dependabot ignore may be liftable::"
            "A blocker recorded in .github/dependabot-ignores.yml has cleared — see the log."
        )
    else:
        print(f"\n{GREEN} every ignore still has a live blocker")
    return 0


if __name__ == "__main__":
    sys.exit(main())
