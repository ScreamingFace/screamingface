"""What the importer can learn about a Benchmark's provenance without a human (OME-1455).

Think of the importer as a clerk filling the cover sheet of an exam it is copying. Two
sources are within reach at import time and nowhere else: inspect's own per-eval
``eval.yaml`` (the paper link, who ported the eval into inspect, the declared size, a human
baseline for 8 of 129 evals, the group) and the paper's arXiv entry (the author list and the
BibTeX). Everything else — who brought the Benchmark here, the best published score, a
content warning — only a human can source, so the generated row carries a ``TODO(review)``
there and registration refuses the literal TODO by name.

Stages, in execution order:

1. ``read_eval_metadata``: resolve the task reference to its inspect_evals package, read
   ``eval.yaml`` from the INSTALLED package at the pinned version (never GitHub), pick the
   task entry by name.
2. ``read_arxiv_entry``: one HTTP call per source, at import time, never at page load; a
   failure returns None and the row says TODO (F8). Tests inject ``fetch``.
3. ``provenance_row_lines``: the generated ``BenchmarkSpec`` lines, every value a JSON
   string literal so arXiv- or Hub-controlled text can never escape the literal (Lane 4).
"""

from __future__ import annotations

import http.client
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import version as _installed_version
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

#: The GitHub tree of the inspect_evals catalogue, pinned to the installed version's tag.
#: INVARIANT (F7): a version tag, never a branch, so the link follows the OME-1421 pin bump
#: and a reader always lands on the code the Engine actually imported from.
_INSPECT_EVALS_TREE = (
    "https://github.com/UKGovernmentBEIS/inspect_evals/tree/v{version}/src/inspect_evals/{package}"
)
_ARXIV_API = "https://export.arxiv.org/api/query?id_list={arxiv_id}"
_ARXIV_BIBTEX = "https://arxiv.org/bibtex/{arxiv_id}"
_ARXIV_ID = re.compile(r"arxiv\.org/(?:abs|pdf)/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?")
_ATOM = "{http://www.w3.org/2005/Atom}"
#: The one notebook every Imported Benchmark runs from (spec §3).
IMPORTED_NOTEBOOK = "12_inspect_evals_benchmarks"
#: Hub licence strings → their SPDX spelling (the cleared list plus the common ones).
_SPDX = {
    "mit": "MIT",
    "apache-2.0": "Apache-2.0",
    "cc0-1.0": "CC0-1.0",
    "cc-by-4.0": "CC-BY-4.0",
    "cc-by-sa-4.0": "CC-BY-SA-4.0",
    "cc-by-nc-4.0": "CC-BY-NC-4.0",
    "cc-by-nc-sa-4.0": "CC-BY-NC-SA-4.0",
    "cc-by-nd-4.0": "CC-BY-ND-4.0",
    "odc-by": "ODC-By-1.0",
    "bsd-3-clause": "BSD-3-Clause",
    "gpl-3.0": "GPL-3.0",
}
_REQUEST_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class EvalMetadata:
    """What inspect's eval.yaml declares for one imported task."""

    package: str
    paper_url: str | None
    inspect_contributors: tuple[str, ...]
    upstream_case_count: int | None
    #: (score, source URL) on the task's own headline metric, when the file ships one.
    human_baseline: tuple[float, str] | None
    #: inspect files the eval under its Safeguards group: the row gets a content-warning
    #: review mark (F9); nothing here judges the prompts themselves.
    safeguards: bool


@dataclass(frozen=True)
class ArxivEntry:
    """The paper's arXiv entry, reduced to the two strings the row carries."""

    authors: str
    citation: str


@dataclass(frozen=True)
class ProvenanceFacts:
    """Everything the importer learned, handed to the row renderer in one piece."""

    metadata: EvalMetadata | None
    arxiv: ArxivEntry | None
    inspect_evals_version: str


