# pyright: reportMissingImports=false
# WHY file-level: platformdirs comes with the `inspect` extra (inspect_evals depends on it),
# absent in the default (extra-less) install the typecheck gate runs against.
"""Fetch one LABBench2 question's picture from the authors' public bucket, into the replay cache.

Think of it as collecting the exhibit for one exam question: the question row names a folder
in the authors' public Google Cloud Storage bucket (``/figs/imgs/<id>/``), the bucket's listing
says which files are in it and what their bytes should hash to, and each file is downloaded
into this import's own cache, checked, then handed to the Sample as a path.

Stages, in execution order (:func:`fetch_question_files`):

    Stage 1 — list: ask the bucket's JSON API for every object under the prefix, page by
              page. Each object comes with its name, size and base64 md5.
    Stage 2 — place: each object's name minus the prefix is its path under
              ``<cache>/lab_bench_2/labbench2-data-public/<prefix>/``, the authors' own cache
              layout under a different root. A name that would leave that folder is refused.
    Stage 3 — download: a file already there with the listed md5 is kept; anything else is
              fetched into a ``.part`` sibling, checked against the listed md5, and renamed
              into place only when it matches. A passing fault (a dropped or cut-short
              connection, HTTP 429 or 5xx) is retried, twice.

WHY the replay cache, not the authors' ``~/.cache/labbench2``: the importer seals a picture
from a file only when the file sits inside the import's own cache (``picture_input.py``), the
directory the replay points ``INSPECT_EVALS_CACHE_DIR`` into. MMMU and MathVista write there
for the same reason.

WHY our own HTTP and not ``inspect_ai.util.download``: that primitive pins each file by a
sha256 written in the source, which would mean 201 hashes vendored here. The bucket's own md5
catches a corrupted transfer, and the Case Digest pins the bytes every build must reproduce:
a figure the authors replace fails the next build by name. GDPval's local Task fetches its
reference files the same way (``local_tasks/gdpval/references.py``).

Example: prefix ``/figs/imgs/b60fdf79-25b2-4bf2-a5bb-cb553d83770f/`` lists one object,
``figs/imgs/b60fdf79-…/figure.png`` (1,097,438 bytes) → written to
``$INSPECT_EVALS_CACHE_DIR/lab_bench_2/labbench2-data-public/figs/imgs/b60fdf79-…/figure.png``.

INVARIANT: a path this module returns is complete and matches the bucket's md5; every failure
raises :class:`FigureFetchError` naming the prefix, never a raw ``urllib`` or JSON error.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

#: The authors' public bucket, as their harness names it (``evals/utils.py`` ``GCS_BUCKET``).
BUCKET: Final[str] = "labbench2-data-public"
#: The bucket's JSON listing endpoint and its plain download address.
_LIST_URL: Final[str] = "https://storage.googleapis.com/storage/v1/b/{bucket}/o"
_DOWNLOAD_URL: Final[str] = "https://storage.googleapis.com/{bucket}/{path}"
#: This Task's folder under the inspect_evals cache, beside the evals' own folders.
CACHE_FOLDER: Final[str] = "lab_bench_2"

#: The authors' harness waits 60 s for a file (``httpx.stream(..., timeout=60)``).
_TIMEOUT_S: Final[float] = 60.0
#: One fetch plus two retries; a bucket that fails three times in a row is down, not flaky.
_ATTEMPTS: Final[int] = 3
#: The wait before retry k is ``k`` times this (2 s, then 4 s).
_BACKOFF_S: Final[float] = 2.0
#: The one 4xx status that means "later", not "never".
_TOO_MANY_REQUESTS: Final[int] = 429

#: How a URL is opened. A seam, so the tests point it at a local server.
Opener = Callable[[str, float], Any]


class FigureFetchError(RuntimeError):
    """A question's picture could not be listed, placed, downloaded or verified."""


@dataclass(frozen=True, slots=True)
class _Blob:
    """One object the bucket listed: its full name, and its bytes' base64 md5."""

    name: str
    md5: str


