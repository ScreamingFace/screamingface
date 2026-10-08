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

With fetch pins (OME-1460, :mod:`screamingface_engine_inspect.fetch_pins`) the officer also
stamps visas: in stage 2 a top-level Hub fetch gets the declaration's revision before the
original runs, and inspect's ``hf_dataset`` is wrapped too (by identity, so a name bound at
import and the inspect_evals shim both reach it) to force the revision and the shuffle
seeds. That wrap records nothing and does not count depth: the Case Source stays the
``datasets.load_dataset`` call ``hf_dataset`` makes, as before.

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
from dataclasses import dataclass, field
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.bundle_provenance import (
    FILE,
    HUGGING_FACE,
    LOAD_PHASE,
    UNPINNED,
    URL,
    hugging_face_url,
)
from screamingface_engine_inspect.fetch_pins import (
    FetchPins,
    forced_hf_dataset_arguments,
    forced_revision,
)

_COMMIT_IN_URL: re.Pattern[str] = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")
_URL_SCHEMES: tuple[str, ...] = ("http://", "https://", "s3://", "gs://", "hf://")

# The Case Source kind words (hugging-face, url, file), "unpinned" and the load phase live in
# core, so the hand-built preparers' labels and this recorder's read alike; the comment the
# importer writes starts with the kind.
#: When capture rendered a Sample, as opposed to while the task function loaded its dataset
#: (see CaseSource.phase).
RENDER_PHASE: str = "render"

#: What a describe step returns: the Case Sources one call fetched (often one, maybe none).
Described = list["CaseSource"]


@dataclass(frozen=True)
class CaseSource:
    """One place Cases were fetched from, and what pins its content.

    ``phase`` says WHEN the fetch happened: while the task function loaded its dataset
    (``load``, the usual case) or while capture ran the Task's solvers on a Sample
    (``render``: a solver that reads a few-shot file or a template at solve time). The
    reviewer reads the two differently: a load fetch is where the Cases come from, a render
    fetch is something the prompt depends on.

    ``url`` is a browser link to the source AT its pin (OME-1524), or None. It is built when
    the fetch is recorded because the location alone cannot say what it names:
    ``TsinghuaC3I/MedXpertQA/Text`` is a config, ``dgslibisey/MuSiQue/<file>`` a file.
    WHY outside equality: the call that fixed kind, location and pin also fixed the link, so
    it adds no identity; two records of one fetch stay one Case Source.
    """

    kind: str
    location: str
    pin: str
    phase: str = LOAD_PHASE
    url: str | None = field(default=None, compare=False)

    def as_comment(self) -> str:
        """The one-line review note the importer prints for this Case Source (spec R6)."""

        return " · ".join(self.comment_lines())

    def comment_lines(self) -> tuple[str, str]:
        """The same note as two lines, as the generated declaration's comment carries it.

        WHY two lines: a URL plus a 40-hex pin overflows the 100-column lint gate; a line
        that ENDS with its URL is exempt, so the pin goes on a line of its own.
        """

        pin: str = f"pin {self.pin}"
        if self.pin == UNPINNED:
            pin += " (no upstream hash: the Case Digest is the only pin)"
        what: str = f"{self.kind} {self.location}"
        if self.phase == RENDER_PHASE:
            what += " (fetched while rendering a Case, not while loading the dataset)"
        return what, pin

    def hub_repo_id(self) -> str:
        """The Hugging Face repository a hugging-face location names: `owner/name`.

        Example: ``bigbio/med_qa/main`` (a load_dataset config) → ``bigbio/med_qa``.
        """

        owner, _, rest = self.location.partition("/")
        return f"{owner}/{rest.partition('/')[0]}"

    def web_url(self) -> str | None:
        """Where a reader can see this Case Source in a browser, if anywhere."""

        if self.kind == HUGGING_FACE:
            return f"https://huggingface.co/datasets/{self.hub_repo_id()}"
        if self.kind == URL and self.location.startswith(("http://", "https://")):
            return self.location
        return None


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


def _hub_link(call: Mapping[str, Any], repo_id: str, *, file: str | None = None) -> str | None:
    """The browser link for a Hub fetch at its revision; only a dataset repo has one here.

    WHY datasets only: a model or Space page lives at another address, and a wrong link is
    worse than none. ``load_dataset`` passes no ``repo_type``; callers say "dataset" for it.
    """

    revision: Any = call.get("revision")
    if call.get("repo_type") != "dataset" or not isinstance(revision, str):
        return None
    return hugging_face_url(repo_id, revision, file=file)


