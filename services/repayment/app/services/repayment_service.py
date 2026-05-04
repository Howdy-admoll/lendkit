"""
Repayment Service — Business Logic Layer

Orchestrates DB reads/writes and engine calls. All public methods receive
an AsyncSession and return domain objects / response schemas.

Payment application flow
------------------------
1. Idempotency check — reject duplicate provider_reference.
2. Fetch LoanAccount by loan_id; raise 404 if not found.
3. Guard against payments on SETTLED / WRITTEN_OFF loans.
4. Run PaymentAllocator to split payment across penalty→interest→principal.
5. Update LoanAccount balances.
6. Insert RepaymentRecord (immutable).
7. Mark the earliest unpaid ScheduleInstallment as paid (if fully covered).
8. Re-classify delinquency status.
9. If total_outstanding == 0, mark as SETTLED.
10. Commit (handled by session dependency).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    LoanAccount,
    RepaymentMethod,
    RepaymentRecord,
    RepaymentStatus,
    ScheduleInstallment,
)
from app.engine import allocator as alloc_engine
from app.engine import delinquency as delinq_engine
from app.engine import schedule as sched_engine
from app.schemas.repayment import (
    AmortizationScheduleOut,
    DefaultedLoanOut,
    DefaultsListOut,
    InstallmentOut,
    LoanRepaymentStatusOut,
    RegisterLoanRequest,
    RepaymentRecordOut,
    RepaymentStatus as SchemaRepaymentStatus,
    RepaymentWebhookPayload,
    WebhookAckOut,
)
from fastapi import HTTPException, status


# ---------------------------------------------------------------------------
# Register a new loan (called on disbursement)
# ---------------------------------------------------------------------------


async def register_loan(
    payload: RegisterLoanRequest,
    db: AsyncSession,
) -> LoanRepaymentStatusOut:
    """
    Register a newly disbursed loan and persist its amortization schedule.

    Raises 409 if a LoanAccount for this loan_id already exists.
    """
    # Idempotency guard
    existing = await db.scalar(
        select(LoanAccount).where(LoanAccount.loan_id == payload.loan_id)
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Loan account for loan_id={payload.loan_id} already registered.",
        )

    # Create loan account
    account = LoanAccount(
        loan_id=payload.loan_id,
        customer_id=payload.customer_id,
        tenant_id=payload.tenant_id,
        original_principal_kobo=payload.original_principal_kobo,
        annual_percentage_rate=payload.annual_percentage_rate,
        tenure_months=payload.tenure_months,
        monthly_installment_kobo=payload.monthly_installment_kobo,
        start_date=payload.start_date,
        first_due_date=payload.first_due_date,
        outstanding_principal_kobo=payload.original_principal_kobo,
        accrued_interest_kobo=0,
        accrued_penalties_kobo=0,
        installments_paid=0,
        next_due_date=payload.first_due_date,
        status=RepaymentStatus.CURRENT,
        days_past_due=0,
    )
    db.add(account)
    await db.flush()  # get account.id before inserting schedule rows

    # Generate and persist amortization schedule
    installments = sched_engine.generate(
        principal_kobo=payload.original_principal_kobo,
        annual_rate=payload.annual_percentage_rate,
        tenure_months=payload.tenure_months,
        first_due_date=payload.first_due_date,
    )
    for inst in installments:
        db.add(
            ScheduleInstallment(
                loan_account_id=account.id,
                installment_number=inst.installment_number,
                due_date=inst.due_date,
                opening_balance_kobo=inst.opening_balance_kobo,
                principal_due_kobo=inst.principal_due_kobo,
                interest_due_kobo=inst.interest_due_kobo,
                total_due_kobo=inst.total_due_kobo,
                closing_balance_kobo=inst.closing_balance_kobo,
                is_paid=False,
            )
        )

    await db.flush()
    return _account_to_status_out(account)


# ---------------------------------------------------------------------------
# Apply a payment
# ---------------------------------------------------------------------------


async def apply_payment(
    payload: RepaymentWebhookPayload,
    db: AsyncSession,
) -> WebhookAckOut:
    """
    Apply an inbound payment to the matching loan account.

    Returns WebhookAckOut. Raises:
    - 404 if loan_id not found
    - 409 if provider_reference already processed (idempotency)
    - 422 if loan is settled/written off (no more payments possible)
    """
    # 1. Idempotency check
    duplicate = await db.scalar(
        select(RepaymentRecord).where(
            RepaymentRecord.provider == payload.provider,
            RepaymentRecord.provider_reference == payload.provider_reference,
        )
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Payment reference '{payload.provider_reference}' already processed.",
        )

    # 2. Fetch loan account
    account = await db.scalar(
        select(LoanAccount).where(LoanAccount.loan_id == payload.loan_id)
    )
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active loan account found for loan_id={payload.loan_id}",
        )

    # 3. Guard terminal states
    if account.status in (RepaymentStatus.SETTLED, RepaymentStatus.WRITTEN_OFF):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Loan is {account.status.value} — no further payments accepted.",
        )

    # 4. Allocate payment
    balance_before = account.total_outstanding_kobo
    result = alloc_engine.allocate(
        payment_kobo=payload.amount_kobo,
        accrued_penalty_kobo=account.accrued_penalties_kobo,
        accrued_interest_kobo=account.accrued_interest_kobo,
        outstanding_principal_kobo=account.outstanding_principal_kobo,
    )

    # 5. Update balances
    account.accrued_penalties_kobo = result.remaining_penalty_kobo
    account.accrued_interest_kobo = result.remaining_interest_kobo
    account.outstanding_principal_kobo = result.remaining_principal_kobo
    account.last_payment_date = payload.paid_at
    account.last_payment_amount_kobo = payload.amount_kobo

    # 6. Insert repayment record
    try:
        payment_method = RepaymentMethod(payload.payment_method.value)
    except ValueError:
        payment_method = RepaymentMethod.UNKNOWN

    record = RepaymentRecord(
        loan_account_id=account.id,
        provider=payload.provider,
        provider_reference=payload.provider_reference,
        amount_kobo=payload.amount_kobo,
        penalty_portion_kobo=result.penalty_portion_kobo,
        interest_portion_kobo=result.interest_portion_kobo,
        principal_portion_kobo=result.principal_portion_kobo,
        overpayment_kobo=result.overpayment_kobo,
        balance_before_kobo=balance_before,
        balance_after_kobo=account.total_outstanding_kobo,
        payment_method=payment_method,
        currency=payload.currency,
        paid_at=payload.paid_at,
    )
    db.add(record)

    # 7. Mark earliest unpaid installment as paid if fully covered
    if result.principal_portion_kobo > 0:
        unpaid = await db.scalar(
            select(ScheduleInstallment)
            .where(
                ScheduleInstallment.loan_account_id == account.id,
                ScheduleInstallment.is_paid.is_(False),
            )
            .order_by(ScheduleInstallment.installment_number)
            .limit(1)
        )
        if unpaid and payload.amount_kobo >= unpaid.total_due_kobo:
            unpaid.is_paid = True
            unpaid.paid_at = payload.paid_at
            unpaid.paid_amount_kobo = payload.amount_kobo
            account.installments_paid += 1
            # Advance next_due_date
            next_unpaid = await db.scalar(
                select(ScheduleInstallment)
                .where(
                    ScheduleInstallment.loan_account_id == account.id,
                    ScheduleInstallment.is_paid.is_(False),
                )
                .order_by(ScheduleInstallment.installment_number)
                .limit(1)
            )
            account.next_due_date = next_unpaid.due_date if next_unpaid else None

    # 8. Re-classify delinquency
    classification = delinq_engine.classify(
        account.days_past_due,
        is_settled=account.outstanding_principal_kobo == 0,
    )
    account.status = RepaymentStatus(classification.status.value)

    # 9. Mark settled if fully paid
    if account.outstanding_principal_kobo == 0 and account.accrued_interest_kobo == 0:
        account.status = RepaymentStatus.SETTLED
        account.settled_at = datetime.now(timezone.utc)
        account.days_past_due = 0

    await db.flush()

    return WebhookAckOut(
        status="processed",
        loan_id=payload.loan_id,
        amount_kobo=payload.amount_kobo,
        provider_reference=payload.provider_reference,
        message=(
            "Payment fully settled the loan."
            if account.status == RepaymentStatus.SETTLED
            else f"Payment applied. Outstanding: ₦{account.total_outstanding_kobo // 100:,}"
        ),
    )


# ---------------------------------------------------------------------------
# Get loan repayment status
# ---------------------------------------------------------------------------


async def get_loan_status(loan_id: str, db: AsyncSession) -> LoanRepaymentStatusOut:
    account = await db.scalar(
        select(LoanAccount).where(LoanAccount.loan_id == loan_id)
    )
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No loan account found for loan_id={loan_id}",
        )
    return _account_to_status_out(account)


# ---------------------------------------------------------------------------
# Get amortization schedule
# ---------------------------------------------------------------------------


async def get_schedule(loan_id: str, db: AsyncSession) -> AmortizationScheduleOut:
    account = await db.scalar(
        select(LoanAccount).where(LoanAccount.loan_id == loan_id)
    )
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No loan account found for loan_id={loan_id}",
        )

    rows = (
        await db.scalars(
            select(ScheduleInstallment)
            .where(ScheduleInstallment.loan_account_id == account.id)
            .order_by(ScheduleInstallment.installment_number)
        )
    ).all()

    total_interest = sum(r.interest_due_kobo for r in rows)
    total_repayable = sum(r.total_due_kobo for r in rows)

    return AmortizationScheduleOut(
        loan_id=loan_id,
        principal_kobo=account.original_principal_kobo,
        annual_percentage_rate=account.annual_percentage_rate,
        tenure_months=account.tenure_months,
        monthly_installment_kobo=account.monthly_installment_kobo,
        total_interest_kobo=total_interest,
        total_repayable_kobo=total_repayable,
        schedule=[
            InstallmentOut(
                installment_number=r.installment_number,
                due_date=r.due_date,
                opening_balance_kobo=r.opening_balance_kobo,
                principal_due_kobo=r.principal_due_kobo,
                interest_due_kobo=r.interest_due_kobo,
                total_due_kobo=r.total_due_kobo,
                closing_balance_kobo=r.closing_balance_kobo,
                is_paid=r.is_paid,
                paid_at=r.paid_at,
                paid_amount_kobo=r.paid_amount_kobo,
            )
            for r in rows
        ],
    )


# ---------------------------------------------------------------------------
# Get defaulted loans
# ---------------------------------------------------------------------------


async def get_defaults(
    days_past_due_threshold: int,
    db: AsyncSession,
    limit: int = 100,
    offset: int = 0,
) -> DefaultsListOut:
    total = await db.scalar(
        select(func.count(LoanAccount.id)).where(
            LoanAccount.days_past_due >= days_past_due_threshold,
            LoanAccount.status.in_(
                [RepaymentStatus.DELINQUENT, RepaymentStatus.DEFAULT]
            ),
        )
    )

    rows = (
        await db.scalars(
            select(LoanAccount)
            .where(
                LoanAccount.days_past_due >= days_past_due_threshold,
                LoanAccount.status.in_(
                    [RepaymentStatus.DELINQUENT, RepaymentStatus.DEFAULT]
                ),
            )
            .order_by(LoanAccount.days_past_due.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return DefaultsListOut(
        threshold_days=days_past_due_threshold,
        total=total or 0,
        loans=[
            DefaultedLoanOut(
                loan_id=r.loan_id,
                customer_id=r.customer_id,
                tenant_id=r.tenant_id,
                days_past_due=r.days_past_due,
                outstanding_principal_kobo=r.outstanding_principal_kobo,
                accrued_penalties_kobo=r.accrued_penalties_kobo,
                status=SchemaRepaymentStatus(r.status.value),
                last_payment_date=r.last_payment_date,
            )
            for r in rows
        ],
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _account_to_status_out(account: LoanAccount) -> LoanRepaymentStatusOut:
    return LoanRepaymentStatusOut(
        loan_id=account.loan_id,
        customer_id=account.customer_id,
        tenant_id=account.tenant_id,
        original_principal_kobo=account.original_principal_kobo,
        outstanding_principal_kobo=account.outstanding_principal_kobo,
        accrued_interest_kobo=account.accrued_interest_kobo,
        accrued_penalties_kobo=account.accrued_penalties_kobo,
        total_outstanding_kobo=account.total_outstanding_kobo,
        annual_percentage_rate=account.annual_percentage_rate,
        tenure_months=account.tenure_months,
        monthly_installment_kobo=account.monthly_installment_kobo,
        installments_paid=account.installments_paid,
        installments_remaining=account.installments_remaining,
        status=SchemaRepaymentStatus(account.status.value),
        days_past_due=account.days_past_due,
        next_due_date=account.next_due_date,
        last_payment_date=account.last_payment_date,
        last_payment_amount_kobo=account.last_payment_amount_kobo,
        start_date=account.start_date,
        settled_at=account.settled_at,
    )
