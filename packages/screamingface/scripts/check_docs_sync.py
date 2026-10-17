"""Fail a PR that changes a public sf.* export without touching its docs page.

Public surface is the set of names in packages/screamingface/src/screamingface/__init__.py's
__all__, and the file each one is imported from. That second part is read from __init__.py's
own `from X import Y` statements, not guessed from a directory-naming convention: two of its
sources, _default_client.py and _ui/connections.py, sit under an underscore-prefixed path
despite backing real public names (configure, close, connect, disconnect, evaluate,
ConnectionPanel). A convention-based check would silently miss changes to all six.

A symbol counts as changed two ways, checked independently: its __all__ entry is new on this
branch (regardless of whether the file backing it also changed in this diff, since a PR can
promote an existing, untouched function to public by editing only __init__.py's import and
export lines), or its backing file changed. Either one requires a matching docs change.

Checks presence, not quality: a changed symbol's page must appear in the diff. Whether the
page content is actually updated to match is not checked here.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
INIT_FILE = REPO_ROOT / "packages/screamingface/src/screamingface/__init__.py"
INIT_REL = "packages/screamingface/src/screamingface/__init__.py"
API_PAGE_DIR = "public-docs/src/pages/sf-client/api"

# From symbol-page-map.md. One entry per __all__ name that has a page; the three that do not
# (__version__, OperationAccounting, OperationCache) are a named, accepted gap, not a check
# failure waiting to happen.
SYMBOL_PAGE: dict[str, str] = {
    "Client": "ClientsPage.vue",
    "AsyncClient": "ClientsPage.vue",
    "Recipe": "RecipesPage.vue",
    "CorrectiveLoop": "RecipesPage.vue",
    "SelfCorrective": "RecipesPage.vue",
    "Model": "ModelsCatalogPage.vue",
    "ModelCapability": "ModelsCatalogPage.vue",
    "ModelDetails": "ModelsCatalogPage.vue",
    "ModelInfo": "ModelsCatalogPage.vue",
    "ModelParameter": "ModelsCatalogPage.vue",
    "ModelParameterSchema": "ModelsCatalogPage.vue",
    "Fusion": "FusionsPage.vue",
    "Pipeline": "PipelinesPage.vue",
    "Url4": "Url4Page.vue",
    "Benchmark": "BenchmarksPage.vue",
    "Connection": "ConnectionsPage.vue",
    "ConnectionPanel": "ConnectionsPage.vue",
    "AsyncOAuthFlow": "ConnectionsPage.vue",
    "OAuthFlow": "ConnectionsPage.vue",
    "connect": "ConnectionsPage.vue",
    "disconnect": "ConnectionsPage.vue",
    "connections": "ConnectionsPage.vue",
    "Report": "ReportsPage.vue",
    "CandidateResult": "CandidateResultPage.vue",
    "BenchmarkInfo": "CandidateResultPage.vue",
    "CaseGrade": "CandidateResultPage.vue",
    "CaseResult": "CandidateResultPage.vue",
    "Check": "CandidateResultPage.vue",
    "Evidence": "CandidateResultPage.vue",
    "EvidenceProducer": "CandidateResultPage.vue",
    "Failure": "CandidateResultPage.vue",
    "MemberResult": "CandidateResultPage.vue",
    "OperationInfo": "CandidateResultPage.vue",
    "Usage": "UsagePage.vue",
    "Leaderboard": "LeaderboardsPage.vue",
    "LeaderboardBaseline": "LeaderboardsPage.vue",
    "LeaderboardEntry": "LeaderboardsPage.vue",
    "LeaderboardInfo": "LeaderboardsPage.vue",
    "LeaderboardScore": "LeaderboardsPage.vue",
    "leaderboards": "LeaderboardsPage.vue",
    "Event": "EventsPage.vue",
    "events": "EventsPage.vue",
    "AuthenticationError": "ErrorsPage.vue",
    "EngineUnavailableError": "ErrorsPage.vue",
    "ExecutionError": "ErrorsPage.vue",
    "EvaluationWarning": "ErrorsPage.vue",
    "LeaderboardError": "ErrorsPage.vue",
    "PlanningError": "ErrorsPage.vue",
    "ProviderConnectionError": "ErrorsPage.vue",
    "ScreamingFaceError": "ErrorsPage.vue",
    "configure": "ModulesPage.vue",
    "close": "ModulesPage.vue",
    "evaluate": "ModulesPage.vue",
    "benchmarks": "ModulesPage.vue",
    "models": "ModulesPage.vue",
}

EXEMPT = {"__version__", "OperationAccounting", "OperationCache"}


def all_names_from_source(source: str) -> set[str]:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                return {
                    elt.value
                    for elt in node.value.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                }
    raise SystemExit("no __all__ assignment found")


def parse_symbol_sources(source: str, package_dir: Path) -> dict[str, Path]:
    """Map every name __init__.py exports to the file it is imported from.

    Reads the import statements themselves, so a name backed by an underscore-prefixed file
    (_default_client.py, _ui/connections.py) is attributed correctly, unlike a check keyed
    on directory naming.
    """
    tree = ast.parse(source)
    mapping: dict[str, Path] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        if node.module == "screamingface":
            # from screamingface import benchmarks, connections, events, leaderboards, models
            for alias in node.names:
                name = alias.asname or alias.name
                mapping[name] = package_dir / f"{alias.name}.py"
        elif node.module.startswith("screamingface."):
            rel = node.module[len("screamingface.") :].replace(".", "/")
            source_file = package_dir / f"{rel}.py"
            for alias in node.names:
                name = alias.asname or alias.name
                mapping[name] = source_file
    return mapping


def read_file_at_ref(rel_path: str, ref: str) -> str | None:
    """Return a file's content at a git ref, or None if it did not exist there."""
    result = subprocess.run(
        ["git", "show", f"{ref}:{rel_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else None


def changed_files(base_ref: str) -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return set(result.stdout.splitlines())


def find_missing_for_changed(
    changed_symbols: list[str],
    newly_exported: set[str],
    changed: set[str],
) -> list[tuple[str, str]]:
    missing: list[tuple[str, str]] = []
    for name in changed_symbols:
        if name in EXEMPT:
            continue
        page = SYMBOL_PAGE.get(name)
        if page is None:
            reason = "newly exported" if name in newly_exported else "source file changed"
            note = f"(no page assigned, {reason}; add one to SYMBOL_PAGE or EXEMPT)"
            missing.append((name, note))
            continue
        page_path = f"{API_PAGE_DIR}/{page}"
        if page_path not in changed:
            missing.append((name, page_path))
    return missing


def find_missing_for_removed(removed: set[str], changed: set[str]) -> list[tuple[str, str]]:
    """A removed name still owes a docs change: its page needs updating or removing to
    match, not because a new page is needed. Skips names that were exempt or never had a
    page, since there is nothing on the page to reconcile.
    """
    missing: list[tuple[str, str]] = []
    for name in sorted(removed):
        page = SYMBOL_PAGE.get(name)
        if page is None:
            continue
        page_path = f"{API_PAGE_DIR}/{page}"
        if page_path not in changed:
            missing.append((name, f"{page_path} (removed from __all__, page not updated)"))
    return missing


def main() -> None:
    base_ref = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    changed = changed_files(base_ref)

    head_source = INIT_FILE.read_text()
    head_names = all_names_from_source(head_source)
    sources = parse_symbol_sources(head_source, INIT_FILE.parent)

    base_source = read_file_at_ref(INIT_REL, base_ref)
    base_names = all_names_from_source(base_source) if base_source is not None else set()
    newly_exported = head_names - base_names
    removed = base_names - head_names

    file_changed = {
        name
        for name in head_names
        if name in sources and str(sources[name].relative_to(REPO_ROOT)) in changed
    }
    changed_symbols = sorted(newly_exported | file_changed)

    missing = find_missing_for_changed(changed_symbols, newly_exported, changed)
    missing += find_missing_for_removed(removed, changed)

    if missing:
        print("public surface changed with no matching docs update:", file=sys.stderr)
        for name, page in missing:
            print(f"  {name} -> expected a change in {page}", file=sys.stderr)
        raise SystemExit(1)

    print(f"ok: {len(changed_symbols)} changed public symbol(s), all with a matching docs change")


if __name__ == "__main__":
    main()
