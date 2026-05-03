"""
Loan Origination Service — Loan Service Layer

Orchestrates the full origination flow:
  1. Fetch latest credit score (or trigger a fresh one) from credit-scoring service
  2. Run the underwriting engine
  3. Persist LoanApplication + LoanOffer
  4. Return the populated response schema
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.models import LoanApplication, LoanOffer, LoanState
from app.engine.underwriting import underwrite
from app.schemas.loan import (
    LoanApplicationOut,
    LoanApplicationRequest,
    LoanListOut,
    LoanOfferOut,
)
from app.services.scoring_client import scoring_client

logger = logging.getLogger(__name__)

_KOBO = 100  # 1 NGN = 100 kobo


def _to_ngn(kobo: int) -> float:
    return round(kobo / _KOBO, 2)


def _offer_out(offer: LoanOffer) -> LoanOfferOut:
    return LoanOfferOut(
        offer_id=offer.id,
        approved_amount_kobo=offer.approved_amount_kobo,
        approved_amount_ngn=_to_ngn(offer.approved_amount_kobo),
        tenure_months=offer.tenure_months,
        annual_percentage_rate=offer.annual_percentage_rate,
        monthly_repayment_kobo=offer.monthly_repayment_kobo,
        monthly_repayment_ngn=_to_ngn(offer.monthly_repayment_kobo),
        total_repayable_kobo=offer.total_repayable_kobo,
        total_repayable_ngn=_to_ngn(offer.total_repayable_kobo),
        disbursement_method=offer.disbursement_method,
        is_accepted=offer.is_accepted,
        expires_at=offer.expires_at,
    )


def _loan_out(loan: LoanApplication) -> LoanApplicationOut:
    return LoanApplicationOut(
        loan_id=loan.id,
        customer_id=loan.customer_id,
        tenant_id=loan.tenant_id,
        state=loan.state,
        requested_amount_kobo=loan.requested_amount_kobo,
        requested_amount_ngn=_to_ngn(loan.requested_amount_kobo),
        tenure_months=loan.tenure_months,
        purpose=loan.purpose,
        credit_score=loan.credit_score,
        credit_tier=loan.credit_tier,
        decline_reasons=loan.decline_reasons,
        offer=_offer_out(loan.offer) if loan.offer else None,
        created_at=loan.created_at,
        updated_at=loan.updated_at,
    )


async def _load_loan(db: AsyncSession, loan_id: str) -> LoanApplication | None:
    result = await db.execute(
        select(LoanApplication)
        .where(LoanApplication.id == loan_id)
        .options(selectinload(LoanApplication.offer))
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def submit_application(
    db: AsyncSession,
    payload: LoanApplicationRequest,
) -> LoanApplicationOut:
    """
    Full synchronous origination flow:
    1. Fetch credit score
    2. Underwrite
    3. Persist + return
    """

    # --- 1. Fetch or request credit score ---
    credit_score: int | None = None
    credit_tier: str | None = None

    try:
        score_data = await scoring_client.get_latest_score(
            customer_id=payload.customer_id,
            tenant_id=payload.tenant_id,
        )
        if score_data is None:
            # No score on file — request a fresh computation
            score_data = await scoring_client.request_score(
                customer_id=payload.customer_id,
                tenant_id=payload.tenant_id,
                kyc_verification_id=payload.kyc_verification_id,
                monthly_income_kobo=payload.monthly_income_kobo,
                employment_type=payload.employment_type,
                requested_loan_amount_kobo=payload.requested_amount_kobo,
            )
        credit_score = score_data.get("score")
        credit_tier = score_data.get("tier")
    except httpx.HTTPError as exc:
        logger.warning("Credit scoring service unreachable: %s — proceeding without score", exc)

    # --- 2. Underwrite ---
    effective_tier = credit_tier or "very_poor"

    decision = underwrite(
        credit_tier=effective_tier,
        requested_amount_kobo=payload.requested_amount_kobo,
        tenure_months=payload.tenure_months,
        monthly_income_kobo=payload.monthly_income_kobo,
    )

    # --- 3. Persist loan ---
    loan = LoanApplication(
        customer_id=payload.customer_id,
        tenant_id=payload.tenant_id,
        requested_amount_kobo=payload.requested_amount_kobo,
        tenure_months=payload.tenure_months,
        purpose=payload.purpose,
        kyc_verification_id=payload.kyc_verification_id,
        monthly_income_kobo=payload.monthly_income_kobo,
        employment_type=payload.employment_type,
        credit_score=credit_score,
        credit_tier=effective_tier,
        state=LoanState.UNDERWRITING,
    )

    if decision.approved:
        loan.state = LoanState.APPROVED
        loan.underwriting_notes = decision.notes or None
        db.add(loan)
        await db.flush()  # get loan.id before creating offer

        offer = LoanOffer(
            loan_id=loan.id,
            approved_amount_kobo=decision.approved_amount_kobo,
            tenure_months=decision.tenure_months,
            annual_percentage_rate=decision.annual_percentage_rate,
            monthly_repayment_kobo=decision.monthly_repayment_kobo,
            total_repayable_kobo=decision.total_repayable_kobo,
            expires_at=datetime.now(UTC) + timedelta(hours=settings.offer_validity_hours),
        )
        db.add(offer)
        loan.state = LoanState.OFFER_SENT
    else:
        loan.state = LoanState.REJECTED
        loan.decline_reasons = decision.decline_reasons

    await db.commit()
    await db.refresh(loan)
    if loan.offer:
        await db.refresh(loan.offer)

    return _loan_out(loan)


async def get_loan(db: AsyncSession, loan_id: str) -> LoanApplicationOut | None:
    loan = await _load_loan(db, loan_id)
    return _loan_out(loan) if loan else None


async def accept_offer(
    db: AsyncSession,
    loan_id: str,
    disbursement_method: str,
) -> LoanApplicationOut | None:
    loan = await _load_loan(db, loan_id)
    if loan is None:
        return None

    if loan.state != LoanState.OFFER_SENT:
        raise ValueError(f"Loan is in state '{loan.state}'; offer can only be accepted when in 'offer_sent'.")

    if loan.offer is None:
        raise ValueError("No offer found for this loan.")

    now = datetime.now(UTC)
    if loan.offer.expires_at < now:
        raise ValueError("Offer has expired. Please reapply.")

    loan.offer.is_accepted = True
    loan.offer.accepted_at = now
    loan.offer.disbursement_method = disbursement_method
    loan.state = LoanState.OFFER_ACCEPTED

    await db.commit()
    await db.refresh(loan)
    await db.refresh(loan.offer)

    return _loan_out(loan)


async def cancel_loan(db: AsyncSession, loan_id: str) -> LoanApplicationOut | None:
    loan = await _load_loan(db, loan_id)
    if loan is None:
        return None

    terminal_states = {LoanState.ACTIVE, LoanState.REJECTED, LoanState.CANCELLED}
    if loan.state in terminal_states:
        raise ValueError(f"Loan in state '{loan.state}' cannot be cancelled.")

    loan.state = LoanState.CANCELLED
    await db.commit()
    await db.refresh(loan)
    return _loan_out(loan)


async def list_customer_loans(
    db: AsyncSession,
    customer_id: str,
    tenant_id: str,
    limit: int = 20,
    offset: int = 0,
) -> LoanListOut:
    base_q = (
        select(LoanApplication)
        .where(
            LoanApplication.customer_id == customer_id,
            LoanApplication.tenant_id == tenant_id,
        )
        .options(selectinload(LoanApplication.offer))
    )

    count_result = await db.execute(
        select(func.count()).select_from(base_q.subquery())
    )
    total = count_result.scalar_one()

    result = await db.execute(
        base_q.order_by(LoanApplication.created_at.desc()).limit(limit).offset(offset)
    )
    loans = result.scalars().all()

    return LoanListOut(items=[_loan_out(l) for l in loans], total=total)
