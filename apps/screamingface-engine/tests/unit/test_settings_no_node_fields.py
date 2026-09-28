"""DEC-6: the App's settings carry no node-tier field (uniform executor PRD 05).

`node_base_url` armed the App's forwarder to the node tier; `node_forward_timeout_s` was its
budget. Both went with the tier: a mount call is a direct run on the worker pool.
"""

from screamingface_engine.config import Settings


def test_settings_have_no_node_fields() -> None:
    assert not {name for name in Settings.model_fields if name.startswith("node_")}
