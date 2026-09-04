"""The worker half (OME-1089): a slot pool that claims runs from the durable run queue
and forks the existing run entrypoint as a supervised child process, so the crash domain
stays one run and ``runner/main.py`` is untouched.

LAYERING: the worker may import the serving half and ``runner_queue``, and must import
NOTHING from the run half (no ``runner/``, no ``url4.streaming.lifecycle``) — it spawns
the run as a child process, it never imports it. The layering gate names this half
explicitly (see ``.claude/scripts/check_layering.py``).
"""

from screamingface_engine.worker.loop import PULL_TIMEOUT_S, Worker, run_worker

__all__ = ["PULL_TIMEOUT_S", "Worker", "run_worker"]
