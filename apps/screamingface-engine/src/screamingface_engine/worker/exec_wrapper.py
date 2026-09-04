"""The exec wrapper that puts each run under its own ``RLIMIT_AS`` (OME-1089).

The worker forks the run entrypoint as a child process, and each child must be spawned
under its own address-space limit so an over-allocating run fails alone instead of
triggering a Pod OOM that kills its co-tenants — which would void the reason for
choosing subprocess isolation in the first place.

WHY a wrapper and not ``preexec_fn``: CPython documents ``preexec_fn`` as unsafe in the
presence of threads, and this process runs an event loop plus whatever the NATS client
starts. The wrapper is a separate tiny process: it sets the limit, then execs
``screamingface-engine run`` in place, so the run inherits the limit and the worker
never touches the child's memory.

The wrapper imports nothing but the stdlib, so it stays importable even if the rest of
the worker's import graph is broken.
"""

import os
import resource
import sys


def main() -> None:
    budget = int(sys.argv[1])
    resource.setrlimit(resource.RLIMIT_AS, (budget, budget))
    os.execvpe("screamingface-engine", ["screamingface-engine", "run"], os.environ)


if __name__ == "__main__":  # pragma: no cover - execs in place; nothing to return to
    main()
