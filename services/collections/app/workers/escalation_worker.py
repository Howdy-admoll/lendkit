"""
Collections Service — Daily Escalation Worker

Runs once per day (invoked by a Kubernetes CronJob).
Queries all open collection cases, checks current DPD against the
escalation ladder, and applies the appropriate escalation action.

DPD is refreshed by querying the repayment service API. In this
implementation we accept a pre-fetched list of (loan_id, dpd) pairs
to keep the worker decoupled from HTTP dependencies during testing.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.db.models import CollectionCase
from app.db.session import AsyncSessionLocal
from app.engine.state_machine import CollectionState
from app.services.collection_service import CollectionService

logger = logging.getLogger(__name__)


async def run_escalation_sweep(dpd_map: dict[str, int]) -> dict[str, str]:
    """
    Sweep all open collection cases and apply escalation rules.

    Parameters
    ----------
    dpd_map:
        Mapping of loan_id → current days_past_due, sourced from the
        repayment service. Cases not in the map keep their existing DPD.

    Returns
    -------
    dict[str, str]:
        Mapping of loan_id → action taken (for logging/reporting).
    """
    results: dict[str, str] = {}

    async with AsyncSessionLocal() as db:
        # Fetch all non-terminal cases
        stmt = select(CollectionCase).where(
            CollectionCase.state.not_in([
                CollectionState.RECOVERED,
                CollectionState.WRITTEN_OFF,
            ])
        )
        rows = await db.execute(stmt)
        open_cases = rows.scalars().all()

    logger.info("Escalation sweep: %d open cases", len(open_cases))

    for case in open_cases:
        current_dpd = dpd_map.get(case.loan_id, case.days_past_due)
        try:
            async with AsyncSessionLocal() as db:
                svc = CollectionService(db=db)
                action = await svc.escalate_if_needed(
                    loan_id=case.loan_id,
                    current_dpd=current_dpd,
                )
            results[case.loan_id] = action
            logger.info("Loan %s: %s", case.loan_id, action)
        except Exception as exc:
            logger.exception("Escalation failed for loan %s: %s", case.loan_id, exc)
            results[case.loan_id] = f"error: {exc}"

    return results


async def check_broken_promises() -> list[str]:
    """
    Find cases in PROMISE_TO_PAY state where the promise date has passed.

    Returns list of loan_ids that were transitioned to BROKEN_PROMISE.
    """
    from datetime import date

    today = date.today().isoformat()
    broken: list[str] = []

    async with AsyncSessionLocal() as db:
        stmt = select(CollectionCase).where(
            CollectionCase.state == CollectionState.PROMISE_TO_PAY,
            CollectionCase.promise_to_pay_date < today,
        )
        rows = await db.execute(stmt)
        overdue_promises = rows.scalars().all()

    for case in overdue_promises:
        try:
            async with AsyncSessionLocal() as db:
                svc = CollectionService(db=db)
                await svc.mark_broken_promise(loan_id=case.loan_id)
            broken.append(case.loan_id)
            logger.info("Broken promise recorded for loan %s", case.loan_id)
        except Exception as exc:
            logger.exception("Failed to mark broken promise for loan %s: %s", case.loan_id, exc)

    return broken
