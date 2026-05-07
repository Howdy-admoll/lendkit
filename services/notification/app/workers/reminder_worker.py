"""
Notification Service — Payment Reminder Worker

Runs on a schedule (called externally via cron or APScheduler).
Queries the repayment service's data for upcoming due dates and
fires repayment.due_soon notifications.

In this architecture, rather than querying the repayment DB directly
(which would couple services), the reminder worker publishes
repayment.due_soon events onto the Redis Stream — the event consumer
then picks them up and dispatches notifications. This preserves
service isolation.

Reminder schedule: configured via settings.reminder_days_before (default [3, 1]).

In production this is invoked by a Kubernetes CronJob at midnight UTC daily.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, timedelta

import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def publish_reminder(
    redis_client: aioredis.Redis,
    stream: str,
    consumer_group: str,
    *,
    loan_id: str,
    borrower_id: str,
    first_name: str,
    phone: str | None,
    email: str | None,
    amount_formatted: str,
    due_date: str,
    days_left: int,
    installment_number: int,
    total_installments: int,
    monthly_installment_formatted: str,
) -> None:
    """Publish one repayment.due_soon event to the loan events stream."""
    data = {
        "loan_id": loan_id,
        "borrower_id": borrower_id,
        "first_name": first_name,
        "phone": phone or "",
        "email": email or "",
        "amount_formatted": amount_formatted,
        "due_date": due_date,
        "days_left": days_left,
        "installment_number": installment_number,
        "total_installments": total_installments,
        "monthly_installment_formatted": monthly_installment_formatted,
    }

    await redis_client.xadd(
        stream,
        {"event_type": "repayment.due_soon", "data": json.dumps(data)},
    )

    logger.info(
        "Published repayment.due_soon for loan %s (due in %d day(s))",
        loan_id,
        days_left,
    )


async def run_reminder_check(due_dates: list[dict]) -> None:
    """
    Entry point called by the scheduler.

    Parameters
    ----------
    due_dates:
        List of dicts with keys matching publish_reminder parameters.
        Typically sourced by querying the repayment service API or a
        shared read replica.
    """
    settings = get_settings()
    redis_client = aioredis.from_url(settings.redis_stream_url, decode_responses=True)

    today = date.today()
    reminder_targets = {
        (today + timedelta(days=d)).isoformat(): d
        for d in settings.reminder_days_before
    }

    for item in due_dates:
        due_date_str = item.get("due_date", "")
        if due_date_str not in reminder_targets:
            continue

        days_left = reminder_targets[due_date_str]
        await publish_reminder(
            redis_client,
            stream="repayment.events",
            consumer_group=settings.consumer_group,
            loan_id=item["loan_id"],
            borrower_id=item["borrower_id"],
            first_name=item.get("first_name", "Customer"),
            phone=item.get("phone"),
            email=item.get("email"),
            amount_formatted=item.get("amount_formatted", "₦0.00"),
            due_date=due_date_str,
            days_left=days_left,
            installment_number=item.get("installment_number", 0),
            total_installments=item.get("total_installments", 0),
            monthly_installment_formatted=item.get("amount_formatted", "₦0.00"),
        )

    await redis_client.aclose()
