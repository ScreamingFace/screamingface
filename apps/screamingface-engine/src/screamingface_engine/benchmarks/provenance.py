"""Benchmark Provenance, Human Baseline, Frontier Score and the Benchmark Saturation verdict.

FEATURE: show where each Benchmark comes from and how much room frontier models have left
on it (OME-1455). Think of a Benchmark as an exam. This module holds the facts printed on
the exam's cover sheet that say nothing about the questions themselves: who wrote it, who
brought it here, where the original code and data live, may you use it, how humans and the
best published model scored, and one derived word, saturated / open / unknown, that says
whether a further gain on it can still show a capability difference.

INVARIANT: nothing here enters a Benchmark Revision. A link or a baseline says nothing about
which Cases are asked or how they are graded, so editing one must never make a recorded
Leaderboard Score look incomparable (the OME-904 rule for ``focus`` and ``dataset_url``).

The three stages, in the order a Benchmark meets them:

1. Authoring: a definition module (or the importer's generated row) fills the fields on
   ``Benchmark``; ``validate_provenance`` refuses a malformed value where it is typed.
2. Serving: ``provenance_metadata`` projects the fields onto the catalogue entry, present-only
   (an absent field is an absent key, never null) with ``saturation`` always emitted.
3. Conformance: a test over every registered Benchmark asks that each required field is
   present or declared ``NotPublished`` with a reason, except ids grandfathered until the
   values PR lands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from screamingface_engine.benchmarks.definition import Benchmark

type Saturation = Literal["saturated", "open", "unknown"]


class ProvenanceFields(TypedDict, total=False):
    """The provenance keyword arguments every Benchmark factory accepts and passes through.

    WHY a TypedDict and not twelve parameters per factory: the three variant factories
    and the imported-row assembler are pass-throughs for these; one declaration of the names
    here, `**provenance: Unpack[ProvenanceFields]` there, so a field added to `Benchmark` is
    added in one place and pyright refuses a misspelled key at every call site.
    INVARIANT: key-for-key the provenance fields on `Benchmark` (definition.py).
    """

    paper_url: str | NotPublished | None
    authors: str | None
    citation: str | NotPublished | None
    inspect_contributors: tuple[str, ...] | None
    homepage_url: str | None
    harness_url: str | None
    license: str | NotPublished | None
    license_note: str | None
    content_warning: str | None
    human_baseline: HumanBaseline | NotPublished | None
    frontier_score: FrontierScore | NotPublished | None
    notebook: str | None


#: The provenance field names, in declaration order — the one list the row assembler and
#: the conformance test iterate.
PROVENANCE_FIELD_NAMES: tuple[str, ...] = tuple(ProvenanceFields.__annotations__)

#: Required means present, or declared NotPublished with a reason (spec §2.1). The three
#: optional fields (homepage_url, license_note, content_warning) are never asked for;
#: inspect_contributors is asked for on an inspect_evals-origin Benchmark only.
#: WHY here and not in the test: the conformance test runs in CI's inspect lane (the only
#: lane where the imported Benchmarks register), the fixture probe runs in the extra-less
#: lane, and the fidelity sweep (OME-1471) will ask the same question — one rule, one home.
REQUIRED_PROVENANCE_FIELDS: tuple[str, ...] = (
    "paper_url",
    "authors",
    "citation",
    "harness_url",
    "license",
    "human_baseline",
    "frontier_score",
    "notebook",
)

# The one named constant behind the verdict: headroom = 1.0 − frontier score; saturated when
# headroom ≤ this floor. WHY 0.10: Akhtar et al. (arXiv 2602.16763) give no fixed cutoff —
# their rule is statistical indistinguishability of the top models plus closeness to the
# empirical ceiling, which needs several scored models we do not have per Benchmark. Where
# the field does pick a number, 80% is the common "saturated" line and 90–92% is where
# ceiling effects are said to begin; 0.10 (top ≥ 90%) is the conservative end of that range,
# so fewer Benchmarks wear the badge, never a wrong one. Changing it is a one-line PR.
SATURATION_HEADROOM: float = 0.10
#: INVARIANT: value-for-value identical to the SDK's `SATURATION_VERDICTS` in
#: `_catalogue_vocabulary.py`; pinned by test_catalogue_vocabulary_conformance on BOTH sides.
SATURATION_VERDICTS: tuple[Saturation, ...] = ("saturated", "open", "unknown")

_WEB_URL = re.compile(r"https?://\S+")
# A GitHub username: 1–39 chars of [A-Za-z0-9-], no leading, trailing or doubled hyphen.
# WHY a handle and not a URL: the pages derive the profile link from it, inspect's eval.yaml
# ships handles, and a handle is checkable here where a URL would need parsing to prove the
# same thing.
_GITHUB_HANDLE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
# A harness link is pinned when its path names a commit sha or a version tag after
# /tree/, /blob/, /commit/ or an @ — never a branch name, never the repo root (F7).
_PINNED_REF = re.compile(
    r"(?:/(?:tree|blob|commit)/|@)(?:[0-9a-f]{7,40}|v?\d+(?:\.\d+)+(?:[-.][A-Za-z0-9]+)*)(?:/|$)"
)
_DEFAULT_BRANCH = re.compile(r"/(?:tree|blob)/(?:main|master)(?:/|$)")
# WHY refuse our own monorepo: the harness link is the evidence a fidelity check (OME-1471)
# compares our translation against; pointing it at ourselves compares our code with itself.
_OUR_MONOREPO = "github.com/ScreamingFace/"
_AS_OF_MONTH = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])")
_NOTEBOOK_STEM = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*")

#: Longest text each string field may carry. INVARIANT: the Scoreboard stores the block as
#: one JSON column (spec §4.1), so these guard page layout, not a column width.
PROVENANCE_TEXT_LIMITS: dict[str, int] = {
    "authors": 255,
    "license": 64,
    "license_note": 255,
    "content_warning": 255,
    "notebook": 120,
}


@dataclass(frozen=True, slots=True)
class NotPublished:
    """A declaration that no such fact exists, with the reason a reviewer reads.

    Written where the value would go (``human_baseline=NotPublished(reason=...)``), so the
    reason sits beside the field. It passes the conformance test; silence does not. It is
    never served: the pages omit the field the same way they omit a missing one.
    """

    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("NotPublished reason must be non-empty text")


@dataclass(frozen=True, slots=True)
class HumanBaseline:
    """The published human score on the Benchmark's own headline metric, with its source."""

    score: float
    source_url: str

    def __post_init__(self) -> None:
        _check_score("HumanBaseline score", self.score)
        _check_url("HumanBaseline source_url", self.source_url)

    def as_block(self) -> dict[str, object]:
        return {"score": self.score, "source_url": self.source_url}


