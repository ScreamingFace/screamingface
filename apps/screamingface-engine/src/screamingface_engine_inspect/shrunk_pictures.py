# pyright: reportMissingImports=false
# WHY file-level: this module imports Pillow (the `benchmarks` extra) and reads inspect's
# Sample types, both absent in the default (extra-less) install the typecheck gate runs against.
"""A Named Deviation: shrink a named Sample's oversized picture before capture (OME-1970).

FEATURE: Task replay serves each picture exactly as the eval hands it over. A few are bigger
than some hosts accept. Think of it as a photocopier set to "fit to page", used on one named
page of the exam: the listed Sample's pictures whose long side is over 8000 px are scaled down
to 8000 px, aspect kept, and every other Sample goes through untouched.

Stages of :func:`with_shrunk_pictures`, in execution order:

    Stage 1 — every listed id must name a Sample in the dataset, or the prepare stops.
    Stage 2 — each listed Sample: every ``data:`` URI picture in its messages is opened with
              Pillow; one whose long side is over ``MAX_PICTURE_SIDE_PX`` is resized with
              LANCZOS to that long side and re-encoded as PNG with Pillow's defaults (lossless,
              same mode, same data URI label). A picture within the limit keeps its bytes.
    Stage 3 — a listed Sample with no picture over the limit stops the prepare: the deviation
              no longer describes the data and must be removed by hand.

Worked example, the one row that needs it (cais/hle row ``66f1b940f8bb4425f74e4299``, ``hle``
Case 250, ``hle_diamond`` Case 35): a 14950×2780 RGBA PNG becomes 8000×1488 (2780 × 8000 /
14950 = 1487.6, rounded). Claude then takes it (8000 px per side at most), and so does GPT's
patch count: 250 × 47 = 11,750 patches of 32 px, under its 30,000 (the original needed 40,716).

INVARIANT: the re-encode is deterministic for one Pillow build, so the Case Digest seals it;
Pillow's PNG bytes differ by platform, so a row using this is sealed on linux/amd64, as the
image build replays it.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING, Any

# WHY import the side limit: the seal check refuses a picture over it, so the size a picture
# shrinks to is that same number, defined once (8000 px, Claude's limit; on the 6 Nov 2026 prod
# HLE runs every Claude Candidate refused hle Case 250's 14950 px picture).
from screamingface_engine_inspect.picture_input import MAX_PICTURE_SIDE_PX
from screamingface_engine_inspect.prepare import PrepareError

if TYPE_CHECKING:
    from inspect_ai.dataset import Sample

#: The one picture format this deviation re-encodes. WHY only PNG: its re-encode is lossless;
#: JPEG or WebP would also need a chosen quality, a decision no row has made.
_SHRINKABLE_FORMAT: str = "PNG"

_DATA_URI_PREFIX: str = "data:"
_BASE64_MARKER: str = ";base64"


def shrunk_size(width: int, height: int) -> tuple[int, int]:
    """The size a picture gets: unchanged when it fits, else its long side at the limit, aspect
    kept (14950×2780 → 8000×1488)."""

    longest: int = max(width, height)
    if longest <= MAX_PICTURE_SIDE_PX:
        return (width, height)
    scale: float = MAX_PICTURE_SIDE_PX / longest
    if width >= height:
        return (MAX_PICTURE_SIDE_PX, max(1, round(height * scale)))
    return (max(1, round(width * scale)), MAX_PICTURE_SIDE_PX)


def with_shrunk_pictures(sample_ids: Collection[str], samples: Sequence[Sample]) -> list[Sample]:
    """Apply the named deviation: the listed Samples' oversized pictures shrunk, the rest as is.

    Args:
        sample_ids: inspect_evals Sample ids (``str(Sample.id)``) the row declares in
            ``shrunk_picture_sample_ids``; a list after the replay child's JSON round trip.
        samples: the Task's Samples after the row's exclusions, in the Task's order.

    Returns:
        The Samples in the same order: a listed one as a copy carrying its shrunk pictures, every
        other one the same object.

    Raises:
        PrepareError: a listed id names no Sample, a listed Sample has no picture over the limit,
            or its oversized picture is not a PNG.
    """

    # Stage 1 — WHY refuse a missing id (as excluded_sample_ids does): the list was written
    # against one revision's data; an id that matches nothing describes nothing we can check.
    present: set[str] = {str(sample.id) for sample in samples}
    missing: list[str] = sorted(set(sample_ids) - present)
    if missing:
        raise PrepareError(
            f"shrunk_picture_sample_ids {', '.join(missing)} are not in the dataset — the named "
            "deviation no longer matches the pinned Samples"
        )
    # Stages 2 and 3, per listed Sample.
    return [
        _sample_with_shrunk_pictures(sample) if str(sample.id) in sample_ids else sample
        for sample in samples
    ]


def _sample_with_shrunk_pictures(sample: Sample) -> Sample:
    """Stage 2 and 3 — copy one listed Sample with its oversized pictures shrunk, refusing a
    Sample that has none."""

    shrunk: int = 0
    messages: list[Any] = []
    for message in sample.input if not isinstance(sample.input, str) else ():
        if isinstance(message.content, str):
            messages.append(message)
            continue
        parts: list[Any] = []
        for part in message.content:
            image: str | None = getattr(part, "image", None) if part.type == "image" else None
            if image is not None:
                smaller: str = _shrunk_picture(image, str(sample.id))
                if smaller != image:
                    shrunk += 1
                    part = part.model_copy(update={"image": smaller})
            parts.append(part)
        messages.append(message.model_copy(update={"content": parts}))
    # Stage 3 — INVARIANT: a deviation that changes nothing is stale, never a silent no-op.
    if shrunk == 0:
        raise PrepareError(
            f"shrunk_picture_sample_ids {sample.id}: the Sample has no picture over "
            f"{MAX_PICTURE_SIDE_PX} px — the named deviation no longer matches the pinned Samples"
        )
    return sample.model_copy(update={"input": messages})


def _shrunk_picture(image: str, sample_id: str) -> str:
    """One picture's data URI, shrunk when its long side is over the limit, else as given.

    WHY only data URIs: inspect_evals' hle hands its pictures over inline; a picture given as a
    file path or URL is left alone, and if it was the oversized one, Stage 3 refuses.
    """

    header, _, payload = image.partition(",")
    if not header.startswith(_DATA_URI_PREFIX) or not header.endswith(_BASE64_MARKER):
        return image
    # WHY lazy: Pillow is the `benchmarks` extra, installed only where Cases are prepared.
    from PIL import Image

    with Image.open(io.BytesIO(base64.b64decode(payload))) as original:
        size: tuple[int, int] = shrunk_size(*original.size)
        if size == original.size:
            return image
        if original.format != _SHRINKABLE_FORMAT:
            raise PrepareError(
                f"shrunk_picture_sample_ids {sample_id}: the oversized picture is "
                f"{original.format}, and only a {_SHRINKABLE_FORMAT} is shrunk (a lossless "
                "re-encode); declare a quality before shrinking another format"
            )
        smaller: Image.Image = original.resize(size, Image.Resampling.LANCZOS)
    buffer: io.BytesIO = io.BytesIO()
    smaller.save(buffer, format=_SHRINKABLE_FORMAT)
    return f"{header},{base64.b64encode(buffer.getvalue()).decode('ascii')}"
