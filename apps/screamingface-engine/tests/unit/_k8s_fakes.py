from dataclasses import dataclass


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
    type: str
    default: dict[str, str] | None = None
    defaultRequest: dict[str, str] | None = None


@dataclass
class FakeLimitRangeSpec:
    limits: list[FakeLimitRangeItem] | None = None


@dataclass
class FakeLimitRange:
    spec: FakeLimitRangeSpec | None = None


@dataclass
class FakeLimitRangeList:
    items: list[FakeLimitRange]


class FakeCoreV1:
    """The quota/limitrange read surface for the admission tests.

    A subclass can raise ApiException from either read to exercise the degradation path.
    """

    def __init__(
        self,
        quotas: list[FakeQuota] | None = None,
        limitranges: list[FakeLimitRange] | None = None,
    ) -> None:
        self.quotas = quotas or []
        self.limitranges = limitranges or []
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
