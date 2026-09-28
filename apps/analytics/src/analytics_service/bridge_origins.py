"""Observed Colab output-host grammar; not a wildcard for Google-hosted content."""

import re

COLAB_TOP = "https://colab.research.google.com"
# WHY: shared with the browser script; full canonical origins exclude ports and paths.
COLAB_PATTERN = r"https://[a-z0-9]+-[0-9a-f]{16}-[0-9]+-colab\.googleusercontent\.com"


def is_colab_origin(origin: str) -> bool:
    return len(origin.removeprefix("https://").split(".")[0]) <= 63 and bool(
        re.fullmatch(COLAB_PATTERN, origin)
    )
