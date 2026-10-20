"""The community request cache, pulled into a local engine (epic OME-1311).

`pull_from_remote()` copies the hosted community cache into the local gateway's database, so a
local run answers from it for free the calls the community has already made. The local gateway
caches by default; `evaluate(..., use_cache=False)` opts one run out.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from screamingface.errors import ScreamingFaceError


@dataclass(frozen=True, slots=True)
class PullResult:
    """What one `pull_from_remote` call did.

    `rows_read` counts the rows of completed pages; `rows_added` the rows that were new to the
    local cache (a row it already held is kept and not counted). `rows_skipped` counts the rows
    of completed pages the local gateway could not serve, which were not loaded. `resumed` is true
    when the call continued a pull this process had started; `complete` when it reached the last
    page.
    """

    rows_read: int
    rows_added: int
    pages: int
    resumed: bool
    complete: bool
    rows_skipped: int = 0


class CachePullError(ScreamingFaceError):
    """A pull stopped before its last page. `result` says how far it got.

    Pages already loaded stay loaded: every row is an independent cache entry. Calling
    `pull_from_remote` again in the same process with the same `url` and `models` continues from
    the last loaded page.
    """

    _default_code: str = "community_cache_pull_failed"

    def __init__(
        self, message: str, *, result: PullResult, code: str | None = None, hint: str | None = None
    ) -> None:
        super().__init__(message, code=code, hint=hint)
        self.result: PullResult = result


def pull_from_remote(
    models: Sequence[str] | None = None,
    *,
    url: str | None = None,
    progress: bool | None = None,
) -> PullResult:
    """Pull the hosted community cache into the local gateway.

    `models` limits the pull to those models, exactly as the hosted cache names them (for
    example `"openrouter/anthropic/claude-opus-5.5"`); a run can only hit rows of the models its
    candidates and judge use, so a filtered pull loses no hits. `None` pulls everything.

    `url` is the hosted Engine to pull from; `None` is the production Engine. It never follows
    the Engine your runs use: when `screamingface up` is running that is the local Engine — where
    the rows are going, not where they come from.

    The first page opens the Engine's sign-in in a browser unless this process is already
    signed in. The rows land in the local gateway database (`screamingface up` must have run once
    to create it), which needs `screamingface[runtime]`. That database is the one in
    `SCREAMINGFACE_DATA_DIR` (default `~/.screamingface`) — the same stack `sf.connect()` finds.
    For a stack started with `screamingface up --data-dir DIR`, set `SCREAMINGFACE_DATA_DIR=DIR`
    or run `screamingface cache pull --data-dir DIR`. `progress=None` shows progress in a
    notebook or an interactive terminal; `True` / `False` force it on or off.

    A dropped connection or a busy Engine is retried. If the pull still stops, `CachePullError`
    says why and how far it got, and calling again in the same process continues from there; a
    pull whose process ended starts over, which costs only time — rows already loaded are kept.
    """
    from screamingface._cache.pull import pull_into
    from screamingface._runtime.config import default_data_dir

    return pull_into(_models(models), url=url, data_dir=default_data_dir(), progress=progress)


def _models(models: Sequence[str] | None) -> tuple[str, ...]:
    if models is None:
        return ()
    if isinstance(models, str):
        raise TypeError("models must be a sequence of model names, not one string")
    names = tuple(models)
    if not all(isinstance(name, str) and name for name in names):
        raise TypeError("models must be non-empty strings")
    return tuple(sorted(set(names)))


__all__ = ["CachePullError", "PullResult", "pull_from_remote"]
