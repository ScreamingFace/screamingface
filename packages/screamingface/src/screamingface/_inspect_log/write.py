# pyright: reportMissingImports=false
# WHY the file-level escape: the repo's gates typecheck against an extra-less
# install (`uv sync --extra notebook`), so `inspect_ai` is deliberately absent —
# same pattern as the Engine's inspect shim. The import is guarded at runtime by
# `find_spec`, and everything outside the guarded block stays fully typed.
"""Hand one Report's payload to inspect's own `.eval` writer.

Mental model: a mail slot — the pure mapping (`payload.py`) writes the letter,
this module only checks the address (`.eval` suffix), checks the recipient
exists (the `inspect` extra), and posts it through `inspect_ai`'s writer so the
zip layout stays THEIR contract, not ours. One-way by construction: nothing in
this package reads a log back.
"""

from __future__ import annotations

from importlib.util import find_spec
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING

from screamingface._inspect_log.payload import eval_log_payload

if TYPE_CHECKING:
    from screamingface.report import Report


def write_inspect_log(
    report: Report,
    path: str | PathLike[str],
    *,
    candidate: str | None = None,
) -> Path:
    """Write one Candidate's run as an inspect `.eval` log and return its path.

    Stages: validate the `.eval` address → refuse without the `inspect` extra
    (naming the fix) → build the pure payload → let inspect's own
    ``EvalLog.model_validate`` + ``write_eval_log`` produce the file. Parent
    directories are created; an existing file is replaced (same convention as
    the JSON export).

    Args:
        report: the completed Report to export from.
        candidate: the Candidate name when the Report holds more than one.

    Returns:
        The selected path, now holding a log `inspect view` opens.
    """
    selected = Path(path)
    if selected.suffix.lower() != ".eval":
        raise ValueError("an inspect log export path must be a .eval file")
    if find_spec("inspect_ai") is None:
        raise ModuleNotFoundError(
            "exporting an inspect log needs the 'inspect' extra — "
            'pip install "screamingface[inspect]"'
        )
    payload = eval_log_payload(report, candidate=candidate)
    from inspect_ai.log import EvalLog, write_eval_log

    selected.parent.mkdir(parents=True, exist_ok=True)
    write_eval_log(EvalLog.model_validate(payload), str(selected))
    return selected