def read_eval_metadata(task_ref: str, *, root: Path | None = None) -> EvalMetadata | None:
    """Stage 1: the task's eval.yaml facts, or None when the eval ships no such file.

    ``task_ref`` is ``"inspect_evals.<package>.<module>:<task>"``; the file lives at
    ``<root>/<package>/eval.yaml``. ``root`` defaults to the installed inspect_evals package
    and is injectable for tests.
    """

    located: tuple[str, str] | None = _package_and_task(task_ref)
    if located is None:
        return None
    package, task_name = located
    document: dict[str, Any] | None = _eval_document(package, root)
    if document is None:
        return None
    task: dict[str, Any] = _task_entry(document, task_name)
    samples: Any = task.get("dataset_samples")
    paper: Any = document.get("arxiv")
    contributors: Any = document.get("contributors") or ()
    return EvalMetadata(
        package=package,
        paper_url=str(paper) if isinstance(paper, str) and paper.strip() else None,
        inspect_contributors=tuple(str(name) for name in contributors if isinstance(name, str)),
        upstream_case_count=int(samples) if isinstance(samples, int) else None,
        human_baseline=_baseline_of(task),
        safeguards=document.get("group") == "Safeguards",
    )


def _package_and_task(task_ref: str) -> tuple[str, str] | None:
    """``inspect_evals.mmlu.mmlu:mmlu_0_shot`` → (``mmlu``, ``mmlu_0_shot``); None elsewhere."""

    module_name, _, task_name = task_ref.partition(":")
    parts: list[str] = module_name.split(".")
    if len(parts) < 2 or parts[0] != "inspect_evals" or not task_name:
        return None
    return parts[1], task_name


def _eval_document(package: str, root: Path | None) -> dict[str, Any] | None:
    """The parsed eval.yaml mapping, or None when absent or unreadable."""

    text: str | None = _eval_yaml_text(package, root)
    if text is None:
        return None
    try:
        document: Any = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return document if isinstance(document, dict) else None


def _task_entry(document: dict[str, Any], task_name: str) -> dict[str, Any]:
    """The ``tasks`` entry whose name is the imported task, or an empty mapping."""

    return next(
        (
            entry
            for entry in document.get("tasks") or ()
            if isinstance(entry, dict) and entry.get("name") == task_name
        ),
        {},
    )


def _baseline_of(task: dict[str, Any]) -> tuple[float, str] | None:
    """The task's ``human_baseline`` as (score, source), when the file ships one."""

    baseline: Any = task.get("human_baseline")
    if isinstance(baseline, dict) and isinstance(baseline.get("score"), int | float):
        return (float(baseline["score"]), str(baseline.get("source") or ""))
    return None


def _eval_yaml_text(package: str, root: Path | None) -> str | None:
    """The eval.yaml text from a directory root or from the installed package."""

    if root is not None:
        path: Path = root / package / "eval.yaml"
        return path.read_text(encoding="utf-8") if path.is_file() else None
    try:
        resource = files("inspect_evals") / package / "eval.yaml"
        return resource.read_text(encoding="utf-8") if resource.is_file() else None
    except (ModuleNotFoundError, OSError, TypeError):
        return None


def read_arxiv_entry(
    paper_url: str, *, fetch: Callable[[str], str] | None = None
) -> ArxivEntry | None:
    """Stage 2: the paper's author line and BibTeX from arXiv, or None (F8).

    Two requests: the Atom feed for the author names and the year, the bibtex page for the
    citation. Any network or parse failure returns None; nothing is guessed.
    """

    match = _ARXIV_ID.search(paper_url)
    if match is None:
        return None
    arxiv_id: str = match.group("id")
    fetch_text: Callable[[str], str] = fetch or _http_get
    try:
        atom: str = fetch_text(_ARXIV_API.format(arxiv_id=arxiv_id))
        bibtex: str = fetch_text(_ARXIV_BIBTEX.format(arxiv_id=arxiv_id))
        authors: str | None = _author_line(atom)
    # http.client.HTTPException is NOT an OSError: a truncated or malformed reply would
    # traceback out of the importer before any row is written (review finding on PR 1236).
    except (OSError, ValueError, ET.ParseError, http.client.HTTPException):
        return None
    citation: str = bibtex.strip()
    usable: bool = authors is not None and citation.startswith("@")
    return ArxivEntry(authors=authors or "", citation=citation) if usable else None


def _author_line(atom: str) -> str | None:
    """``Hendrycks et al., 2020``; up to three authors are named in full."""

    entry = ET.fromstring(atom).find(f"{_ATOM}entry")
    names: list[str] = (
        []
        if entry is None
        else [
            name.text.strip()
            for name in entry.findall(f"{_ATOM}author/{_ATOM}name")
            if name.text and name.text.strip()
        ]
    )
    year: str = ("" if entry is None else entry.findtext(f"{_ATOM}published") or "")[:4]
    if not names or not year.isdigit():
        return None
    return _short_author_line(names, year)


