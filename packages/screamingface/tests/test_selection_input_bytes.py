"""The Case input in the Rank and Filter envelope changes no compiled url4 (E4b unit 1, SI-4).

CHAR (SI#2): passes before and after unit 1. The engine adds ``input`` to the ``top_k@1`` and
``kept@1`` output (option C, P4); the SDK compile does not change, so a selection Pipeline keeps
its url4 bytes and its replay identity.
INVARIANT defended: the two frozen selection url4 files keep their bytes (SHA-256 below, taken
from the files at e4b-combine-extensions 0b848c219), and the compiler still writes them.
"""

from __future__ import annotations

import hashlib

from _combine_contract import COMBINE_CONTRACT, requires_engine_app
from _fusion_doc_examples import EXAMPLES, compile_example
from test_engine_url4_contract_fixtures import filter_pipeline_url4
from test_fusion_doc_goldens import golden_path

_RANKED_SHA256 = "4f289c7e95eca78454c6ea43cc69b67962443d6869abdc8fe6be0002b79ff726"
_FILTER_SHA256 = "3d18d28af07dbe0286471f2b64ffbb3f9d6299bff85692eec0beef7c33ec1b7f"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@requires_engine_app
def test_selection_pipeline_url4_bytes_are_unchanged() -> None:
    ranked = next(example for example in EXAMPLES if example.slug == "readme-514-ranked")
    ranked_file = golden_path(ranked).read_bytes()
    filter_file = (COMBINE_CONTRACT / "filter_pipeline_candidate.url4").read_bytes()

    assert _sha256(ranked_file) == _RANKED_SHA256
    assert _sha256(filter_file) == _FILTER_SHA256
    # WHY + b"\n": the end-of-file-fixer hook appends one newline; the compiler writes none.
    assert compile_example(ranked).encode("utf-8") + b"\n" == ranked_file
    assert filter_pipeline_url4().encode("utf-8") + b"\n" == filter_file
