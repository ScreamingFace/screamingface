"""RR-22 of prd/review-round-2.md (RR-S16): the Engine CI runs on the SDK files its chat tests read.

FEATURE: OpenAI-compatible Engine API, review round 2, unit U-F2 (RR-S16). The two SDK files
are read by tests/unit/test_chat_recipe_check.py and tests/unit/_chat_corpus.py. A path that is
missing from a `paths:` list of the Engine workflow lets a change to it skip the chat tests.

STORY: as a maintainer, I change the SDK surface parity data or the operation bindings, and the
Engine CI runs the chat tests that read them, so a break shows on the pull request.
WHY: the text of the workflow is read, not parsed: PyYAML reads the key `on` as True.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
WORKFLOW = REPO / ".github/workflows/screamingface-engine-tests.yml"
SDK_FILES = (
    "packages/screamingface/tests/data/surface_parity.json",
    "packages/screamingface/src/screamingface/_operation_bindings.py",
)


def test_engine_ci_paths_cover_the_sdk_files_the_chat_tests_read() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    push_start = text.index("\n  push:\n")
    pull_start = text.index("\n  pull_request:\n")
    dispatch_start = text.index("\n  workflow_dispatch:")
    push = text[push_start:pull_start]
    pull = text[pull_start:dispatch_start]

    for section in (push, pull):
        for path in SDK_FILES:
            assert f'- "{path}"' in section, path

    for path in SDK_FILES:
        assert (REPO / path).is_file(), path
