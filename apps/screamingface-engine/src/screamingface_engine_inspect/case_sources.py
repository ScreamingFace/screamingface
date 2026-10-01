# pyright: reportMissingImports=false
# WHY file-level: the primitives live in the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Case Sources: where an eval's Cases really come from, recorded as it fetches them (OME-1273).

FEATURE: Task-replay Imported Benchmarks — the importer calls the eval's own task function,
and this module watches every fetch primitive it can reach, so the generated declaration can
list each Case Source for review (spec R3).

Think of it as a customs officer at every door of the clean room: each top-level fetch is
logged once, with what it fetched and what pins it. Stages, in execution order:

    Stage 1 — install: wrap each primitive and rebind, in every loaded module, every
              attribute that IS the original. Evals import helpers by name: mgsm does
              `from inspect_ai.util import download`, so patching inspect_ai.util alone
              would miss it.
    Stage 2 — on a call: only a top-level call records (depth 1). A primitive called by
              another primitive is the same fetch: agieval's _download_remote reads the
              bytes through inspect_ai's file(), snapshot_download calls hf_hub_download.
    Stage 3 — describe: the call's arguments, bound to the primitive's own signature, become
              Case Sources, or none when the call is not a fetch (a read from the replay's
              own cache, a relative path inside a snapshot already recorded).
    Stage 4 — uninstall: put every rebound attribute back. The import child dies with its
              patches; the tests that install into the pytest process need this.

Example: mgsm's `download(url, "4c2f…", cache/mgsm_en.tsv)` records
``url https://…/mgsm_en.tsv · pin sha256 4c2f…``; its following read of cache/mgsm_en.tsv
through file() records nothing.

AIDEV-NOTE: the depth counter is shared across threads, so two top-level fetches running at
once on two threads record only the first (a declared limitation of PR 3). A per-thread
counter would instead record every file snapshot_download's worker threads fetch.
"""

from __future__ import annotations

import functools
import inspect
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any

_COMMIT_IN_URL: re.Pattern[str] = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")
_URL_SCHEMES: tuple[str, ...] = ("http://", "https://", "s3://", "gs://", "hf://")

#: Kinds a Case Source can be. The comment the importer writes starts with the kind.
HUGGING_FACE: str = "hugging-face"
URL: str = "url"
FILE: str = "file"
#: The pin of a Case Source nothing upstream pins: the Case Digest is then the only pin.
UNPINNED: str = "unpinned"

#: What a describe step returns: the Case Sources one call fetched (often one, maybe none).
Described = list["CaseSource"]


@dataclass(frozen=True)
class CaseSource:
    """One place Cases were fetched from, and what pins its content."""

    kind: str
    location: str
    pin: str

    def as_comment(self) -> str:
        """The review line the importer writes above the declaration (spec R6)."""

        line: str = f"{self.kind} {self.location} · pin {self.pin}"
        if self.pin == UNPINNED:
            line += " (no upstream hash: the Case Digest is the only pin)"
        return line


def pin_from_url(url: str) -> str:
    """A commit sha in the URL path is a pin; anything else is unpinned."""

    match: re.Match[str] | None = _COMMIT_IN_URL.search(url)
    return f"commit {match.group(0)}" if match else UNPINNED


def _is_url(value: Any) -> bool:
    """Whether a path-like argument names something on the network."""

    return isinstance(value, str) and value.startswith(_URL_SCHEMES)


def _revision_pin(revision: Any) -> str:
    """A Hugging Face revision pins the content; none means the Hub's moving HEAD."""

    return f"revision {revision}" if revision else UNPINNED


def _describe_load_dataset(call: Mapping[str, Any]) -> Described:
    """datasets.load_dataset(path, name=None, ..., revision=None)."""

    name: Any = call.get("name")
    location: str = f"{call['path']}/{name}" if name else str(call["path"])
    return [CaseSource(HUGGING_FACE, location, _revision_pin(call.get("revision")))]


def _describe_snapshot_download(call: Mapping[str, Any]) -> Described:
    """huggingface_hub.snapshot_download(repo_id, ..., revision=None)."""

    return [CaseSource(HUGGING_FACE, str(call["repo_id"]), _revision_pin(call.get("revision")))]


def _describe_hf_hub_download(call: Mapping[str, Any]) -> Described:
    """huggingface_hub.hf_hub_download(repo_id, filename, ..., revision=None)."""

    location: str = f"{call['repo_id']}/{call['filename']}"
    return [CaseSource(HUGGING_FACE, location, _revision_pin(call.get("revision")))]


def _describe_inspect_download(call: Mapping[str, Any]) -> Described:
    """inspect_ai.util.download(url, sha256, dest): the hash is the pin."""

    url: str = str(call["url"])
    sha256: Any = call.get("sha256")
    return [CaseSource(URL, url, f"sha256 {sha256}" if sha256 else pin_from_url(url))]


def _describe_download_remote(call: Mapping[str, Any]) -> Described:
    """inspect_evals' _download_remote(remote_url, local_cache_path): no hash, maybe a commit."""

    url: str = str(call["remote_url"])
    return [CaseSource(URL, url, pin_from_url(url))]