def _short_author_line(names: list[str], year: str) -> str:
    """Up to three names in full, else the first surname with et al."""

    if len(names) > 3:
        return f"{names[0].split()[-1]} et al., {year}"
    joined: str = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    return f"{joined}, {year}"


def _http_get(url: str) -> str:
    """One GET with a timeout; the only network call this module makes."""

    with urllib.request.urlopen(url, timeout=_REQUEST_TIMEOUT_SECONDS) as reply:  # noqa: S310
        return reply.read().decode("utf-8")


def read_provenance_facts(
    task_ref: str, *, fetch: Callable[[str], str] | None = None
) -> ProvenanceFacts:
    """Stages 1 and 2 together, as the CLI runs them."""

    metadata: EvalMetadata | None = read_eval_metadata(task_ref)
    arxiv: ArxivEntry | None = (
        read_arxiv_entry(metadata.paper_url, fetch=fetch)
        if metadata is not None and metadata.paper_url is not None
        else None
    )
    return ProvenanceFacts(
        metadata=metadata, arxiv=arxiv, inspect_evals_version=_installed_version("inspect-evals")
    )


def harness_url_for(package: str, *, version: str) -> str:
    """The inspect_evals task directory on GitHub at the installed version's tag."""

    return _INSPECT_EVALS_TREE.format(version=version, package=package)


def spdx_license(hub_license: str | None) -> str | None:
    """The Hub's licence string in its SPDX spelling, or as the Hub wrote it, or None."""

    if hub_license is None or not hub_license.strip():
        return None
    return _SPDX.get(hub_license.strip().lower(), hub_license.strip())


def provenance_row_lines(
    facts: ProvenanceFacts, hub_license: str | None, cleared_licenses: frozenset[str]
) -> list[str]:
    """Stage 3: the BenchmarkSpec lines for the provenance fields; TODO where only a human can.

    Every value is written through ``json.dumps`` so Hub- or arXiv-controlled text stays a
    string literal; the composed file is ast-verified again before it is written.
    ``cleared_licenses`` is the importer's cleared list (lowercase Hub spellings): a card
    licence outside it is written as the TODO the owner resolves, never served as-is.
    """

    return [
        "        # Benchmark Provenance (OME-1455): paper, inspect porters, baseline and size",
        "        # read from the eval's eval.yaml; authors and citation from arXiv. Every TODO",
        "        # below is refused by name at registration, so an unreviewed row cannot ship.",
        *_paper_lines(facts.metadata, facts.arxiv),
        *_people_and_harness_lines(facts.metadata, facts.inspect_evals_version),
        *_licence_and_warning_lines(facts.metadata, hub_license, cleared_licenses),
        *_score_lines(facts.metadata),
        f"        notebook={json.dumps(IMPORTED_NOTEBOOK)},",
        *_size_lines(facts.metadata),
    ]


def _paper_lines(metadata: EvalMetadata | None, arxiv: ArxivEntry | None) -> list[str]:
    """paper_url from eval.yaml; authors and citation from arXiv; TODO for each gap."""

    paper: str | None = metadata.paper_url if metadata is not None else None
    lines: list[str] = []
    if paper is None:
        lines.append("        # TODO(review): eval.yaml names no paper; link it, or NotPublished.")
    lines.append(f"        paper_url={json.dumps(paper or 'TODO')},")
    if arxiv is None:
        lines.append(
            "        # TODO(review): arXiv gave no entry; write the author line and BibTeX."
        )
        lines.append('        authors="TODO",')
        lines.append('        citation="TODO",')
    else:
        lines.append(f"        authors={json.dumps(arxiv.authors)},")
        lines.extend(_citation_lines(arxiv.citation))
    return lines


def _people_and_harness_lines(metadata: EvalMetadata | None, version: str) -> list[str]:
    """The inspect porters from eval.yaml and the harness at the pin; nothing here is a TODO."""

    lines: list[str] = []
    if metadata is not None and metadata.inspect_contributors:
        handles: str = ", ".join(json.dumps(name) for name in metadata.inspect_contributors)
        # A one-element tuple keeps its trailing comma; a longer one reads like the rows above.
        trailing: str = "," if len(metadata.inspect_contributors) == 1 else ""
        lines.append(f"        inspect_contributors=({handles}{trailing}),")
    harness: str = (
        harness_url_for(metadata.package, version=version) if metadata is not None else "TODO"
    )
    lines.append(f"        harness_url={json.dumps(harness)},")
    return lines


