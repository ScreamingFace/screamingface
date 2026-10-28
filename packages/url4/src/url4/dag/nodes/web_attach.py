"""An attachment source reads its payload from the run's frozen manifest (``OME-1543``, F1b).

FEATURE: image and PDF inputs (epic ``OME-1529``). STORY: as an ensemble author I write
``src=https://…/photo.png;accept=image/png`` and every model call receives the image as an
attachment, while the payload carries the URL text.

INVARIANT (owner decision A, 2026-10-27 — Q-B dropped): only an attachment source (an exact
attachment ``;accept=``, :mod:`url4.dag.attachment_sources`) is ever attached, and only by the
run-start admission phase (:mod:`url4.dag._materialize`). A text source is never attached and
never fetched as bytes, whatever its body: a non-text body stays ``unsupported_content_type``.
"""

from __future__ import annotations

from url4.core.errors import ResolutionError
from url4.dag.attachment import Attachment
from url4.dag.attachment_sources import AttachmentIdentity, not_static
from url4.dag.attachments import current_run_files


def materialized_attachment(identity: AttachmentIdentity) -> str | None:
    """An attachment source's payload: its URL text, read from the run's frozen manifest.

    INVARIANT (F1b round 7): execution never fetches an attachment source. A materialized
    identity reads as its URL; an omitted ``;optional`` one re-raises its typed failure as
    permanent (so its guard drops it without a retry, and nothing is re-fetched); an identity
    the run-start manifest never saw is ``x.source_not_static``. Outside a ``run()`` there is
    no manifest: ``None``, and the node keeps today's text path.
    """
    files = current_run_files()
    if files is None:
        return None
    outcome = files.manifest.get(identity)
    if outcome is None:
        raise not_static(repr(identity.url))
    if isinstance(outcome, Attachment):
        return identity.url
    raise ResolutionError(str(outcome), code=outcome.code, permanent=True)


__all__ = ["materialized_attachment"]