def _web_link(url: str) -> str | None:
    """An http(s) address is its own link; s3:// or gs:// opens nothing in a browser."""

    return url if url.startswith(("http://", "https://")) else None


def _describe_load_dataset(call: Mapping[str, Any]) -> Described:
    """datasets.load_dataset(path, name=None, ..., revision=None)."""

    name: Any = call.get("name")
    location: str = f"{call['path']}/{name}" if name else str(call["path"])
    # The config is not a path on the Hub, so the link is the repo (``path``) at the commit.
    url: str | None = _hub_link({**call, "repo_type": "dataset"}, str(call["path"]))
    return [CaseSource(HUGGING_FACE, location, _revision_pin(call.get("revision")), url=url)]


def _describe_snapshot_download(call: Mapping[str, Any]) -> Described:
    """huggingface_hub.snapshot_download(repo_id, ..., revision=None)."""

    repo_id: str = str(call["repo_id"])
    url: str | None = _hub_link(call, repo_id)
    return [CaseSource(HUGGING_FACE, repo_id, _revision_pin(call.get("revision")), url=url)]


def _describe_hf_hub_download(call: Mapping[str, Any]) -> Described:
    """huggingface_hub.hf_hub_download(repo_id, filename, ..., revision=None)."""

    location: str = f"{call['repo_id']}/{call['filename']}"
    # WHY join the subfolder: hf_hub_download fetches ``subfolder/filename``.
    subfolder: Any = call.get("subfolder")
    file: str = f"{subfolder}/{call['filename']}" if subfolder else str(call["filename"])
    url: str | None = _hub_link(call, str(call["repo_id"]), file=file)
    return [CaseSource(HUGGING_FACE, location, _revision_pin(call.get("revision")), url=url)]


def _describe_inspect_download(call: Mapping[str, Any]) -> Described:
    """inspect_ai.util.download(url, sha256, dest): the hash is the pin."""

    url: str = str(call["url"])
    sha256: Any = call.get("sha256")
    pin: str = f"sha256 {sha256}" if sha256 else pin_from_url(url)
    return [CaseSource(URL, url, pin, url=_web_link(url))]


def _describe_download_remote(call: Mapping[str, Any]) -> Described:
    """inspect_evals' _download_remote(remote_url, local_cache_path): no hash, maybe a commit."""

    url: str = str(call["remote_url"])
    return [CaseSource(URL, url, pin_from_url(url), url=_web_link(url))]


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
    return [
        CaseSource(URL, str(url), pin_from_url(str(url)), url=_web_link(str(url)))
        for url in flat
        if _is_url(url)
    ]


@dataclass(frozen=True)
class Primitive:
    """One fetch primitive the recorder wraps: where it lives and how to describe a call.

    ``hub_repo_argument`` names the argument holding the Hugging Face repo id on a Hub
    fetch (its ``revision`` argument is then forced by the fetch pins); None elsewhere.
    """

    module: str
    attribute: str
    describe: Callable[[Mapping[str, Any]], Described]
    hub_repo_argument: str | None = None


#: The module-level fetch primitives of spec R3. inspect_ai's file() is the sixth; it needs
#: the recorder's cache root, so the recorder adds it (and D7's DownloadManager method).
PRIMITIVES: tuple[Primitive, ...] = (
    Primitive("datasets", "load_dataset", _describe_load_dataset, "path"),
    Primitive("huggingface_hub", "snapshot_download", _describe_snapshot_download, "repo_id"),
    Primitive("huggingface_hub", "hf_hub_download", _describe_hf_hub_download, "repo_id"),
    Primitive("inspect_ai.util", "download", _describe_inspect_download),
    Primitive("inspect_evals.utils.load_dataset", "_download_remote", _describe_download_remote),
)


