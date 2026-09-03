"""The console script: `report-intake` serves, `report-intake queue …` drains.

**`report-intake` with no arguments must go on running uvicorn, exactly as before.** It is the
container's `ENTRYPOINT` (see the Dockerfile), so that is deployment behaviour and not a default
anyone is free to change: a subcommand made mandatory here is every pod in the fleet failing to
start. `add_subparsers` is left optional and the top-level parser carries `run=_serve`, so the
argument-free invocation reaches the same two lines it always did.

The parser lives here rather than in `queue_cli.py` because the argument surface *is* the
entrypoint's contract, and this is the module that owns it. What the commands DO lives in
`queue_cli.py`, which the container reaches only through `kubectl exec` — never over HTTP (spec
§1 removed `GET /v1/reports/{ref}` and the drain path must not reinstate it).

A DELIBERATE DEPARTURE FROM THIS REPO'S PRECEDENT, recorded here because departing quietly is
how a convention becomes folklore. `apps/scoreboard` keeps `cli:main` a bare uvicorn launcher and
ships its operator commands as separate modules invoked as `python -m scoreboard.seed` /
`python -m scoreboard.retire_benchmark` — its chart README and its seed Job both spell them that
way. That shape makes the failure this docstring opens with — a subcommand made mandatory, and
every pod in the fleet failing to start — structurally impossible instead of a property defended
by an `add_subparsers()` left optional. Three things bought the divergence: plan §13's
verification step is written as `queue list` rather than as a module path, `kubectl exec … --
report-intake queue list` is what an operator on a triage call actually types (the image's
`ENTRYPOINT` is already this script, so `python -m` is the longer spelling of the same thing
here), and the entrypoint property is pinned by two tests rather than by a comment —
`test_a_queue_command_never_starts_the_server` and
`test_the_entrypoint_still_serves_when_given_no_arguments_at_all`. If
either of those is ever deleted, take the scoreboard shape instead; they are what the extra risk
was traded for. `docs/work/2026-08-26-OME-1002-review-fixes.md` carries the decision.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence

import uvicorn

from . import queue_cli
from .config import Settings


def main(argv: Sequence[str] | None = None) -> int:
    """Parse and run. Returns the process's exit code, which the console-script wrapper exits on.

    `argv` is a parameter only so a test can pass one; nothing in the image supplies it, and
    argparse falls back to `sys.argv[1:]` exactly as it would.
    """
    args = _parser().parse_args(argv)
    command: Callable[[argparse.Namespace], int] = args.run
    return command(args)


def _serve(args: argparse.Namespace) -> int:
    settings = Settings()
    # `log_level` reaches the app's own logger through create_app's logs.configure(); this
    # argument governs uvicorn's loggers, which are a separate tree.
    uvicorn.run(
        "report_intake.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )
    return queue_cli.EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="report-intake",
        description="Serve the report-intake API, or drain the queue of reports awaiting triage.",
    )
    # THE DEFAULT IS THE CONTRACT: no subcommand means serve. See the module docstring.
    parser.set_defaults(run=_serve)
    commands = parser.add_subparsers(metavar="<command>")

    queue = commands.add_parser(
        "queue",
        help="the reports QueueSink marked ready for an agent to file",
        description=(
            "Read and drain the triage queue. The `reports` table IS the queue (spec §9): a row "
            "marked `queued` is one an agent files into Linear through MCP."
        ),
    )
    # `required=True` HERE and deliberately not on `commands` above: a bare `report-intake queue`
    # has no sensible fallback, whereas a bare `report-intake` has the one the Dockerfile depends
    # on.
    actions = queue.add_subparsers(metavar="<subcommand>", required=True)

    listing = actions.add_parser("list", help="the reports awaiting triage, newest first")
    listing.add_argument(
        "--limit",
        type=queue_cli.positive,
        default=queue_cli.DEFAULT_LIMIT,
        help=f"how many reports to show (default: {queue_cli.DEFAULT_LIMIT})",
    )
    listing.set_defaults(run=queue_cli.list_queued)

    show = actions.add_parser("show", help="the ticket body to file for one report")
    show.add_argument("ref", help="the report's server-minted ref, as `queue list` prints it")
    show.set_defaults(run=queue_cli.show)

    filed = actions.add_parser("mark-filed", help="record that this report has been filed")
    filed.add_argument("ref", help="the report's server-minted ref")
    filed.add_argument("--ticket-id", required=True, metavar="OME-N", help="the issue identifier")
    filed.add_argument("--ticket-url", required=True, metavar="URL", help="the issue's url")
    filed.set_defaults(run=queue_cli.mark_filed)

    return parser


if __name__ == "__main__":
    raise SystemExit(main())
