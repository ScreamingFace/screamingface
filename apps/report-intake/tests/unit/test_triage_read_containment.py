"""The queue's drain path is a command, never a route — a structural assertion.

Spec §1 removed `GET /v1/reports/{ref}`: it was inherited from a browser-form design that no
longer exists, nothing consumes it, and `POST /v1/reports` is unauthenticated, so a by-ref read
would make a guessable `ref` worth guessing. `OME-1009`'s follow-up gave the store three reads so
that `queue_cli.py` could drain the queue over `kubectl exec`. This test is what stops those three
becoming that endpoint under a different name.

Same shape and same reasoning as `test_mesh_header_containment.py`: the value of the check is that
it is already red when someone reaches for the read in the wrong place, and a rule that only
arrives with the code it constrains constrains nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

_SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "report_intake"

_TRIAGE_READS = ("awaiting_triage", "read_for_triage", "mark_filed")
"""The store's three console-only methods. Named unmistakably — `read_for_triage` rather than
`read` — precisely so this scan can be exact rather than a guess about which `.read(` was meant."""

_MAY_CALL_THEM = frozenset({"queue_cli.py", "reports/store.py"})
"""The store that defines them and the console that calls them. A third entry is the change this
test exists to make somebody justify out loud — and if that entry is under `routes/`, it is the
endpoint the spec removed."""


def _modules_calling(name: str) -> set[str]:
    """Modules that define or invoke `name`, by call syntax rather than by mention.

    The word boundary matters: `queue_cli` has an argparse handler called `mark_filed` beside the
    store method of the same name — the same operation at two layers — and `cli.py` passes that
    handler to `set_defaults` without calling it. A bare substring scan would read that reference
    as a triage read and this file would be about spelling instead of about reach.
    """
    called = re.compile(rf"(?<!\w){re.escape(name)}\s*\(")
    return {
        str(path.relative_to(_SOURCE_ROOT))
        for path in _SOURCE_ROOT.rglob("*.py")
        if called.search(path.read_text(encoding="utf-8"))
    }


def _modules_naming(name: str) -> set[str]:
    return {
        str(path.relative_to(_SOURCE_ROOT))
        for path in _SOURCE_ROOT.rglob("*.py")
        if name in path.read_text(encoding="utf-8")
    }


def test_the_triage_reads_are_called_only_by_the_store_and_the_console() -> None:
    """Equality, not containment: both modules exist, so a run finding a name nowhere means the
    scan stopped matching rather than that the invariant strengthened."""
    for name in _TRIAGE_READS:
        assert _modules_calling(name) == _MAY_CALL_THEM, name


def test_no_route_module_can_read_a_report_by_ref() -> None:
    """The narrow statement of the rule, kept separately because it is the one that matters: an
    HTTP handler reaching a triage read IS `GET /v1/reports/{ref}`, whatever the path is called.

    Scanned by MENTION rather than by call here, deliberately wider than the check above — a route
    module that so much as names one of these is already the change worth stopping.
    """
    mentioned = {module for name in _TRIAGE_READS for module in _modules_naming(name)}

    assert not [module for module in mentioned if module.startswith("routes/")]