class CaseSourceRecorder:
    """The customs officer: installs the wraps and keeps the list of Case Sources."""

    def __init__(self, cache_root: Path) -> None:
        self.sources: list[CaseSource] = []
        #: Every top-level Hub fetch as (repo id, revision it read), in call order: the
        #: importer resolves these to the declaration's source pins (OME-1460).
        self.hub_fetches: list[tuple[str, str | None]] = []
        #: Which declared seeds a call actually needed ("shuffle_seed", "choice_shuffle_seed"):
        #: the importer refuses a seed nothing applied (OME-1460, R10).
        self.seeds_applied: set[str] = set()
        self._pins: FetchPins | None = None
        self._cache_root: Path = cache_root.resolve()
        self._depth: int = 0
        self._package_root: Path | None = None
        self._rebound: list[tuple[Any, str, Any, Any]] = []

    def install(self, pins: FetchPins | None = None) -> None:
        """Stage 1 — wrap every primitive and rebind it wherever it is already bound.

        Args:
            pins: the fetch pins to force (OME-1460); None watches without changing a call.
        """

        import inspect_ai.dataset
        import inspect_evals
        from datasets.download.download_manager import DownloadManager

        self._pins = pins

        # WHY the guard: a module's __file__ is typed str | None (a namespace package has none).
        package_file: str | None = inspect_evals.__file__
        self._package_root = Path(package_file).resolve().parent if package_file else None
        primitives: tuple[Primitive, ...] = (
            *PRIMITIVES,
            Primitive("inspect_ai._util.file", "file", self._describe_file),
        )
        for primitive in primitives:
            original: Any = getattr(import_module(primitive.module), primitive.attribute)
            self._rebind_everywhere(original, self._wrap(original, primitive))
        if pins is not None:
            # WHY only the real hf_dataset: the inspect_evals shim calls it through the
            # inspect_ai.dataset module attribute, which this rebinds too.
            real_hf_dataset: Any = inspect_ai.dataset.hf_dataset
            self._rebind_everywhere(real_hf_dataset, self._enforce_hf_dataset(real_hf_dataset))
        # D7: the DownloadManager primitive is a method, so the class holds the binding.
        method: Any = DownloadManager.download
        self._rebind(
            DownloadManager,
            "download",
            method,
            self._wrap(method, Primitive("datasets", "download", _describe_download_manager)),
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
            return [CaseSource(URL, text, pin_from_url(text), url=_web_link(text))]
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

    def _wrap(self, original: Any, primitive: Primitive) -> Any:
        """Stage 2 — a pass-through that records a top-level call before running the original,
        forcing a Hub fetch's revision first when fetch pins are installed."""

        signature: inspect.Signature = inspect.signature(original)

        @functools.wraps(original)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            """The primitive, with its top-level calls pinned and recorded first."""

            self._depth += 1
            try:
                if self._depth == 1:
                    # WHY bind: evals pass the same argument by position or by name.
                    bound: inspect.BoundArguments = signature.bind_partial(*args, **kwargs)
                    repo_argument: str | None = primitive.hub_repo_argument
                    if repo_argument is not None and repo_argument in bound.arguments:
                        self._pin_hub_fetch(bound, str(bound.arguments[repo_argument]))
                        args, kwargs = bound.args, bound.kwargs
                    self._record(primitive.describe(bound.arguments))
                # INVARIANT: a nested call is the same fetch as its parent; the parent's
                # revision already reached it, so it is neither pinned again nor recorded.
                return original(*args, **kwargs)
            finally:
                self._depth -= 1

        return wrapped

    def _pin_hub_fetch(self, bound: inspect.BoundArguments, repo_id: str) -> None:
        """Force the declaration's revision onto one top-level Hub fetch and remember it."""

        if self._pins is not None:
            revision: Any = forced_revision(self._pins, repo_id, bound.arguments.get("revision"))
            if revision is not None:
                bound.arguments["revision"] = revision
        fetched: Any = bound.arguments.get("revision")
        self.hub_fetches.append((repo_id, None if fetched is None else str(fetched)))

    def _enforce_hf_dataset(self, original: Any) -> Any:
        """inspect's hf_dataset with the revision and seeds forced; records nothing itself."""

        signature: inspect.Signature = inspect.signature(original)

        @functools.wraps(original)
        def enforced(*args: Any, **kwargs: Any) -> Any:
            """hf_dataset, called with the declaration's revision and seeds."""

            bound: inspect.BoundArguments = signature.bind_partial(*args, **kwargs)
            # WHY assert: install() wraps hf_dataset only when pins are given.
            assert self._pins is not None
            forced: dict[str, Any] = forced_hf_dataset_arguments(self._pins, bound.arguments)
            if forced.get("seed") != bound.arguments.get("seed"):
                self.seeds_applied.add("shuffle_seed")
            if forced.get("shuffle_choices") is not bound.arguments.get("shuffle_choices"):
                self.seeds_applied.add("choice_shuffle_seed")
            bound.arguments.update(forced)
            return original(*bound.args, **bound.kwargs)

        return enforced

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
