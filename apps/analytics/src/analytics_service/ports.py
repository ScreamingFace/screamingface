"""Core-owned delivery interface."""

from typing import Protocol

from analytics_service.contract import Batch


class DeliveryUnavailable(Exception):
    pass


class UpstreamRejected(Exception):
    pass


class EventDelivery(Protocol):
    async def deliver(self, batch: Batch) -> None:
        """Return only on upstream acceptance; propagate cancellation."""
