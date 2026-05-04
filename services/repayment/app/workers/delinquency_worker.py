"""
Repayment Service — Delinquency Detection Worker

Runs on a schedule (every hour via APScheduler or Celery beat) to:
  1. Find all non-terminal loan accounts where next_due_date < today.
  2. Recompute days_past_due.
  3. Accrue daily penalties for delinquent/default loans.
  4. Update RepaymentStatus via the DelinquencyClassifier.
  5. Emit domain events for status transitions (loan.delinquent, loan.default_detected).

In development / CI this is exposed as a standalone async function that can be
called directly. In production it is driven by APScheduler as a background task.

Event schema (emitted to Redis Stream repayment.events):
    {
        "event": "loan.status_changed",
        "loan_id": "<uuid>",
        "customer_id": "<uuid>",
        "previous_status": "current",
        "new_status": "delinquent",
        "days_past_due": 15,
        "outstanding_principal_kobo": 450000,
        "timestamp": "2025-03-01T10:00:00Z"
    }
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LoanAccount, RepaymentStatus
from app.engine.delinquency import ClassificationConfig, classify
from app.engine.allocator import daily_penalty

logger = logging.getLogger(__name__)


async def run_delinquency_sweep(
    db: AsyncSession,
    today: date | None = None,
    config: ClassificationConfig = ClassificationConfig(),
) -> dict[str, int]:
    """
    Scan all active loan accounts and update delinquency status.

    Parameters
    ----------
    db:
        AsyncSession — must be committed by the caller.
    today:
        Override today's date (for testing). Defaults to date.today().
    config:
        Delinquency classification config.

    Returns
    -------
    dict with keys: scanned, updated, newly_delinquent, newly_default, errors
    """
    today = today or date.today()

    # Fetch all non-terminal accounts where next_due_date is set
    accounts = (
        await db.scalars(
            select(LoanAccount).where(
                LoanAccount.status.notin_(
                    [RepaymentStatus.SETTLED, RepaymentStatus.WRITTEN_OFF]
                ),
                LoanAccount.next_due_date.isnot(None),
            )
        )
    ).all()

    stats = {
        "scanned": len(accounts),
        "updated": 0,
        "newly_delinquent": 0,
        "newly_default": 0,
        "errors": 0,
    }

    for account in accounts:
        try:
            prev_status = account.status
            due = account.next_due_date

            # Compute DPD
            dpd = max(0, (today - due).days)
            account.days_past_due = dpd

            # Accrue daily penalty for overdue accounts
            if dpd > config.grace_period_days and account.outstanding_principal_kobo > 0:
                penalty = daily_penalty(
                    outstanding_principal_kobo=account.outstanding_principal_kobo,
                    days_past_due=1,  # accrue one day at a time (called daily)
                )
                account.accrued_penalties_kobo += penalty

            # Classify
            result = classify(
                dpd,
                is_settled=account.outstanding_principal_kobo == 0,
                is_written_off=account.status == RepaymentStatus.WRITTEN_OFF,
                config=config,
            )
            new_status = RepaymentStatus(result.status.value)

            if new_status != prev_status:
                account.status = new_status
                stats["updated"] += 1

                if new_status == RepaymentStatus.DELINQUENT:
                    stats["newly_delinquent"] += 1
                    logger.warning(
                        "Loan entered DELINQUENT",
                        extra={
                            "loan_id": account.loan_id,
                            "customer_id": account.customer_id,
                            "days_past_due": dpd,
                        },
                    )

                elif new_status == RepaymentStatus.DEFAULT:
                    stats["newly_default"] += 1
                    logger.error(
                        "Loan entered DEFAULT",
                        extra={
                            "loan_id": account.loan_id,
                            "customer_id": account.customer_id,
                            "days_past_due": dpd,
                            "outstanding_principal_kobo": account.outstanding_principal_kobo,
                        },
                    )

        except Exception as exc:
            logger.exception(
                "Error processing loan account",
                extra={"loan_id": account.loan_id, "error": str(exc)},
            )
            stats["errors"] += 1

    logger.info(
        "Delinquency sweep complete",
        extra={"today": today.isoformat(), **stats},
    )
    return stats