@dataclass(frozen=True, slots=True)
class FrontierScore:
    """The best published AI score on the headline metric: model, source and as-of month.

    For an Inverted Grade Benchmark the score is already 1 − the published rate, so the one
    saturation rule holds unchanged; the conversion is named in ``model`` or on the source.
    """

    score: float
    model: str
    source_url: str
    as_of: str

    def __post_init__(self) -> None:
        _check_score("FrontierScore score", self.score)
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("FrontierScore model must be non-empty text")
        _check_url("FrontierScore source_url", self.source_url)
        if not isinstance(self.as_of, str) or _AS_OF_MONTH.fullmatch(self.as_of) is None:
            raise ValueError("FrontierScore as_of must be an ISO month such as 2026-09")

    def as_block(self) -> dict[str, object]:
        return {
            "score": self.score,
            "model": self.model,
            "source_url": self.source_url,
            "as_of": self.as_of,
        }


def saturation_verdict(frontier: FrontierScore | NotPublished | None) -> Saturation:
    """One word for "can a further gain here still show a capability difference?".

    Worked example: frontier 0.92 → headroom 0.08 ≤ 0.10 → ``saturated``; frontier 0.60 →
    headroom 0.40 → ``open``; no frontier score → ``unknown``. The Human Baseline is never an
    input: human-level is not saturated (glossary, Benchmark Saturation).
    """

    if not isinstance(frontier, FrontierScore):
        return "unknown"
    headroom: float = 1.0 - frontier.score
    return "saturated" if headroom <= SATURATION_HEADROOM else "open"


