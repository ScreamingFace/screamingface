"""HTTP software identity shared by catalogue and evaluation clients."""

from screamingface._version import resolve_version


def engine_headers() -> dict[str, str]:
    # WHY: identify the installed Client, without leaking machine or user details.
    return {"User-Agent": f"screamingface/{resolve_version()}"}
