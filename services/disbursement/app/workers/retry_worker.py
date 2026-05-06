"""
Disbursement Service — Retry Worker

Runs on a schedule (every minute) to pick up FAILED disbursements
whose next_retry_at has elapsed and re-initiate the transfer.

Retry schedule (from state_machine.py):
  Attempt 1 →  60s  (1 min after failure)
  Attempt 2 → 300s  (5 min after failure)
  Attempt 3 → 900s (15 min after failure)

After max_attempts, the disbursement stays FAILED and requires
manual intervention or a different approach (e.g., different provider).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import DisbursementRequest, DisbursementState
from app.engine.providers.paystack import PaystackProvider
from app.services.disbursement_service import retry_disbursement

logger = logging.getLogger(__name__)


async def run_retry_sweep(db: AsyncSession) -> dict[str, int]:
    """
    Find all FAILED disbursements past their next_retry_at and retry them.

    Returns stats dict: {scanned, retried, still_failed, errors}
    """
    now = datetime.now(timezone.utc)

    candidates = (
        await db.scalars(
            select(DisbursementRequest).where(
                DisbursementRequest.state == DisbursementState.FAILED,
                DisbursementRequest.next_retry_at <= now,
                DisbursementRequest.attempt_count < DisbursementRequest.max_attempts,
            )
        )
    ).all()

    stats = {"scanned": len(candidates), "retried": 0, "still_failed": 0, "errors": 0}

    provider = PaystackProvider(secret_key=settings.paystack_secret_key)

    for req in candidates:
        try:
            result = await retry_disbursement(req.loan_id, db, provider)
            if result.state.value == "transfer_initiated":
                stats["retried"] += 1
                logger.info(
                    "Disbursement retry initiated",
                    extra={"loan_id": req.loan_id, "attempt": result.attempt_count},
                )
            else:
                stats["still_failed"] += 1
        except Exception as exc:
            stats["errors"] += 1
            logger.exception(
                "Error during disbursement retry",
                extra={"loan_id": req.loan_id, "error": str(exc)},
            )

    logger.info("Disbursement retry sweep complete", extra=stats)
    return stats
