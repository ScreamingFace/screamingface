from collections.abc import Sequence
from dataclasses import dataclass

from screamingface_engine.adapters.k8s import _LimitRangeView


@dataclass(frozen=True)
class FakeObjectMeta:
    uid: str


@dataclass(frozen=True)
class FakeCreatedJob:
    metadata: FakeObjectMeta


def fake_created_job(uid: str) -> FakeCreatedJob:
    return FakeCreatedJob(metadata=FakeObjectMeta(uid=uid))


# --- quota/limitrange fakes for the admission tests (OME-1065) ------------------------------


@dataclass
class FakeQuotaStatus:
    used: dict[str, str] | None = None
    hard: dict[str, str] | None = None


@dataclass
class FakeQuota:
    status: FakeQuotaStatus | None = None


@dataclass
class FakeQuotaList:
    items: list[FakeQuota]


@dataclass
class FakeLimitRangeItem:
    """Mirrors `kubernetes.client.V1LimitRangeItem`'s Python attribute names (snake_case),
    NOT the k8s API's JSON wire names — see the `WHY` on `_LimitRangeItem` in
    `adapters/k8s.py` (OME-1083). A field spelled after the wire name here would agree with a
    matching bug in the adapter and never catch the mismatch against the real client.
    """

    type: str
    default: dict[str, str] | None = None
    default_request: dict[str, str] | None = None


@dataclass
class FakeLimitRangeSpec:
    limits: list[FakeLimitRangeItem] | None = None


@dataclass
class FakeLimitRange:
    spec: FakeLimitRangeSpec | None = None


@dataclass
class FakeLimitRangeList:
    items: Sequence[_LimitRangeView]


class FakeCoreV1:
    """The quota/limitrange read surface for the admission tests.

    A subclass can raise ApiException from either read to exercise the degradation path.

    ``limitranges`` accepts anything structurally shaped like `_LimitRangeView` — a
    `FakeLimitRange`, or a REAL `kubernetes.client.V1LimitRange` (OME-1083's regression test
    passes the real client type directly, precisely to catch a Protocol/real-client mismatch
    the hand-rolled fakes agreed with by construction).
    """

    def __init__(
        self,
        quotas: list[FakeQuota] | None = None,
        limitranges: Sequence[_LimitRangeView] | None = None,
    ) -> None:
        self.quotas = quotas or []
        self.limitranges: Sequence[_LimitRangeView] = limitranges or []
        self.quota_reads = 0
        self.limitrange_reads = 0

    def list_namespaced_resource_quota(
        self, namespace: str, *, _request_timeout: float | None = None
    ) -> FakeQuotaList:
        self.quota_reads += 1
        return FakeQuotaList(self.quotas)

    def list_namespaced_limit_range(
        self, namespace: str, *, _request_timeout: float | None = None
    ) -> FakeLimitRangeList:
        self.limitrange_reads += 1
        return FakeLimitRangeList(self.limitranges)
