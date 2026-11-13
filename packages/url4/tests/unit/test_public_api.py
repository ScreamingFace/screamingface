"""The package's public surface — everything the SDK story needs is one import away.

STORY: `import url4` gives a user the whole flow — build (builders), inspect
(render), execute (Client), and serve (Url4Node) — without spelunking modules.
"""

from __future__ import annotations

import url4


def test_sdk_surface_is_exported():
    for name in (
        # G1 renderer
        "render",
        "RenderError",
        "build",
        # G2 builders
        "expr",
        "src",
        "text",
        "ref",
        "self_",
        "identity",
        "struct",
        "iterate",
        "broadcast",
        "reduce",
        "expand",
        # G3 client
        "Client",
        "Url4Result",
        "evaluate_sync",
        # G4 node SDK
        "Url4Node",
        "Request",
    ):
        assert hasattr(url4, name), name
        assert name in url4.__all__, name


def test_engine_internals_stay_off_the_front_page():
    # the engine room is one level down (url4.dag), not in the root namespace
    for name in ("Graph", "Executor", "DagNode", "LoweringRegistry", "run", "compile_expression"):
        assert name not in url4.__all__, name


def test_render_is_inverse_of_build_from_the_top_level():
    e = url4.expr(url4.src("https://x", name="a", weight=0.9), intent="Summarize $a")
    assert url4.build(url4.render(e)) == e


def test_attachment_and_current_attachments_are_root_exports():
    # FEATURE: image and PDF inputs (OME-1543 U6, owner decision Q-C): a node SDK endpoint
    # reads the run's files without reaching into url4.dag.
    from url4.dag.attachment import Attachment
    from url4.dag.attachments import current_attachments

    assert url4.Attachment is Attachment
    assert url4.current_attachments is current_attachments
    assert {"Attachment", "current_attachments"} <= set(url4.__all__)
    assert url4.current_attachments() == ()
