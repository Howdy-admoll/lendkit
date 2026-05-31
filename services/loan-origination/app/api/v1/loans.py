"""
Loan Origination Service — Loan API Routes (v1)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.loan import (
    LoanApplicationOut,
    LoanApplicationRequest,
    LoanListOut,
    OfferAcceptRequest,
)
from app.services import loan_service

router = APIRouter(prefix="/api/v1/loans", tags=["Loans"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "",
    response_model=LoanApplicationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a loan application",
)
async def apply_for_loan(payload: LoanApplicationRequest, db: DbDep) -> LoanApplicationOut:
    """
    Submit a new loan application.

    The service will:
    1. Fetch or trigger a credit score from the credit-scoring service.
    2. Run the underwriting engine.
    3. Return the loan record — approved with an offer, or rejected with reasons.
    """
    return await loan_service.submit_application(db, payload)


@router.get(
    "",
    response_model=LoanListOut,
    summary="List all loan applications",
)
async def list_loans(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: DbDep = ...,
) -> LoanListOut:
    return await loan_service.list_all_loans(db, limit, offset)


@router.get(
    "/{loan_id}",
    response_model=LoanApplicationOut,
    summary="Get loan application",
)
async def get_loan(loan_id: str, db: DbDep) -> LoanApplicationOut:
    loan = await loan_service.get_loan(db, loan_id)
    if loan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan not found.")
    return loan


@router.post(
    "/{loan_id}/accept-offer",
    response_model=LoanApplicationOut,
    summary="Accept a loan offer",
)
async def accept_offer(loan_id: str, payload: OfferAcceptRequest, db: DbDep) -> LoanApplicationOut:
    """
    Customer accepts the loan offer. Transitions state to OFFER_ACCEPTED.
    A separate disbursement job picks this up and transitions to DISBURSING → ACTIVE.
    """
    try:
        loan = await loan_service.accept_offer(db, loan_id, payload.disbursement_method)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if loan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan not found.")
    return loan


@router.post(
    "/{loan_id}/cancel",
    response_model=LoanApplicationOut,
    summary="Cancel a loan application",
)
async def cancel_loan(loan_id: str, db: DbDep) -> LoanApplicationOut:
    try:
        loan = await loan_service.cancel_loan(db, loan_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if loan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan not found.")
    return loan


@router.get(
    "/customer/{customer_id}",
    response_model=LoanListOut,
    summary="List loans for a customer",
)
async def list_customer_loans(
    customer_id: str,
    tenant_id: str = Query(..., description="Tenant identifier"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: DbDep = ...,
) -> LoanListOut:
    return await loan_service.list_customer_loans(db, customer_id, tenant_id, limit, offset)
