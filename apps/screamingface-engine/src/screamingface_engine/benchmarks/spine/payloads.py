"""Kind-tagged Case payloads — the envelope a case input or candidate answer travels in.

Think of a payload as a labelled envelope: the ``kind`` tag on the front says what shape
is inside, and only the board's ``grade_case`` hook opens it. The spine carries the
envelope from row decode to the hook without looking inside, so "a candidate's answer is
text" is a fact about ONE kind, never about the pipeline.

FEATURE: one grading spine per benchmark (OME-1024). OME-1096 kept the decoded row
opaque and deferred the payload types to this seam (OME-1097); this module is where they
land.

INVARIANT: the hook's input and answer fields are payload-typed, never bare ``str`` — the
constraint the epic's three consumers force (enclave judge, inspect_evals shim, agentic
boards whose answer is a patch + action log).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class TextPayload:
    """A plain text input or answer — the only payload kind implemented today."""

    text: str
    kind: Literal["text"] = "text"


# AIDEV-NOTE: CasePayload can grow more kinds — decided in OME-1103, e.g.:
#   TextPayload                 kind="text"              a plain prompt/answer string (today)
#   TextAttachmentsPayload      kind="text+attachments"  text plus files (images, PDFs)
#   EnvironmentPayload          kind="environment"       an agentic outcome: patch + action log
# Adding one = a new dataclass + widening this union; the spine never opens the
# envelope, so a new kind is an addition, never a spine rewrite.
CasePayload = TextPayload

__all__ = ["CasePayload", "TextPayload"]
