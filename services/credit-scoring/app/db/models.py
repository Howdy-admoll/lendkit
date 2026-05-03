"""
Credit Scoring Service — ORM Models

Tables
------
credit_scores
    The latest computed score for a customer. A new row is inserted each time
    a score is (re-)computed; the most recent row for a customer is the
    authoritative score.

score_factors
    Individual signal contributions that explain how the score was built.
    One row per factor per score computation (parent: credit_scores).
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ScoreTier(StrEnum):
    EXCELLENT = "excellent"  # 750–850  → Tier A
    GOOD = "good"  # 650–749  → Tier B
    FAIR = "fair"  # 550–649  → Tier C
    POOR = "poor"  # 450–549  → Tier D
    VERY_POOR = "very_poor"  # <  450   → decline


class ScoreStatus(StrEnum):
    PENDING = "pending"  # triggered, not yet computed
    COMPUTED = "computed"  # engine ran successfully
    FAILED = "failed"  # engine error (see error_detail)
    STALE = "stale"  # superseded by a newer computation


class SignalCategory(StrEnum):
    KYC_OUTCOME = "kyc_outcome"
    IDENTITY = "identity"
    INCOME_EMPLOYMENT = "income_employment"
    REPAYMENT_HISTORY = "repayment_history"


# ---------------------------------------------------------------------------
# credit_scores
# ---------------------------------------------------------------------------


class CreditScore(Base):
    __tablename__ = "credit_scores"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # The raw numeric score (300–850)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)  # ScoreTier value
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ScoreStatus.PENDING)

    # Maximum possible score from signals that were available (for % display)
    max_possible_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Trigger that caused this computation
    trigger: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # e.g. "kyc_approved", "manual", "refresh"
    kyc_verification_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Human-readable recommendation
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    decline_reasons: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Hard-stop flags — these override the numeric score
    is_sanctioned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_pep: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    # When this score expires and should be refreshed (e.g. 90 days)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    factors: Mapped[list["ScoreFactor"]] = relationship(
        "ScoreFactor", back_populates="credit_score", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# score_factors  (explainability)
# ---------------------------------------------------------------------------


class ScoreFactor(Base):
    __tablename__ = "score_factors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    credit_score_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("credit_scores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    category: Mapped[str] = mapped_column(String(32), nullable=False)  # SignalCategory value
    factor_key: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "kyc_status"
    factor_label: Mapped[str] = mapped_column(String(128), nullable=False)  # human label
    points_awarded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    points_possible: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # positive | negative | neutral
    impact: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")

    credit_score: Mapped["CreditScore"] = relationship("CreditScore", back_populates="factors")

    __table_args__ = (UniqueConstraint("credit_score_id", "factor_key", name="uq_score_factor"),)