def validate_provenance(benchmark: Benchmark) -> None:
    """Refuse a malformed provenance value where it is typed (stage 1).

    Every check is a shape check: http(s) links, GitHub handles, a pinned harness link, text
    limits, an ISO month. Whether a value is TRUE is the reviewer's job (spec §5).
    """

    _check_links_and_text(benchmark)
    _check_people(benchmark)
    _check_scores_and_sentinels(benchmark)
    _check_no_todo(benchmark)


def _check_no_todo(benchmark: Benchmark) -> None:
    """Refuse the importer's literal TODO wherever it was left, like difficulty="TODO".

    WHY: "TODO" is a valid GitHub handle and a non-blank reason, so without this rule an
    unreviewed generated row would register clean. The match is EXACT (case-insensitive,
    whitespace-trimmed): every placeholder the importer writes is the bare word, so that is
    what is refused; "TODO: fill" is a human's text and passes.
    """

    for name in PROVENANCE_FIELD_NAMES:
        value = getattr(benchmark, name)
        texts: tuple[str, ...]
        if isinstance(value, str):
            texts = (value,)
        elif isinstance(value, NotPublished):
            texts = (value.reason,)
        elif isinstance(value, tuple):
            texts = value
        else:
            continue
        if any(text.strip().upper() == "TODO" for text in texts):
            raise ValueError(
                f"Benchmark {name} is still the importer's TODO; resolve the TODO(review) "
                "before registering"
            )


def _check_links_and_text(benchmark: Benchmark) -> None:
    """The string fields: http(s) links, non-blank text, the notebook stem, text limits."""

    _check_optional_url("paper_url", benchmark.paper_url)
    _check_optional_url("homepage_url", benchmark.homepage_url)
    _check_harness(benchmark.harness_url)
    for name in ("authors", "citation", "license", "license_note", "content_warning", "notebook"):
        _check_optional_text(name, getattr(benchmark, name))
    notebook = benchmark.notebook
    if isinstance(notebook, str) and _NOTEBOOK_STEM.fullmatch(notebook) is None:
        raise ValueError(
            "Benchmark notebook must be the bare stem of an SDK example notebook "
            "(no path, no .ipynb), such as 12_inspect_evals_benchmarks"
        )
    for name, limit in PROVENANCE_TEXT_LIMITS.items():
        value = getattr(benchmark, name)
        if isinstance(value, str) and len(value) > limit:
            raise ValueError(f"Benchmark {name} must be at most {limit} characters")


def _check_people(benchmark: Benchmark) -> None:
    """The inspect porters' handle list, and the rule that it exists only on an import.

    WHY no `contributors` list for who typed the row here (owner decision, 2026-10-06): in a
    team-only registry it was one handle on 57 of 65 rows, git already holds it, and the
    field a syft-space data owner will need is a different one (org and contact, not a
    GitHub handle tuple). The porters upstream are real provenance: credit owed outside.
    """

    _check_handles("inspect_contributors", benchmark.inspect_contributors)
    if benchmark.inspect_contributors is not None and benchmark.origin != "inspect_evals":
        raise ValueError(
            "Benchmark inspect_contributors credits whoever ported the eval into inspect, "
            "so only an inspect_evals-origin Benchmark may declare it"
        )


def _check_scores_and_sentinels(benchmark: Benchmark) -> None:
    """The two score records, and which fields may never be declared NotPublished."""

    for name in ("authors", "harness_url", "notebook"):
        if isinstance(getattr(benchmark, name), NotPublished):
            raise TypeError(
                f"Benchmark {name} always exists for a published Benchmark; "
                "it cannot be declared NotPublished"
            )
    # WHY each field against its OWN class: a FrontierScore typed as the baseline (or the
    # reverse) would register clean, serve a verdict of "unknown" and omit the key, with no
    # error anywhere (review finding on PR 1236).
    if not isinstance(benchmark.human_baseline, HumanBaseline | NotPublished | type(None)):
        raise TypeError("Benchmark human_baseline must be a HumanBaseline or NotPublished")
    if not isinstance(benchmark.frontier_score, FrontierScore | NotPublished | type(None)):
        raise TypeError("Benchmark frontier_score must be a FrontierScore or NotPublished")