def _licence_and_warning_lines(
    metadata: EvalMetadata | None, hub_license: str | None, cleared_licenses: frozenset[str]
) -> list[str]:
    """The SPDX licence from the Hub card; a content-warning TODO for a Safeguards eval (F9).

    WHY the cleared list applies here too: the importer turns an uncleared card licence
    into the owner's TODO (OME-1273 D13), and the served ``license=`` line must agree with
    that decision rather than re-read the card (review finding on PR 1236).
    """

    spdx: str | None = spdx_license(hub_license)
    cleared: bool = (hub_license or "").strip().lower() in cleared_licenses
    lines: list[str] = []
    if spdx is None:
        lines.append(
            "        # TODO(review): the Hub card names no licence; find it, or NotPublished."
        )
    elif not cleared:
        lines.append(
            f"        # TODO(review): the Hub card says {json.dumps(spdx)}, which is not on the"
        )
        lines.append("        # cleared list; the owner decides the licence, or NotPublished.")
    lines.append(f"        license={json.dumps(spdx if cleared else 'TODO')},")
    if metadata is not None and metadata.safeguards:
        lines.append("        # TODO(review): inspect files this eval under Safeguards — write the")
        lines.append("        # content warning readers see above the strip, or remove this field.")
        lines.append('        content_warning="TODO",')
    return lines


def _score_lines(metadata: EvalMetadata | None) -> list[str]:
    """The human baseline when eval.yaml ships one; the frontier score is always a human's."""

    lines: list[str] = []
    if metadata is not None and metadata.human_baseline is not None:
        score, source = metadata.human_baseline
        lines.append(
            f"        human_baseline=HumanBaseline(score={score!r}, "
            f"source_url={json.dumps(source)}),"
        )
    else:
        lines.append(
            "        # TODO(review): eval.yaml ships no human baseline; source one from the"
        )
        lines.append("        # paper, or give the reason none is published.")
        lines.append('        human_baseline=NotPublished(reason="TODO"),')
    lines.append(
        "        # TODO(review): the best published score — model, source URL, as-of month —"
    )
    lines.append("        # or the reason none is published.")
    lines.append('        frontier_score=NotPublished(reason="TODO"),')
    return lines


def _size_lines(metadata: EvalMetadata | None) -> list[str]:
    """inspect's declared size, for the conformance cross-check (spec §3.1)."""

    if metadata is None or metadata.upstream_case_count is None:
        return []
    return [f"        upstream_case_count={metadata.upstream_case_count},"]


#: The longest string literal one generated citation line may hold, so the rendered line
#: (12 columns of indent plus quotes and escapes) stays under the 100-column lint gate.
_CITATION_LINE_WIDTH: int = 76


def _citation_lines(citation: str) -> list[str]:
    """A multi-line BibTeX as a parenthesised run of string literals.

    WHY the width split: a BibTeX ``author={...}`` line for a seven-author paper is 150
    characters, and one literal per BibTeX line put it past the lint gate on the first real
    import (OME-1455 PR 3). Adjacent literals concatenate, so the value is unchanged.
    """

    pieces: list[str] = citation.splitlines()
    if len(pieces) == 1 and len(citation) <= _CITATION_LINE_WIDTH:
        return [f"        citation={json.dumps(citation)},"]
    rendered: list[str] = ["        citation=("]
    for index, piece in enumerate(pieces):
        text: str = piece + chr(10) if index < len(pieces) - 1 else piece
        for start in range(0, max(len(text), 1), _CITATION_LINE_WIDTH):
            rendered.append(f"            {json.dumps(text[start : start + _CITATION_LINE_WIDTH])}")
    rendered.append("        ),")
    return rendered


__all__ = [
    "IMPORTED_NOTEBOOK",
    "ArxivEntry",
    "EvalMetadata",
    "ProvenanceFacts",
    "harness_url_for",
    "provenance_row_lines",
    "read_arxiv_entry",
    "read_eval_metadata",
    "read_provenance_facts",
    "spdx_license",
]