def default_cache_root() -> Path:
    """The inspect_evals cache directory, read now: the replay sets it before the Task runs.

    Same rule as ``inspect_evals.constants`` (``INSPECT_EVALS_CACHE_DIR`` when set, else the
    platform cache), read at call time rather than at import, so a Task module imported before
    the replay set the variable still writes inside the replay's cache.
    """

    configured: str | None = os.environ.get("INSPECT_EVALS_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    from platformdirs import user_cache_dir

    return Path(user_cache_dir("inspect_evals"))


def fetch_question_files(
    prefix: str,
    cache_root: Path | None = None,
    *,
    opener: Opener | None = None,
) -> list[Path]:
    """Download every file under one question's bucket prefix and return their paths, sorted.

    Args:
        prefix: the row's ``files`` value, e.g. ``"/figs/imgs/<id>/"``.
        cache_root: the inspect_evals cache; defaults to :func:`default_cache_root`.
        opener: how a URL is opened (tests only); defaults to ``urllib.request.urlopen``.

    Returns:
        The local files, sorted by path, as the authors' loader sorts them.

    Raises:
        FigureFetchError: the prefix lists nothing, a name leaves the prefix's folder, or a
            file cannot be downloaded with the listed md5.
    """

    open_url: Opener = opener if opener is not None else _urlopen
    folder: str = prefix.strip("/")
    if not folder:
        raise FigureFetchError("the question names no files prefix")
    root: Path = (cache_root if cache_root is not None else default_cache_root()) / CACHE_FOLDER
    destination_dir: Path = root / BUCKET / folder
    # Stage 1 — list.
    blobs: list[_Blob] = list(_listing(folder + "/", open_url))
    if not blobs:
        raise FigureFetchError(f"files prefix {prefix!r}: the bucket lists no file under it")
    paths: list[Path] = []
    for blob in blobs:
        # Stage 2 — place, refusing a name that would leave the prefix's folder.
        destination: Path = _place(blob.name, folder, destination_dir, prefix)
        # Stage 3 — download, unless a verified copy is already there.
        if not (destination.is_file() and _md5(destination.read_bytes()) == blob.md5):
            _download(blob, destination, prefix, open_url)
        paths.append(destination)
    return sorted(paths)


def _listing(prefix: str, open_url: Opener) -> Iterator[_Blob]:
    """Every object under ``prefix``, page by page; folder markers (names ending ``/``) skipped."""

    page_token: str | None = None
    while True:
        query: dict[str, str] = {"prefix": prefix}
        if page_token:
            query["pageToken"] = page_token
        url: str = _LIST_URL.format(bucket=BUCKET) + "?" + urllib.parse.urlencode(query)
        page: object = _json(_read(url, open_url, f"files prefix {prefix!r}: listing"), prefix)
        if not isinstance(page, dict):
            raise FigureFetchError(f"files prefix {prefix!r}: the listing is not a JSON object")
        for item in page.get("items", []):
            name: object = item.get("name") if isinstance(item, dict) else None
            md5: object = item.get("md5Hash") if isinstance(item, dict) else None
            if not isinstance(name, str) or not isinstance(md5, str) or not md5:
                raise FigureFetchError(
                    f"files prefix {prefix!r}: a listed object has no name or md5"
                )
            if not name.endswith("/"):
                yield _Blob(name=name, md5=md5)
        token: object = page.get("nextPageToken")
        if not isinstance(token, str) or not token:
            return
        page_token = token


def _place(name: str, folder: str, destination_dir: Path, prefix: str) -> Path:
    """Where one object lands: its name minus the prefix, under the question's folder.

    INVARIANT: the result is inside ``destination_dir``. The listing is the bucket's word, not
    ours, so a name like ``figs/imgs/x/../../../etc/passwd`` is refused rather than written.
    """

    relative: str = name[len(folder) + 1 :] if name.startswith(folder + "/") else ""
    parts: list[str] = relative.split("/")
    if not relative or any(part in ("", ".", "..") for part in parts):
        raise FigureFetchError(
            f"files prefix {prefix!r}: listed object {name!r} is not a file inside the prefix"
        )
    return destination_dir.joinpath(*parts)


def _download(blob: _Blob, destination: Path, prefix: str, open_url: Opener) -> None:
    """Fetch one object into a ``.part`` sibling and rename it into place once its md5 matches.

    WHY a ``.part`` sibling: the destination only ever appears complete, so a fetch killed
    mid-write never leaves a truncated picture that a later build would accept.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    part: Path = destination.with_name(destination.name + ".part")
    url: str = _DOWNLOAD_URL.format(bucket=BUCKET, path=urllib.parse.quote(blob.name))
    try:
        data: bytes = _read(url, open_url, f"files prefix {prefix!r}: {blob.name!r}")
        if _md5(data) != blob.md5:
            raise FigureFetchError(
                f"files prefix {prefix!r}: {blob.name!r} does not match the bucket's md5; "
                "the download was corrupted or the file changed during the fetch"
            )
        part.write_bytes(data)
        os.replace(part, destination)
    finally:
        part.unlink(missing_ok=True)


def _read(url: str, open_url: Opener, what: str) -> bytes:
    """The body at ``url``, retried after a passing fault; any other refusal is not retried.

    Passing: a connection that drops (``OSError``) or ends before the body does
    (``http.client.IncompleteRead``, an ``HTTPException`` and NOT an ``OSError``), and HTTP 429
    or 5xx, the statuses the connector also treats as temporary.
    """

    last: Exception | None = None
    for attempt in range(_ATTEMPTS):
        try:
            with open_url(url, _TIMEOUT_S) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            # WHY no retry on other 4xx: a missing or forbidden object stays so.
            if exc.code != _TOO_MANY_REQUESTS and exc.code < 500:
                raise FigureFetchError(f"{what}: the bucket answered HTTP {exc.code}") from None
            last = exc
        except (OSError, http.client.HTTPException) as exc:
            last = exc
        if attempt + 1 < _ATTEMPTS:
            time.sleep(_BACKOFF_S * (attempt + 1))
    raise FigureFetchError(f"{what}: failed after {_ATTEMPTS} attempts: {last}") from last


def _json(body: bytes, prefix: str) -> object:
    """The listing's JSON, or a named failure."""

    try:
        return json.loads(body)
    except ValueError:
        raise FigureFetchError(f"files prefix {prefix!r}: the listing is not JSON") from None


def _md5(data: bytes) -> str:
    """The base64 md5 of ``data``, the form the bucket's listing gives (``md5Hash``)."""

    return base64.b64encode(hashlib.md5(data, usedforsecurity=False).digest()).decode("ascii")


def _urlopen(url: str, timeout: float) -> Any:
    """Open ``url`` with urllib, as the default :data:`Opener`."""

    return urllib.request.urlopen(url, timeout=timeout)  # noqa: S310 — fixed https URLs above


__all__ = [
    "BUCKET",
    "CACHE_FOLDER",
    "FigureFetchError",
    "Opener",
    "default_cache_root",
    "fetch_question_files",
]
