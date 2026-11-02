"""The pictures and files of a Case, and opening one from the engine (OME-1271, PR 5).

FEATURE (OME-1271): a Case Result shows each picture or file as a placeholder (type, size,
sha256), never its bytes, so a report of 181 figures stays small. Think of a cloakroom: the run
hung each picture on a peg numbered by its sha256 (the engine's result store), and the
placeholder is the ticket. ``case.media`` lists the tickets without any network call;
``fetch_media`` hands one in and checks that what comes back is exactly what the ticket names.

INVARIANT: a fetched picture is shown only when its size and sha256 match its placeholder, so a
picture opened from a result is the one the model saw, or nothing.

AIDEV-NOTE: a local engine drops parked pictures after its ``artifact_ttl_s`` (48 hours by
default), restarted each time a run parks the same bytes again. A deployment's S3 store leaves
expiry to a bucket lifecycle rule, and none is configured today, so a deployment keeps them. A
fetch after a picture is gone fails by name (``media_not_kept``), never with another picture.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from screamingface.case_result import (
    _CANDIDATE_INPUT_V2_SCHEMA,
    _part_placeholder,
    _Placeholder,
    _placeholder_line,
)

#: Picture types a notebook shows inline. WHY not WebP: no Jupyter front end is known to render
#: it from a display bundle; a WebP picture still fetches and saves.
_INLINE_TYPES: frozenset[str] = frozenset({"image/png", "image/jpeg", "image/gif"})
_EXTENSIONS: Mapping[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
_NAME_DIGEST_CHARS = 12


@dataclass(frozen=True)
class CaseMedia:
    """One picture or file of a Case, as its Case Result names it: what proves the bytes, not them.

    e.g. ``CaseMedia(kind="image", media_type="image/png", size=307200, sha256="9f86…")``.
    """

    kind: Literal["image", "file"]
    media_type: str
    size: int
    sha256: str
    filename: str | None = None

    def __str__(self) -> str:
        """The placeholder line every view shows, e.g. ``image/png · 300 KB · sha256 9f86d081…``."""

        return _placeholder_line(self._placeholder())

    @property
    def default_name(self) -> str:
        """The file name ``save`` uses in a folder: the part's own name, else one from its sha256.

        e.g. ``methods.pdf``, or ``9f86d081884c.png`` for an unnamed picture.
        """

        if self.filename:
            return Path(self.filename).name
        return self.sha256[:_NAME_DIGEST_CHARS] + _EXTENSIONS.get(self.media_type, "")

    def _placeholder(self) -> _Placeholder:
        """This item in the placeholder shape the views format."""

        placeholder: _Placeholder = {
            "placeholder": self.kind,
            "media_type": self.media_type,
            "size": self.size,
            "sha256": self.sha256,
        }
        if self.filename:
            placeholder["filename"] = self.filename
        return placeholder


@dataclass(frozen=True)
class FetchedMedia:
    """A picture or file fetched from the engine, already checked against its placeholder."""

    media: CaseMedia
    data: bytes = field(repr=False)

    def _repr_mimebundle_(
        self, include: object = None, exclude: object = None
    ) -> dict[str, object]:
        """Show a picture inline in Jupyter; anything else shows its placeholder line."""

        del include, exclude
        bundle: dict[str, object] = {"text/plain": str(self.media)}
        if self.media.kind == "image" and self.media.media_type in _INLINE_TYPES:
            bundle[self.media.media_type] = self.data
        return bundle

    def save(self, path: str | os.PathLike[str]) -> Path:
        """Write the bytes to ``path``, or into it under ``default_name`` when it is a folder.

        Returns the absolute path written.
        """

        target: Path = Path(path)
        if target.is_dir():
            target = target / self.media.default_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.data)
        return target.resolve()


def case_media(case_input: str) -> tuple[CaseMedia, ...]:
    """Each picture and file of a Case input, in the Case's order; empty for a text Case.

    Reads the placeholder the engine echoed (or measures a ``data:`` URI, for a result from an
    engine older than OME-1271 PR 3). A part this SDK can't read is left out, never guessed.
    """

    try:
        decoded: object = json.loads(case_input)
    except (TypeError, ValueError, RecursionError):
        return ()
    if not isinstance(decoded, Mapping) or decoded.get("schema") != _CANDIDATE_INPUT_V2_SCHEMA:
        return ()
    messages: object = decoded.get("messages")
    found: list[CaseMedia] = []
    for message in messages if isinstance(messages, list) else ():
        content: object = message.get("content") if isinstance(message, Mapping) else None
        for part in content if isinstance(content, list) else ():
            placeholder: _Placeholder | None = (
                _part_placeholder(part) if isinstance(part, Mapping) else None
            )
            if placeholder is not None:
                found.append(
                    CaseMedia(
                        kind=placeholder["placeholder"],
                        media_type=placeholder["media_type"],
                        size=placeholder["size"],
                        sha256=placeholder["sha256"],
                        filename=placeholder.get("filename"),
                    )
                )
    return tuple(found)


__all__ = ["CaseMedia", "FetchedMedia", "case_media"]
