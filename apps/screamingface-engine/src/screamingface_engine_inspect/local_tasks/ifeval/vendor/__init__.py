"""COPIED third-party code — the official IFEval checker. Do not edit.

What this is
    The files under `vendor/` are the copy of files from https://github.com/josejg/instruction_following_eval
    at commit 0c495b2f95155e8b10acb919ae283bfb4d5be6e2 (2025-01-16):
    ``instructions.py``, ``instructions_util.py``, ``instructions_registry.py``,
    ``evaluation.py`` (verdict core only — see its banner), and
    ``data/input_data.jsonl`` (the official 541-row dataset, byte-identical,
    sha256 67ffeee0fcb87c317c5b08a2de85557b4a7e96ada6178aa645b4954fe4b53d49).
    License: Apache-2.0 (the LICENSE file here is copied from the same repo).

Why a copy instead of pip
    The package is not on PyPI, and a Runner Job cannot reach GitHub at run time.
    This fork (not Google's original) is the one inspect_evals pins — the
    community-standard checker.

The ONLY changes we made
    1. A "VENDORED COPY" banner at the top of each file linking to its exact
       source file at the pinned commit.
    2. Two import lines rewritten from ``from instruction_following_eval
       import x`` to ``from . import x`` so the copy works inside this
       package (one in ``instructions.py``, one in ``instructions_registry.py``).
    Everything else is byte-identical to the fork.

Why ``evaluation.py`` and the dataset are vendored too (added with the
golden-parity work)
    Mental model: the fork is the exam board, and these two files let us
    cross-check our marking against it without touching the network. They have
    exactly two consumers:

    1. The parity proof. ``..grading`` reimplements the fork's scoring
       protocol; ``tests/unit/inspect/test_local_task_ifeval_parity.py`` proves the
       reimplementation equivalent by grading all 541 official rows
       (``data/input_data.jsonl``) twice — once with OUR grader, once with the
       fork's own ``test_instruction_following`` (``evaluation.py`` here) —
       and demanding identical verdict vectors. That proof is what makes our
       published IFEval scores comparable to everyone else's.
    2. The dataset authority. ``..ifeval.load_ifeval`` loads the rows from a
       pinned HuggingFace snapshot, then verifies each row against
       ``data/input_data.jsonl``. One known mismatch exists (key 2785's
       prompt); the official text here wins and gets patched in. Any other
       mismatch fails the build loudly.

    The Cases a Job serves still come from the HuggingFace pin — this copy is
    only the referee and the authority, never what candidates see.

INVARIANT: please do not edit these files. This checker IS the exam — changing it
changes every published IFEval score. Every ``.py`` byte here is hashed into the
Benchmark revision (the local Task's ``task_source`` pin), so an edit moves it;
an intentional update must also update the commit named above.

AIDEV-NOTE: never call the fork's nltk download helper. The Job is offline with
a read-only disk; tokenizer data comes from the prepared bundle's ``nltk_data/``,
which the Benchmark's installer points nltk at.
"""
