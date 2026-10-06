"""The importer fills what inspect's eval.yaml and the paper's arXiv entry know (OME-1455, box ③).

FEATURE: Benchmark Provenance on Imported Benchmarks, filled at import time.
STORY: as the agent importing an eval, I get the paper, the inspect porters, the human
baseline, inspect's declared size, the licence, the harness link, the authors and the
BibTeX for free, and a TODO(review) line for everything only a human can source.

INVARIANT: no test here opens a socket. eval.yaml is read from a temp directory; the
arXiv reply is an injected fixture; an injected failure stands in for arXiv being down.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine_inspect.case_sources import CaseSource  # noqa: E402
from screamingface_engine_inspect.import_replay import (  # noqa: E402
    TaskReplayFacts,
    TaskReplayImport,
)
from screamingface_engine_inspect.prepare import TaskReplayCasesSpec  # noqa: E402
from screamingface_engine_inspect.provenance_facts import (  # noqa: E402
    ArxivEntry,
    EvalMetadata,
    ProvenanceFacts,
    harness_url_for,
    read_arxiv_entry,
    read_eval_metadata,
)
from screamingface_engine_inspect.task_replay_rows import render_task_replay_rows  # noqa: E402

_MMLU_EVAL_YAML = """\
title: 'MMLU: Measuring Massive Multitask Language Understanding'
description: |
  Evaluate models on 57 tasks.
arxiv: https://arxiv.org/abs/2009.03300
group: Knowledge
contributors:
  - jjallaire
  - domdomegg
version: "3-A"
tasks:
  - name: mmlu_0_shot
    dataset_samples: 14042
    human_baseline:
      metric: accuracy
      score: 0.898
      source: https://arxiv.org/abs/2009.03300
  - name: mmlu_5_shot
    dataset_samples: 14042
"""

_SAFEGUARDS_EVAL_YAML = """\
title: AgentHarm
arxiv: https://arxiv.org/abs/2410.09024
group: Safeguards
contributors:
  - alexandrasouly-aisi
tasks:
  - name: agentharm
    dataset_samples: 176
"""

_ARXIV_ATOM = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2009.03300v3</id>
    <published>2020-09-07T17:32:45Z</published>
    <title>Measuring Massive Multitask Language Understanding</title>
    <author><name>Dan Hendrycks</name></author>
    <author><name>Collin Burns</name></author>
    <author><name>Steven Basart</name></author>
    <author><name>Andy Zou</name></author>
  </entry>
</feed>
"""

_ARXIV_BIBTEX = """\
@misc{hendrycks2020measuring,
      title={Measuring Massive Multitask Language Understanding},
      author={Dan Hendrycks and Collin Burns},
      year={2020},
      eprint={2009.03300},
}
"""


