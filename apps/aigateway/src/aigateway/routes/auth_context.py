"""Shared app-state accessors for the auth routes.

Every auth-facing module reaches the profile index, the provider registry, the
credential store and the pending-auth table the same way. They live here so the route
modules can share them without importing each other — this module imports nothing from
``routes`` and is the base of that graph.
"""

from __future__ import annotations

import logging

from fastapi import Request

from ..core.profile_index import (
    ProfileIndexStore,
)

logger = logging.getLogger(__name__)


def _index_store(request: Request) -> ProfileIndexStore:
    return _index_store_for_app(request.app)


def _index_store_for_app(app) -> ProfileIndexStore:
    return app.state.profile_index


def _registry(request: Request):
    return _registry_for_app(request.app)


def _registry_for_app(app):
    return app.state.providers


def _credential_store_for_app(app):
    return app.state.credential_store


def _pending(request: Request):
    return _pending_for_app(request.app)


def _pending_for_app(app):
    return app.state.pending_auth
