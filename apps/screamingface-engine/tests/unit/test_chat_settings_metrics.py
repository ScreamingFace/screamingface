"""The chat settings and the two chat metric series (prd/chat-completion.md §3.4, §4)."""

from screamingface_engine.config import Settings
from screamingface_engine.metrics import build_metrics


def test_chat_max_wait_defaults_to_600_s():
    assert Settings(jwt_secret="x" * 32).chat_max_wait_s == 600.0


def test_chat_max_wait_reads_its_env_name(monkeypatch):
    monkeypatch.setenv("URL4_CLOUD_CHAT_MAX_WAIT_S", "12.5")
    assert Settings(jwt_secret="x" * 32).chat_max_wait_s == 12.5


def test_build_metrics_has_the_two_chat_series():
    m = build_metrics()
    assert m.chat_requests is not None
    assert m.chat_request_duration is not None
    m.chat_requests.labels(outcome="ok").inc()
    m.chat_request_duration.observe(1.2)
    assert (
        m.registry.get_sample_value("screamingface_engine_chat_requests_total", {"outcome": "ok"})
        == 1.0
    )
    assert (
        m.registry.get_sample_value("screamingface_engine_chat_request_duration_seconds_count")
        == 1.0
    )
    assert (
        m.registry.get_sample_value(
            "screamingface_engine_chat_request_duration_seconds_bucket", {"le": "600.0"}
        )
        == 1.0
    )
