"""
LendKit Shared — Event Publisher

Publishes domain events to Redis Streams or Kafka.
Consumer services subscribe to specific streams to react to events
(e.g., loan-origination listens to kyc.approved before disbursing).

Usage:
    from shared.events.publisher import EventPublisher
    publisher = EventPublisher.from_settings()
    await publisher.publish("lendkit:kyc:events", KYCApprovedEvent(...))
"""
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event base
# ---------------------------------------------------------------------------

class LendKitEvent:
    """
    Base class for all domain events.
    Subclass and add typed fields for each event type.
    """
    event_type: str = "lendkit.event"

    def __init__(self, source: str, **kwargs: Any) -> None:
        self.source    = source
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.data      = kwargs

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "source": self.source,
            "timestamp": self.timestamp,
            **self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ---------------------------------------------------------------------------
# Concrete Events
# ---------------------------------------------------------------------------

class KYCApprovedEvent(LendKitEvent):
    event_type = "kyc.approved"

    def __init__(self, verification_id: str, customer_id: str, tenant_id: str, risk_score: int) -> None:
        super().__init__(
            source="kyc-service",
            verification_id=verification_id,
            customer_id=customer_id,
            tenant_id=tenant_id,
            risk_score=risk_score,
        )


class KYCRejectedEvent(LendKitEvent):
    event_type = "kyc.rejected"

    def __init__(
        self, verification_id: str, customer_id: str, tenant_id: str, reason: str
    ) -> None:
        super().__init__(
            source="kyc-service",
            verification_id=verification_id,
            customer_id=customer_id,
            tenant_id=tenant_id,
            reason=reason,
        )


class LoanDisbursedEvent(LendKitEvent):
    event_type = "loan.disbursed"

    def __init__(
        self, loan_id: str, customer_id: str, amount: float, currency: str
    ) -> None:
        super().__init__(
            source="loan-service",
            loan_id=loan_id,
            customer_id=customer_id,
            amount=amount,
            currency=currency,
        )


class RepaymentReceivedEvent(LendKitEvent):
    event_type = "repayment.received"

    def __init__(
        self, loan_id: str, amount: float, balance_remaining: float
    ) -> None:
        super().__init__(
            source="repayment-service",
            loan_id=loan_id,
            amount=amount,
            balance_remaining=balance_remaining,
        )


class DefaultDetectedEvent(LendKitEvent):
    event_type = "loan.default_detected"

    def __init__(
        self, loan_id: str, customer_id: str, days_overdue: int, outstanding: float
    ) -> None:
        super().__init__(
            source="repayment-service",
            loan_id=loan_id,
            customer_id=customer_id,
            days_overdue=days_overdue,
            outstanding=outstanding,
        )


# ---------------------------------------------------------------------------
# Publisher interface here so we can add more backends in the future (e.g., RabbitMQ, AWS SNS)
# ---------------------------------------------------------------------------

class BasePublisher(ABC):
    @abstractmethod
    async def publish(self, stream: str, event: LendKitEvent) -> str:
        """Publish event to stream. Returns message/offset ID."""

    @abstractmethod
    async def close(self) -> None:
        """Close connections."""


# ---------------------------------------------------------------------------
# Redis Streams Publisher here as default for simplicity and low overhead. Kafka is optional for high-throughput use cases.
# ---------------------------------------------------------------------------

class RedisStreamPublisher(BasePublisher):
    """
    Publishes to Redis Streams (XADD).
    Each stream maps to a domain: lendkit:kyc:events, lendkit:loan:events, etc.
    """

    def __init__(self, redis_url: str, maxlen: int = 100_000) -> None:
        import redis.asyncio as aioredis
        self._client = aioredis.from_url(redis_url, decode_responses=True)
        self._maxlen = maxlen

    async def publish(self, stream: str, event: LendKitEvent) -> str:
        msg_id = await self._client.xadd(
            stream,
            {"data": event.to_json(), "type": event.event_type},
            maxlen=self._maxlen,
            approximate=True,
        )
        log.debug("Published %s to %s: %s", event.event_type, stream, msg_id)
        return msg_id

    async def close(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Kafka Publisher
# ---------------------------------------------------------------------------

class KafkaPublisher(BasePublisher):
    """
    Publishes to Apache Kafka topics.
    Requires aiokafka: pip install aiokafka
    """

    def __init__(self, bootstrap_servers: str) -> None:
        try:
            from aiokafka import AIOKafkaProducer  # type: ignore[import]
            self._producer = AIOKafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda v: v.encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                acks="all",
                enable_idempotence=True,
            )
        except ImportError:
            raise RuntimeError("aiokafka required for Kafka publisher: pip install aiokafka")

    async def start(self) -> None:
        await self._producer.start()

    async def publish(self, stream: str, event: LendKitEvent) -> str:
        # stream → Kafka topic (e.g., "lendkit:kyc:events" → "lendkit-kyc-events")
        topic = stream.replace(":", "-")
        key = event.data.get("customer_id") or event.data.get("loan_id")
        await self._producer.send_and_wait(
            topic, value=event.to_json(), key=key
        )
        log.debug("Published %s to Kafka topic %s", event.event_type, topic)
        return f"{topic}:sent"

    async def close(self) -> None:
        await self._producer.stop()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_publisher(backend: str = "redis", **kwargs: Any) -> BasePublisher:
    """
    Return a publisher based on configured backend.

    Args:
        backend: "redis" or "kafka"
        **kwargs: passed to publisher constructor
    """
    if backend == "kafka":
        return KafkaPublisher(bootstrap_servers=kwargs.get("bootstrap_servers", "kafka:9092"))
    return RedisStreamPublisher(redis_url=kwargs.get("redis_url", "redis://redis:6379/1"))
