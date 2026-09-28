from datetime import UTC, datetime
from uuid import uuid4

import pytest


@pytest.fixture
def envelope():
    return {
        "schema_version": 1,
        "consent_version": "1",
        "consent_granted": True,
        "events": [
            {
                "event_id": str(uuid4()),
                "operation_id": str(uuid4()),
                "session_id": str(uuid4()),
                "persistent_id": str(uuid4()),
                "id_scope": "installation",
                "event": "evaluation_started",
                "timestamp": datetime.now(UTC)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
                "sdk_version": "0.1.0",
                "surface": "python_sdk",
                "interface": "sync",
                "origin": "python",
                "usage_mode": "hosted",
                "workflow": "recipe",
            }
        ],
    }
