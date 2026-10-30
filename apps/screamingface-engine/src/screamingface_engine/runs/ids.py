"""The Run id (E5 P1 spec D5): `run_` + a random UUID in hex.

FEATURE: first-class Runs (OME-1785). The id is not a secret; access is checked by owner. It
carries no order: Runs list by `created_at`, with the id breaking ties, so any number of App
replicas can mint ids without a shared clock.
"""

from __future__ import annotations

import re
import uuid

# INVARIANT: the one definition of the id form; validators import it rather than restate it.
# WHY anchored: a caller may use `match`, `search` or a Pydantic `pattern` (a search), not only
# `fullmatch`. `^`/`$` rather than `\A`/`\Z` so the same text also works as a Pydantic pattern.
RUN_ID_PATTERN = re.compile(r"^run_[0-9a-f]{32}$")


def new_run_id() -> str:
    """A fresh Run id."""
    return f"run_{uuid.uuid4().hex}"