def provenance_metadata(benchmark: Benchmark) -> dict[str, object]:
    """Project the provenance fields onto the served catalogue entry (stage 2).

    Present-only: a ``None`` or ``NotPublished`` field is an absent key, never null, so a
    seeded row is left untouched rather than blanked. ``saturation`` is always emitted:
    "unknown" is a verdict, not a gap.
    """

    served: dict[str, object] = {}
    for name in (
        "paper_url",
        "authors",
        "citation",
        "homepage_url",
        "harness_url",
        "license",
        "license_note",
        "content_warning",
        "notebook",
    ):
        value = getattr(benchmark, name)
        if isinstance(value, str):
            served[name] = value
    if benchmark.inspect_contributors is not None:
        served["inspect_contributors"] = list(benchmark.inspect_contributors)
    if isinstance(benchmark.human_baseline, HumanBaseline):
        served["human_baseline"] = benchmark.human_baseline.as_block()
    if isinstance(benchmark.frontier_score, FrontierScore):
        served["frontier_score"] = benchmark.frontier_score.as_block()
    served["saturation"] = saturation_verdict(benchmark.frontier_score)
    return served


def provenance_gaps(benchmark: Benchmark) -> list[str]:
    """The required fields this Benchmark left silent (stage 3); empty when it complies.

    A ``NotPublished`` with a reason is not a gap; ``None`` is.
    """

    gaps: list[str] = [
        name for name in REQUIRED_PROVENANCE_FIELDS if getattr(benchmark, name) is None
    ]
    if benchmark.origin == "inspect_evals" and benchmark.inspect_contributors is None:
        gaps.append("inspect_contributors")
    return gaps


def _check_score(label: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{label} must be a number between 0 and 1 on the headline metric")


def _check_url(label: str, value: object) -> None:
    if not isinstance(value, str) or _WEB_URL.fullmatch(value) is None:
        raise ValueError(f"{label} must be an absolute http(s) URL")


def _check_optional_url(name: str, value: object) -> None:
    if value is None or isinstance(value, NotPublished):
        return
    _check_url(f"Benchmark {name}", value)


def _check_optional_text(name: str, value: object) -> None:
    if value is None or isinstance(value, NotPublished):
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Benchmark {name} must be non-empty text when declared")


def _check_handles(name: str, value: object) -> None:
    if value is None:
        return
    if not isinstance(value, tuple) or not value:
        raise ValueError(f"Benchmark {name} must be a non-empty tuple of GitHub usernames")
    for handle in value:
        if not isinstance(handle, str) or _GITHUB_HANDLE.fullmatch(handle) is None:
            raise ValueError(f"Benchmark {name} entry {handle!r} is not a valid GitHub username")


def _check_harness(value: object) -> None:
    if value is None:
        return
    _check_url("Benchmark harness_url", value)
    assert isinstance(value, str)
    if _OUR_MONOREPO in value:
        raise ValueError(
            "Benchmark harness_url must point at the original upstream code, never this monorepo"
        )
    if _DEFAULT_BRANCH.search(value) is not None or _PINNED_REF.search(value) is None:
        raise ValueError(
            "Benchmark harness_url must be pinned to a commit sha or a version tag "
            "(a /tree/, /blob/, /commit/ or @ reference), never a branch or a repo root"
        )


__all__ = [
    "PROVENANCE_FIELD_NAMES",
    "PROVENANCE_TEXT_LIMITS",
    "ProvenanceFields",
    "SATURATION_HEADROOM",
    "SATURATION_VERDICTS",
    "FrontierScore",
    "HumanBaseline",
    "NotPublished",
    "Saturation",
    "provenance_metadata",
    "saturation_verdict",
    "validate_provenance",
]
