"""Composition registry for optional execution observers; no execution logic."""

from collections.abc import Mapping
from functools import partial

from screamingface_engine import job_env
from screamingface_engine.activity.contract import ActivityLevel
from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.observations import ObserverFactory


def observation_factories(env: Mapping[str, str]) -> tuple[ObserverFactory, ...]:
    level = ActivityLevel(env.get(job_env.ACTIVITY_LEVEL, "full"))
    return (partial(ActivityObserver, enabled=level == ActivityLevel.FULL),)
