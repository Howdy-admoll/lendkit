"""
Disbursement Service — Transfer Recipient Management

Handles creating and retrieving Paystack transfer recipients.
A recipient represents a verified bank account owned by a borrower.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DisbursementProvider, TransferRecipient
from app.engine.providers.base import PaymentProvider
from app.schemas.disbursement import (
    CreateRecipientRequest,
    DisbursementProvider as SchemaProvider,
    TransferRecipientOut,
)
from fastapi import HTTPException


async def create_recipient(
    payload: CreateRecipientRequest,
    db: AsyncSession,
    provider: PaymentProvider,
) -> TransferRecipientOut:
    """
    Register a borrower's bank account with the payment provider.

    If a recipient for the same account_number + bank_code already exists
    for this customer, returns the existing record (idempotent).
    """
    # Check for existing recipient
    existing = await db.scalar(
        select(TransferRecipient).where(
            TransferRecipient.customer_id == payload.customer_id,
            TransferRecipient.account_number == payload.account_number,
            TransferRecipient.bank_code == payload.bank_code,
            TransferRecipient.provider == DisbursementProvider(payload.provider.value),
            TransferRecipient.is_active.is_(True),
        )
    )
    if existing:
        return _to_out(existing)

    # Register with provider
    result = await provider.create_recipient(
        account_number=payload.account_number,
        bank_code=payload.bank_code,
        account_name=payload.account_name,
        currency=payload.currency,
    )

    recipient = TransferRecipient(
        customer_id=payload.customer_id,
        tenant_id=payload.tenant_id,
        account_number=payload.account_number,
        bank_code=payload.bank_code,
        bank_name=payload.bank_name,
        account_name=result.account_name,  # use confirmed name from provider
        currency=payload.currency,
        provider=DisbursementProvider(payload.provider.value),
        recipient_code=result.recipient_code,
        is_active=True,
    )
    db.add(recipient)
    await db.flush()
    return _to_out(recipient)


async def get_recipient(recipient_id: str, db: AsyncSession) -> TransferRecipientOut:
    recipient = await db.get(TransferRecipient, recipient_id)
    if not recipient:
        raise HTTPException(status_code=404, detail=f"Recipient {recipient_id} not found.")
    return _to_out(recipient)


async def list_customer_recipients(
    customer_id: str, db: AsyncSession
) -> list[TransferRecipientOut]:
    rows = (
        await db.scalars(
            select(TransferRecipient).where(
                TransferRecipient.customer_id == customer_id,
                TransferRecipient.is_active.is_(True),
            )
        )
    ).all()
    return [_to_out(r) for r in rows]


def _to_out(r: TransferRecipient) -> TransferRecipientOut:
    return TransferRecipientOut(
        id=r.id,
        customer_id=r.customer_id,
        tenant_id=r.tenant_id,
        account_number=r.account_number,
        bank_code=r.bank_code,
        bank_name=r.bank_name,
        account_name=r.account_name,
        currency=r.currency,
        provider=SchemaProvider(r.provider.value),
        recipient_code=r.recipient_code,
        is_active=r.is_active,
        created_at=r.created_at,
    )
