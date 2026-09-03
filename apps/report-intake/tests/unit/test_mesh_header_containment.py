"""`X-User-Email` is named in exactly one module — a structural assertion, not a behavioural one.

Shipped now rather than with `OME-1011`, because the value of this check is that it is already
red when someone reaches for the header in the wrong place. Once it is only added alongside the
code it constrains, it constrains nothing.

The header is trusted **only** when the mesh injected it after re-verifying the Cloudflare Access
assertion, and only after the peer check. Every additional module that reads it is another place
that has to repeat both conditions, and the one that forgets is indistinguishable from the ones
that do not.
"""

from __future__ import annotations

from pathlib import Path

_MESH_IDENTITY_HEADER = "x-user-email"
_SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "report_intake"

_MAY_NAME_IT = frozenset({"identity/mesh_identity.py"})
"""The single module allowed to name it. Adding a second entry here is the change this test
exists to make someone justify out loud."""

_MUST_NOT_NAME_IT = ("routes/reports.py", "reports/store.py")
"""Named individually because these two are where it would most plausibly be reached for: the
route sees every request, and the store writes `caller_email`."""


def _modules_naming_the_header() -> set[str]:
    return {
        str(path.relative_to(_SOURCE_ROOT))
        for path in _SOURCE_ROOT.rglob("*.py")
        if _MESH_IDENTITY_HEADER in path.read_text(encoding="utf-8").lower()
    }


def test_the_mesh_identity_header_is_named_in_exactly_one_module() -> None:
    """Equality, not containment: the adapter has landed, so a run finding it nowhere means the
    scan stopped matching rather than that the invariant strengthened."""
    assert _modules_naming_the_header() == _MAY_NAME_IT


def test_neither_the_report_route_nor_the_store_names_the_mesh_identity_header() -> None:
    """A route that reads the header itself trusts whatever a client sent."""
    named = _modules_naming_the_header()

    for module in _MUST_NOT_NAME_IT:
        assert module not in named


def test_the_source_root_this_scans_is_the_real_one() -> None:
    """A path that stops resolving turns both assertions above into a scan over nothing, which
    passes forever."""
    assert (_SOURCE_ROOT / "routes" / "reports.py").is_file()