def _describe_download_manager(call: Mapping[str, Any]) -> Described:
    """datasets DownloadManager.download(self, url_or_urls): every URL in a str, list or dict."""

    flat: list[Any] = []
    stack: list[Any] = [call["url_or_urls"]]
    while stack:
        item: Any = stack.pop(0)
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
        else:
            flat.append(item)
    # WHY skip non-URLs: medqa's builder "downloads" data_clean.zip, a relative path inside
    # the snapshot already recorded by snapshot_download.
    return [CaseSource(URL, str(url), pin_from_url(str(url))) for url in flat if _is_url(url)]


@dataclass(frozen=True)
class Primitive:
    """One fetch primitive the recorder wraps: where it lives and how to describe a call."""

    module: str
    attribute: str
    describe: Callable[[Mapping[str, Any]], Described]


#: The module-level fetch primitives of spec R3. inspect_ai's file() is the sixth; it needs
#: the recorder's cache root, so the recorder adds it (and D7's DownloadManager method).
PRIMITIVES: tuple[Primitive, ...] = (
    Primitive("datasets", "load_dataset", _describe_load_dataset),
    Primitive("huggingface_hub", "snapshot_download", _describe_snapshot_download),
    Primitive("huggingface_hub", "hf_hub_download", _describe_hf_hub_download),
    Primitive("inspect_ai.util", "download", _describe_inspect_download),
    Primitive("inspect_evals.utils.load_dataset", "_download_remote", _describe_download_remote),
)


class CaseSourceRecorder:
    """The customs officer: installs the wraps and keeps the list of Case Sources."""

    def __init__(self, cache_root: Path) -> None:
        self.sources: list[CaseSource] = []
        self._cache_root: Path = cache_root.resolve()
        self._depth: int = 0
        self._package_root: Path | None = None
        self._rebound: list[tuple[Any, str, Any, Any]] = []

    def install(self) -> None:
        """Stage 1 — wrap every primitive and rebind it wherever it is already bound."""

        import inspect_evals
        from datasets.download.download_manager import DownloadManager

        self._package_root = Path(inspect_evals.__file__).resolve().parent
        primitives: tuple[Primitive, ...] = (
            *PRIMITIVES,
            Primitive("inspect_ai._util.file", "file", self._describe_file),
        )
        for primitive in primitives:
            original: Any = getattr(import_module(primitive.module), primitive.attribute)
            self._rebind_everywhere(original, self._wrap(original, primitive.describe))
        # D7: the DownloadManager primitive is a method, so the class holds the binding.
        method: Any = DownloadManager.download
        self._rebind(
            DownloadManager, "download", method, self._wrap(method, _describe_download_manager)
        )

    def uninstall(self) -> None:
        """Stage 4 — put back every attribute that still holds this recorder's wrapper."""

        for owner, name, original, wrapped in reversed(self._rebound):
            if vars(owner).get(name) is wrapped:
                setattr(owner, name, original)
        self._rebound.clear()

    def _describe_file(self, call: Mapping[str, Any]) -> Described:
        """inspect_ai._util.file.file(file, mode): a URL, a package file, or a cache read."""

        text: str = str(call["file"])
        if _is_url(text):
            return [CaseSource(URL, text, pin_from_url(text))]
        resolved: Path = Path(text).resolve()
        if resolved.is_relative_to(self._cache_root):
            return []  # Stage 3: the eval reading its own download back
        return [self._local_file_source(resolved)]

    def _local_file_source(self, resolved: Path) -> CaseSource:
        """A file the eval ships is pinned by the package version; any other is unpinned."""

        if self._package_root is not None and resolved.is_relative_to(self._package_root):
            relative: str = resolved.relative_to(self._package_root).as_posix()
            pin: str = f"inspect_evals=={version('inspect_evals')}"
            return CaseSource(FILE, f"inspect_evals/{relative}", pin)
        return CaseSource(FILE, str(resolved), UNPINNED)

    def _wrap(self, original: Any, describe: Callable[[Mapping[str, Any]], Described]) -> Any:
        """Stage 2 — a pass-through that records a top-level call before running the original."""

        signature: inspect.Signature = inspect.signature(original)

        @functools.wraps(original)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            """The primitive, with its top-level calls recorded first."""

            self._depth += 1
            try:
                if self._depth == 1:
                    # WHY bind: evals pass the same argument by position or by name.
                    bound: inspect.BoundArguments = signature.bind_partial(*args, **kwargs)
                    self._record(describe(bound.arguments))
                return original(*args, **kwargs)
            finally:
                self._depth -= 1

        return wrapped

    def _record(self, described: Described) -> None:
        """Keep each Case Source once, in first-seen order."""

        for source in described:
            if source not in self.sources:
                self.sources.append(source)

    def _rebind_everywhere(self, original: Any, wrapped: Any) -> None:
        """Replace every loaded-module attribute that IS `original` (spec R3's identity rule)."""

        for module in list(sys.modules.values()):
            if module is None:
                continue
            for name, value in list(vars(module).items()):
                if value is original:
                    self._rebind(module, name, original, wrapped)

    def _rebind(self, owner: Any, name: str, original: Any, wrapped: Any) -> None:
        """Point one attribute at the wrapper and remember how to undo it."""

        setattr(owner, name, wrapped)
        self._rebound.append((owner, name, original, wrapped))


__all__ = [
    "FILE",
    "HUGGING_FACE",
    "PRIMITIVES",
    "UNPINNED",
    "URL",
    "CaseSource",
    "CaseSourceRecorder",
    "Primitive",
    "pin_from_url",
]