def _root_with(tmp_path: Path, package: str, text: str) -> Path:
    (tmp_path / package).mkdir()
    (tmp_path / package / "eval.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def _fetch_arxiv(url: str) -> str:
    """A recorded arXiv: the API's Atom for the author list, the bibtex page for the citation."""

    if "export.arxiv.org/api/query" in url:
        return _ARXIV_ATOM
    if "arxiv.org/bibtex/" in url:
        return _ARXIV_BIBTEX
    raise AssertionError(f"unexpected arXiv URL {url}")


# --- eval.yaml -------------------------------------------------------------------------------


def test_eval_metadata_is_read_for_the_imported_task_by_name(tmp_path: Path) -> None:
    root = _root_with(tmp_path, "mmlu", _MMLU_EVAL_YAML)

    metadata = read_eval_metadata("inspect_evals.mmlu.mmlu:mmlu_0_shot", root=root)

    assert metadata == EvalMetadata(
        package="mmlu",
        paper_url="https://arxiv.org/abs/2009.03300",
        inspect_contributors=("jjallaire", "domdomegg"),
        upstream_case_count=14042,
        human_baseline=(0.898, "https://arxiv.org/abs/2009.03300"),
        safeguards=False,
    )


def test_a_task_without_a_baseline_reads_none_for_it(tmp_path: Path) -> None:
    root = _root_with(tmp_path, "mmlu", _MMLU_EVAL_YAML)

    metadata = read_eval_metadata("inspect_evals.mmlu.mmlu:mmlu_5_shot", root=root)

    assert metadata is not None
    assert metadata.human_baseline is None
    assert metadata.upstream_case_count == 14042


def test_a_safeguards_eval_is_marked_for_a_content_warning_review(tmp_path: Path) -> None:
    root = _root_with(tmp_path, "agentharm", _SAFEGUARDS_EVAL_YAML)

    metadata = read_eval_metadata("inspect_evals.agentharm.agentharm:agentharm", root=root)

    assert metadata is not None
    assert metadata.safeguards is True


def test_a_task_name_the_file_does_not_list_reads_no_size_and_no_baseline(
    tmp_path: Path,
) -> None:
    root = _root_with(tmp_path, "mmlu", _MMLU_EVAL_YAML)

    metadata = read_eval_metadata("inspect_evals.mmlu.mmlu:mmlu_renamed", root=root)

    assert metadata is not None
    assert metadata.paper_url == "https://arxiv.org/abs/2009.03300"
    assert metadata.upstream_case_count is None
    assert metadata.human_baseline is None


def test_an_eval_without_a_metadata_file_reads_none(tmp_path: Path) -> None:
    # F1: the fields stay TODO and the conformance test names the Benchmark later.
    assert read_eval_metadata("inspect_evals.nothing.nothing:nothing", root=tmp_path) is None


def test_a_task_outside_inspect_evals_reads_none(tmp_path: Path) -> None:
    assert read_eval_metadata("acme.sums:sums", root=tmp_path) is None


def test_the_installed_catalogue_ships_mmlu_metadata() -> None:
    # The one test that touches the real installed package: the default root resolves to
    # inspect_evals at the pinned version, and MMLU's file is the ticket's fixture.
    metadata = read_eval_metadata("inspect_evals.mmlu.mmlu:mmlu_0_shot")

    assert metadata is not None
    assert metadata.paper_url == "https://arxiv.org/abs/2009.03300"
    assert metadata.human_baseline == (0.898, "https://arxiv.org/abs/2009.03300")


# --- arXiv -----------------------------------------------------------------------------------


def test_the_arxiv_entry_gives_a_short_author_line_and_the_bibtex() -> None:
    entry = read_arxiv_entry("https://arxiv.org/abs/2009.03300", fetch=_fetch_arxiv)

    assert entry == ArxivEntry(
        authors="Hendrycks et al., 2020",
        citation=_ARXIV_BIBTEX.strip(),
    )


def test_up_to_three_authors_are_named_in_full() -> None:
    atom = _ARXIV_ATOM.replace("    <author><name>Andy Zou</name></author>\n", "").replace(
        "    <author><name>Steven Basart</name></author>\n", ""
    )

    def fetch(url: str) -> str:
        return atom if "api/query" in url else _ARXIV_BIBTEX

    entry = read_arxiv_entry("https://arxiv.org/abs/2009.03300", fetch=fetch)

    assert entry is not None
    assert entry.authors == "Dan Hendrycks and Collin Burns, 2020"


@pytest.mark.parametrize(
    "url", ["https://arxiv.org/abs/2009.03300", "https://arxiv.org/pdf/2009.03300v3"]
)
def test_the_arxiv_id_is_taken_from_abs_and_pdf_links(url: str) -> None:
    seen: list[str] = []

    def fetch(request: str) -> str:
        seen.append(request)
        return _fetch_arxiv(request)

    assert read_arxiv_entry(url, fetch=fetch) is not None
    assert any(request.endswith("id_list=2009.03300") for request in seen)
    assert any(request.endswith("/bibtex/2009.03300") for request in seen)


def test_arxiv_being_down_leaves_authors_and_citation_for_the_agent() -> None:
    # F8: no exception escapes; the generated row carries TODO(review) for both.
    def fetch(url: str) -> str:
        raise OSError("connection refused")

    assert read_arxiv_entry("https://arxiv.org/abs/2009.03300", fetch=fetch) is None


def test_a_paper_that_is_not_on_arxiv_is_left_for_the_agent() -> None:
    def fetch(url: str) -> str:
        raise AssertionError("must not be called")

    assert read_arxiv_entry("https://aclanthology.org/2021.acl-long.1/", fetch=fetch) is None


# --- the harness link ------------------------------------------------------------------------


def test_the_harness_link_is_the_inspect_evals_tree_at_the_installed_tag() -> None:
    # INVARIANT (F7): pinned to the version tag the Engine installs, so it follows the
    # OME-1421 pin bump and never a default branch.
    assert harness_url_for("mmlu", version="0.20.0") == (
        "https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/mmlu"
    )


# --- the generated row -----------------------------------------------------------------------

_MMLU_TASK: str = "inspect_evals.mmlu.mmlu:mmlu_0_shot"
_MMLU_SOURCE: str = "https://huggingface.co/datasets/cais/mmlu"


def _imported(task_ref: str = _MMLU_TASK) -> TaskReplayImport:
    """A sealed Task-replay import as import_by_task_replay returns it (no child runs here)."""

    facts: TaskReplayFacts = TaskReplayFacts(
        task_ref=task_ref,
        task_args=None,
        mcq=True,
        scorer="inspect_ai.scorer:choice",
        scorer_kwargs={},
        custom_metrics=(),
        keep_sample_metadata=False,
    )
    declaration: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task=task_ref, case_count=14042, case_digest="e" * 64
    )
    return TaskReplayImport(
        declaration=declaration,
        case_sources=(CaseSource("url", _MMLU_SOURCE, "commit " + "c" * 40),),
        facts=facts,
    )


