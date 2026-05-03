"""
Credit Scoring Service — Score Service

Orchestrates: request validation → engine computation → DB persistence.
"""

from __future__ import annotations

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import CreditScore, ScoreFactor, ScoreStatus
from app.engine.scorer import ScoringResult, compute_score
from app.schemas.score import ScoreRequest

log = structlog.get_logger(__name__)


async def request_score(
    db: AsyncSession,
    req: ScoreRequest,
) -> CreditScore:
    """
    Compute a credit score for a customer and persist it.

    1. Mark any previous *computed* scores for this customer as STALE.
    2. Create a new CreditScore row in PENDING state.
    3. Run the scoring engine.
    4. Persist the result (factors + score fields).
    5. Return the completed CreditScore ORM object.
    """
    log.info(
        "score.request",
        customer_id=req.customer_id,
        tenant_id=req.tenant_id,
        trigger=req.trigger,
    )

    # -----------------------------------------------------------------------
    # Mark prior scores stale
    # -----------------------------------------------------------------------
    prior = await db.execute(
        select(CreditScore).where(
            CreditScore.customer_id == req.customer_id,
            CreditScore.tenant_id == req.tenant_id,
            CreditScore.status == ScoreStatus.COMPUTED,
        )
    )
    for old in prior.scalars().all():
        old.status = ScoreStatus.STALE

    # -----------------------------------------------------------------------
    # Create pending record
    # -----------------------------------------------------------------------
    kyc_verification_id = req.kyc.verification_id if req.kyc else None
    cs = CreditScore(
        customer_id=req.customer_id,
        tenant_id=req.tenant_id,
        status=ScoreStatus.PENDING,
        trigger=req.trigger,
        kyc_verification_id=kyc_verification_id,
    )
    db.add(cs)
    await db.flush()  # get cs.id

    # -----------------------------------------------------------------------
    # Run engine
    # -----------------------------------------------------------------------
    try:
        result: ScoringResult = compute_score(
            kyc=req.kyc,
            income=req.income,
            repayment=req.repayment,
            requested_loan_amount_kobo=req.requested_loan_amount_kobo,
        )
    except Exception as exc:
        log.error("score.engine_error", customer_id=req.customer_id, exc=str(exc))
        cs.status = ScoreStatus.FAILED
        cs.error_detail = str(exc)
        await db.flush()
        return cs

    # -----------------------------------------------------------------------
    # Persist result
    # -----------------------------------------------------------------------
    cs.score = result.score
    cs.tier = result.tier
    cs.status = ScoreStatus.COMPUTED
    cs.max_possible_score = result.max_possible_score
    cs.recommendation = result.recommendation
    cs.decline_reasons = result.decline_reasons or None
    cs.is_sanctioned = result.is_sanctioned
    cs.is_pep = result.is_pep
    cs.computed_at = result.computed_at
    cs.expires_at = result.expires_at

    for f in result.factors:
        sf = ScoreFactor(
            credit_score_id=cs.id,
            category=f.category,
            factor_key=f.factor_key,
            factor_label=f.factor_label,
            points_awarded=f.points_awarded,
            points_possible=f.points_possible,
            detail=f.detail,
            impact=f.impact,
        )
        db.add(sf)

    await db.flush()

    log.info(
        "score.computed",
        customer_id=req.customer_id,
        score=cs.score,
        tier=cs.tier,
        is_sanctioned=cs.is_sanctioned,
    )
    return cs


async def get_latest_score(
    db: AsyncSession,
    customer_id: str,
    tenant_id: str,
) -> CreditScore | None:
    """Return the most recently computed score for a customer."""
    result = await db.execute(
        select(CreditScore)
        .options(selectinload(CreditScore.factors))
        .where(
            CreditScore.customer_id == customer_id,
            CreditScore.tenant_id == tenant_id,
            CreditScore.status == ScoreStatus.COMPUTED,
        )
        .order_by(desc(CreditScore.computed_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_score_by_id(
    db: AsyncSession,
    score_id: str,
    tenant_id: str,
) -> CreditScore | None:
    """Fetch a specific score by ID (tenant-scoped)."""
    result = await db.execute(
        select(CreditScore)
        .options(selectinload(CreditScore.factors))
        .where(
            CreditScore.id == score_id,
            CreditScore.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def list_scores(
    db: AsyncSession,
    customer_id: str,
    tenant_id: str,
    limit: int = 10,
    offset: int = 0,
) -> tuple[list[CreditScore], int]:
    """Return paginated score history for a customer."""
    from sqlalchemy import func

    count_result = await db.execute(
        select(func.count()).where(
            CreditScore.customer_id == customer_id,
            CreditScore.tenant_id == tenant_id,
        )
    )
    total = count_result.scalar_one()

    rows = await db.execute(
        select(CreditScore)
        .options(selectinload(CreditScore.factors))
        .where(
            CreditScore.customer_id == customer_id,
            CreditScore.tenant_id == tenant_id,
        )
        .order_by(desc(CreditScore.created_at))
        .limit(limit)
        .offset(offset)
    )
    return list(rows.scalars().all()), total
