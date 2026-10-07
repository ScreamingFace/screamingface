"""What the MuSiQue-Ans benchmark pins — the Case Source, the preparer, the protocol, the scorer.

INVARIANT: the IDENTITY pins below participate in the benchmark's revision hash (wired in the
benchmark definition): dataset, dataset revision, dataset file and its sha256, preparer
revision, protocol revision, scorer revision. Changing one changes every route address, which is
the point: an expression addressed to an old revision must never resolve against changed Cases
or a changed scorer.

`MAX_TOKENS` is OUTSIDE the revision hash: it is advisory, never applied by this benchmark (see
its note below).

References:
    - Paper: Trivedi et al., "MuSiQue: Multihop Questions via Single-hop Question Composition",
      TACL 2022 — https://aclanthology.org/2022.tacl-1.31/
    - Reference harness: https://github.com/StonyBrookNLP/musique (CC BY 4.0)
      @ 922ac98f19a201998dbdae6d7f2887a5258dbdeb
    - Case Source: https://huggingface.co/datasets/dgslibisey/MuSiQue (a community mirror whose
      dev file is byte-identical to the official Google Drive zip's)
"""

from __future__ import annotations

DATASET = "dgslibisey/MuSiQue"
# WHY a community mirror and not the authors' copy: the authors publish only a Google Drive zip,
# and image builds that download from Google Drive fail on its rate limits. The mirror's dev file
# was compared with `cmp` against the official zip's and is byte-identical; DATASET_SHA256 below
# is what keeps it that way (spec D2).
DATASET_REVISION = "c8f4f8c9465fb69d31a8eae894c3fd509c4ca321"
DATASET_FILE = "musique_ans_v1.0_dev.jsonl"
# INVARIANT: Case Preparation refuses any bytes whose sha256 is not this one, BEFORE parsing. A
# commit pin alone trusts the host; this hash is what proves the Cases are the ones reviewed.
DATASET_SHA256 = "15fa63794d18a94ce12411aca6e2327e65b6e83b0b1490efab3f1962e48abf3b"

#: The dev split's Case count — all 2,417 answerable (the test split's answers are withheld).
#: Asserted at prepare time, so a resized file fails the build instead of serving a benchmark
#: whose declared `case_count` it does not hold.
EXPECTED_CASES = 2417

# WHY: prepare's emission rules (which file, how a Case renders, what the Grading Material holds)
# are part of the answer key; bump when they change.
PREPARER_REVISION = "ans-dev-v1"
# WHY: the exchange itself — one Candidate call, the reply ending with the two committed lines
# `Supporting paragraphs:` and `Answer:`, read by `answering.extract_reply`.
PROTOCOL_REVISION = "answer-support-lines-v1"
# WHY: the code that turns a reply into numbers is copied from this commit (`vendor/`); a
# different scorer is a different benchmark even over the same Cases.
SCORER_REVISION = "StonyBrookNLP/musique@922ac98f19a201998dbdae6d7f2887a5258dbdeb"

# AIDEV-NOTE: ADVISORY — not applied by this benchmark and not in the revision hash. Sampling
# parameters reach a model from the SDK caller's `sf.Model(params=...)`, so this records a
# sensible budget for whoever writes a notebook or a run script (spec D10). Do not "wire it up"
# without deciding what it means for a Fusion, whose members may each need different parameters.
#
# WHY 4096: the committed answer is short (2 words at the median, 14 at most), but the prompt
# invites the model to reason first, and a reasoning model that runs out of budget before the two
# closing lines scores as if it never answered.
MAX_TOKENS = 4096

__all__ = [
    "DATASET",
    "DATASET_FILE",
    "DATASET_REVISION",
    "DATASET_SHA256",
    "EXPECTED_CASES",
    "MAX_TOKENS",
    "PREPARER_REVISION",
    "PROTOCOL_REVISION",
    "SCORER_REVISION",
]