def _row(
    license: str,
    provenance: ProvenanceFacts | None,
    *,
    key: str = "mmlu",
    task_ref: str = _MMLU_TASK,
) -> str:
    """The BenchmarkSpec row the importer writes for one eval, on its one path (OME-1460).

    ``license`` is what the importer decided from the card: a cleared value as the card
    spells it, or the raw card value, which the provenance lines must turn into a TODO.
    """

    return render_task_replay_rows(
        key, _imported(task_ref), license=license, provenance=provenance
    ).benchmark


def _provenance(
    metadata: EvalMetadata | None, arxiv: ArxivEntry | None, *, version: str = "0.20.0"
) -> ProvenanceFacts:
    return ProvenanceFacts(metadata=metadata, arxiv=arxiv, inspect_evals_version=version)


def _mmlu_metadata(**overrides: Any) -> EvalMetadata:
    base: dict[str, Any] = {
        "package": "mmlu",
        "paper_url": "https://arxiv.org/abs/2009.03300",
        "inspect_contributors": ("jjallaire", "domdomegg"),
        "upstream_case_count": 14042,
        "human_baseline": (0.898, "https://arxiv.org/abs/2009.03300"),
        "safeguards": False,
    }
    base.update(overrides)
    return EvalMetadata(**base)


def test_the_generated_row_carries_everything_the_importer_could_read() -> None:
    arxiv = ArxivEntry(authors="Hendrycks et al., 2020", citation=_ARXIV_BIBTEX.strip())

    row = _row("mit", _provenance(_mmlu_metadata(), arxiv))

    ast.parse(f"BENCHMARKS = (\n{row})")
    assert 'paper_url="https://arxiv.org/abs/2009.03300",' in row
    assert 'authors="Hendrycks et al., 2020",' in row
    assert '"@misc{hendrycks2020measuring,' in row
    assert 'inspect_contributors=("jjallaire", "domdomegg"),' in row
    assert (
        'harness_url="https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0'
        '/src/inspect_evals/mmlu",' in row
    )
    assert 'license="MIT",' in row
    assert (
        'human_baseline=HumanBaseline(score=0.898, source_url="https://arxiv.org/abs/2009.03300"),'
        in row
    )
    assert 'notebook="12_inspect_evals_benchmarks",' in row
    assert "upstream_case_count=14042," in row
    # Only a human can say what the best published score is. No "who typed this row" field:
    # git holds that, and the importer must not generate a TODO nobody needs (2026-10-06).
    assert 'frontier_score=NotPublished(reason="TODO"),' in row
    assert 'contributors=("TODO",)' not in row
    assert "content_warning" not in row


