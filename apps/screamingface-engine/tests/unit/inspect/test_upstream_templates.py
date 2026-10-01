# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Choice templates upstream builds at run time, kept as constants our declarations point at.

INVARIANT: each constant IS the template the eval's own solver holds. An inspect_evals bump
that changes the wording fails here, before an image build seals Cases with stale wording.
No network: agieval builds its solver without fetching anything.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_evals")

from inspect_ai._util.registry import registry_params  # noqa: E402
from inspect_evals.agieval.utils import agieval_solver  # noqa: E402

from screamingface_engine_inspect.upstream_templates import AGIEVAL_MCQ_TEMPLATE_EN  # noqa: E402

#: The English multiple-choice agieval datasets the stack imports (OME-1273 PR 4).
AGIEVAL_ENGLISH_MCQ: tuple[str, ...] = (
    "lsat-ar",
    "lsat-lr",
    "lsat-rc",
    "sat-math",
    "sat-en",
    "sat-en-without-passage",
    "aqua-rat",
    "logiqa-en",
)


@pytest.mark.parametrize("dataset_name", AGIEVAL_ENGLISH_MCQ)
def test_the_agieval_constant_is_the_template_agieval_builds(dataset_name: str) -> None:
    """The defaults our imports use: no chain-of-thought, no few-shot examples."""

    solver = agieval_solver(dataset_name=dataset_name, cot=False, fewshot_samples=None)

    assert registry_params(solver)["template"] == AGIEVAL_MCQ_TEMPLATE_EN
