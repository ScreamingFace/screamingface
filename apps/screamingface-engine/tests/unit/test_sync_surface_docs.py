"""The origin's two error dialects are stated where an API consumer reads them (OQ-3.1).

FEATURE (unit 3, prd/03 §7): one public origin serves two surfaces with two error
envelopes. The sync mount surface is a `url4` node surface and returns `url4`'s
``{"error": {"code", "message"}}``; every engine REST path returns RFC 9457
``application/problem+json``. OQ-3.1 keeps BOTH dialects and makes stating the split a
unit-3 deliverable.

WHY these assertions: `/openapi.json` is a served artifact, so the statement is part of the
app's behaviour and testable as such. README prose is deliberately NOT asserted here — see the
module docstring of `test_cache_docs_surface`, which pins only the served documents so an
editorial improvement cannot redden the build.
"""

from __future__ import annotations

from typing import Any

from screamingface_engine.app import create_app


def _schema() -> dict[str, Any]:
    return create_app().openapi()


def test_the_api_description_states_the_two_error_dialects() -> None:
    """The split must be discoverable in the one document every API consumer can fetch."""
    description = _schema()["info"]["description"]

    assert "RFC 9457" in description
    assert "application/problem+json" in description
    assert '{"error"' in description, "url4's envelope must be shown verbatim"
    assert "mount" in description.casefold(), "the mount exception must be named, not implied"


def test_every_declared_router_tag_states_which_envelope_it_speaks() -> None:
    """A consumer reads the tag it calls, so each documented tag carries the split.

    INVARIANT: only tags a documented path actually uses are checked. An UNUSED declared tag
    would render empty in Scalar, which `test_docs_ops` already forbids; a note on one would
    document a surface that has no operations.
    """
    schema = _schema()
    used = {
        tag
        for path in schema["paths"].values()
        for operation in path.values()
        for tag in operation.get("tags", [])
    }
    declared = {tag["name"]: tag for tag in schema.get("tags", [])}

    assert used <= set(declared), f"tags used but not declared: {sorted(used - set(declared))}"
    for name in sorted(used):
        description = declared[name].get("description", "")
        assert "RFC 9457" in description, f"tag {name!r} does not state its error dialect"
        assert "mount" in description.casefold(), f"tag {name!r} omits the mount exception"


def test_the_artifact_route_tag_is_declared_not_implicit() -> None:
    """The artifact redeemer is the one engine path a sync caller reaches (the 303).

    Its tag must be metadata with a description rather than FastAPI auto-adding a bare name.
    """
    declared = {tag["name"] for tag in _schema().get("tags", [])}

    assert "Runs" in declared
