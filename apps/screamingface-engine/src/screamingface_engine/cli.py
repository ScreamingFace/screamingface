"""``screamingface-engine`` console entrypoint — one image, three modes.

    screamingface-engine serve    # the control plane: mint tokens, bridge WS, schedule Runner Jobs
    screamingface-engine run      # one url4 evaluation, streamed to NATS, then exit
    screamingface-engine worker   # claim runs from the durable queue, supervise each as a child

WHY one artifact with a mode argument rather than two images: the two halves already shared
their whole wire vocabulary (`job_env`, `subjects`, the JetStream binding), and keeping them in
separate distributions meant maintaining hand-synced duplicates of all three plus contract tests
whose only job was to catch the copies drifting. The run mode's dependencies are a strict subset
of the serving mode's, so merging cost no new dependency — only the serving-side packages now
sitting unused on a Job's disk. The worker mode (OME-1089) is the third mode: it imports the
serving half and the queue, and spawns the run as a child process rather than importing it.

INVARIANT: the mode is chosen by ARGV, never sniffed from the environment.
The worker pool's Deployment pins `["screamingface-engine", "worker"]` and the run
mode is entered by the worker's child processes, so a pod that is missing its env fails
loudly at boot instead of silently booting a web server that nothing will ever dial.

``serve`` is the default when no subcommand is given, which is what keeps the
image's ``CMD ["screamingface-engine"]`` and the chart's
``command: [screamingface-engine]`` working unchanged.
"""

import argparse

from screamingface_engine.logs import configure as configure_logging

_PORT = 9108


def _serve() -> None:
    """Serve the env-wired control plane with uvicorn."""
    import uvicorn  # WHY: lazy — cold-start discipline, and unit tests never reach a real server

    # INVARIANT: the deployed entrypoint serves the ENV-WIRED factory. The bare `create_app` is
    # the dependency-injected one tests use — calling it here would build
    # stream=None/job_runner=None and skip `_require_prod_secret`, i.e. an App that cannot stream,
    # cannot schedule, and would boot on the insecure default secret.
    #
    # INVARIANT: _PORT here IS the chart's `containerPort` (deploy/helm/templates/deployment.yaml),
    # and it is hardcoded on BOTH sides on purpose. This path reads no port from the environment,
    # so a chart value for it could only ever point the probes and the Service's `targetPort` at a
    # port nothing listens on — which is exactly what `config.port` did before it was removed.
    # Changing this means changing the containerPort in the same commit.
    # INVARIANT (OME-890): uvicorn's WS ping defaults are LOAD-BEARING and deliberately not
    # overridden. `ws_ping_interval=20` / `ws_ping_timeout=20` are what close a partitioned or
    # sleeping peer's socket within ~40s, which is what fires `ConnectionRegistry.remove` and so
    # arms the orphan reaper. Disable or lengthen them and a dead client's run is detected only by
    # TCP retransmission timeout (~15-30 min), which silently reopens most of the spend the
    # reaper closed. Measured on uvicorn 0.52.1; re-check on a major bump.
    uvicorn.run(
        "screamingface_engine.app:create_app_from_env", factory=True, host="0.0.0.0", port=_PORT
    )


def _serve_local() -> None:
    """Serve the fused local-mode App — in-process runner, in-memory stream, loopback only.

    A sibling of :func:`_serve` rather than a flag on it: the two share only the word "serve".
    They resolve different factories, bind different addresses, and differ on whether the
    insecure default JWT secret is tolerated — a boolean parameter switching all of that would
    be a second function wearing the first one's name.
    """
    import uvicorn  # WHY: lazy — same cold-start discipline as `_serve`

    # INVARIANT: loopback only — see `local.LOCAL_HOST`. Local mode accepts the insecure default
    # JWT secret, so the bind address is the only thing keeping it unreachable.
    from screamingface_engine.local import LOCAL_HOST

    # INVARIANT: the WS ping defaults matter here too — see the note in `_serve` (OME-890).
    uvicorn.run(
        "screamingface_engine.local:create_local_app", factory=True, host=LOCAL_HOST, port=_PORT
    )


def _run() -> None:
    """Execute one url4 run from the Job's environment, then exit."""
    # WHY: lazy, and the reason the layering rule earns its keep — importing the run path must
    # not drag in FastAPI/uvicorn/kubernetes, and importing `serve` must not drag in the engine.
    from screamingface_engine.runner.main import main as run_main

    run_main()


def _worker() -> None:
    """Claim runs from the durable queue and supervise each as a child process."""
    # WHY: lazy, like the other modes — the worker's import graph is the serving half's plus
    # the queue, and a mode that is not running must not pay for it.
    from screamingface_engine.worker.loop import run_worker

    run_worker()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="screamingface-engine",
        description="screamingface-engine — the control plane, or one url4 run.",
    )
    # WHY not `required=True`: bare `screamingface-engine` must keep meaning `serve`,
    # since that is the image CMD and the chart's Deployment command.
    # WHY a top-level default: bare `screamingface-engine` parses no subparser, so
    # `args.local` would not exist at all without one.
    parser.set_defaults(local=False)
    sub = parser.add_subparsers(dest="mode")
    serve_parser = sub.add_parser(
        "serve", help="serve the REST + WebSocket control plane (default)"
    )
    serve_parser.add_argument(
        "--local",
        action="store_true",
        help=(
            "run the whole protocol in one process — runs execute as asyncio tasks and frames "
            "travel an in-memory stream, so neither Kubernetes nor NATS is needed. Binds "
            "loopback only."
        ),
    )
    sub.add_parser("run", help="execute one url4 expression from the environment, then exit")
    sub.add_parser(
        "worker",
        help=(
            "claim runs from the durable run queue and supervise each as a child process "
            "(the fixed worker pool of OME-1086)"
        ),
    )
    args = parser.parse_args(argv)

    # BEFORE dispatch, and for every mode: a Job's logs are as load-bearing as the control
    # plane's, and neither `uvicorn.run` nor `run_main` configures anything for this package.
    configure_logging()

    if args.mode == "worker":
        _worker()
    elif args.mode == "run":
        _run()
    elif args.local:
        _serve_local()
    else:
        _serve()