def test_a_safeguards_eval_gets_a_content_warning_todo() -> None:
    row = _row(
        "mit",
        _provenance(
            _mmlu_metadata(package="agentharm", safeguards=True, human_baseline=None), None
        ),
        key="agentharm",
        task_ref="inspect_evals.agentharm.agentharm:agentharm",
    )

    assert "# TODO(review): inspect files this eval under Safeguards" in row
    assert 'content_warning="TODO",' in row
    assert 'human_baseline=NotPublished(reason="TODO"),' in row


def test_without_metadata_or_arxiv_every_field_is_a_todo_the_review_resolves() -> None:
    # F1 + F8 together: nothing is invented; every gap is a literal TODO that registration
    # refuses by name, so an unreviewed row cannot ship. "TODO" is the licence the importer
    # writes when the card names none (LICENSE_TODO).
    row = _row("TODO", _provenance(None, None), key="sums", task_ref="acme.sums:sums")

    ast.parse(f"BENCHMARKS = (\n{row})")
    assert 'paper_url="TODO",' in row
    assert 'authors="TODO",' in row
    assert 'citation="TODO",' in row
    assert "inspect_contributors" not in row
    assert 'harness_url="TODO",' in row
    assert 'license="TODO",' in row
    assert "upstream_case_count" not in row


def test_a_row_rendered_without_provenance_facts_is_unchanged_from_before() -> None:
    # The keyword is optional so every existing caller and test keeps its output.
    row = _row("mit", None, key="sums", task_ref="acme.sums:sums")

    assert "paper_url" not in row


def test_the_hub_licence_becomes_its_spdx_spelling() -> None:
    row = _row("cc-by-4.0", _provenance(None, None))

    assert 'license="CC-BY-4.0",' in row


@pytest.mark.parametrize("card_says", ["other", "unknown", "cc-by-nc-4.0", "gpl-3.0"])
def test_a_hub_licence_outside_the_cleared_list_is_the_owners_todo_not_a_served_value(
    card_says: str,
) -> None:
    # INVARIANT (OME-1273 D13): a card licence the owner has not cleared never registers as
    # the Benchmark's licence, whatever the importer was handed (review on PR 1236).
    row = _row(card_says, _provenance(None, None))

    assert 'license="TODO",' in row
    assert "not on the" in row and "cleared list" in row
    assert f'license="{card_says}"' not in row


def test_a_long_bibtex_line_is_split_so_every_generated_line_passes_the_lint_gate() -> None:
    # WHY: the first real import (OME-1455 PR 3) hit E501 on seven-author `author={...}` lines;
    # adjacent literals concatenate, so the citation the row carries is byte-identical.
    long_author_line = (
        "      author={" + " and ".join(f"Author Number{n}" for n in range(12)) + "},"
    )
    arxiv = ArxivEntry(
        authors="Number0 et al., 2026", citation=f"@misc{{x,\n{long_author_line}\n}}"
    )
    row = _row("mit", _provenance(None, arxiv))

    assert all(len(line) <= 100 for line in row.splitlines())
    citation_start = row.index("citation=(")
    citation_src = row[citation_start + len("citation=") : row.index("),", citation_start) + 1]
    assert eval(citation_src) == arxiv.citation  # noqa: S307 — generated text, parsed as the row is


def test_generated_text_from_arxiv_cannot_escape_the_string_literal() -> None:
    # Lane 4: arXiv-controlled text lands in generated Python; a quote in an author name
    # must stay inside the literal.
    arxiv = ArxivEntry(authors='O"Brien et al., 2020', citation='@misc{x, title={"q"}}')

    row = _row("mit", _provenance(_mmlu_metadata(), arxiv))

    tree = ast.parse(f"BENCHMARKS = (\n{row})")
    assert isinstance(tree, ast.Module)
