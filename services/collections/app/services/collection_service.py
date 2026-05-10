"""
Collections Service — Orchestration Layer

CollectionService manages the full collection case lifecycle:

  open_case()           Create a new case from a loan.defaulted event.
  assign_agent()        Assign a collections agent to a case.
  record_promise()      Record a borrower's promise-to-pay commitment.
  mark_broken_promise() Move a case from PROMISE_TO_PAY → BROKEN_PROMISE.
  refer_to_legal()      Escalate a case to the legal team.
  record_recovery()     Record a payment and resolve the case.
  write_off()           Close a case with no recovery.
  escalate_if_needed()  Evaluate DPD and apply the appropriate escalation.
  get_case()            Fetch a case by loan_id.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CollectionActivity, CollectionAgent, CollectionCase
from app.engine.escalation import EscalationAction, evaluate as escalate
from app.engine.state_machine import (
    CollectionState,
    InvalidCollectionTransitionError,
    transition,
)

logger = logging.getLogger(__name__)


class CollectionService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Open a new collection case
    # ------------------------------------------------------------------

    async def open_case(
        self,
        *,
        loan_id: str,
        borrower_id: str,
        days_past_due: int,
        outstanding_balance_kobo: int,
    ) -> CollectionCase:
        """
        Open a collection case for a defaulted loan.

        Idempotent — if a case already exists for this loan_id, returns it
        unchanged (the loan.defaulted event may be delivered more than once).
        """
        existing = await self._get_case_by_loan(loan_id)
        if existing:
            logger.info("Collection case already exists for loan %s — skipping", loan_id)
            return existing

        case = CollectionCase(
            loan_id=loan_id,
            borrower_id=borrower_id,
            state=CollectionState.OPEN,
            days_past_due=days_past_due,
            outstanding_balance_kobo=outstanding_balance_kobo,
        )
        self._db.add(case)

        activity = CollectionActivity(
            case_id=case.id,
            activity_type="case_opened",
            to_state=CollectionState.OPEN.value,
            notes=f"Case opened automatically. DPD={days_past_due}, balance={outstanding_balance_kobo}",
        )
        self._db.add(activity)
        await self._db.commit()

        logger.info("Opened collection case %s for loan %s (DPD=%d)", case.id, loan_id, days_past_due)
        return case

    # ------------------------------------------------------------------
    # Assign agent
    # ------------------------------------------------------------------

    async def assign_agent(
        self,
        *,
        loan_id: str,
        agent_id: str | None = None,   # None = auto-assign lowest caseload
        actor_id: str = "system",
    ) -> CollectionCase:
        """
        Assign a human collections agent to an open case.

        If agent_id is None, picks the active agent with the lowest caseload.
        """
        case = await self._require_case(loan_id)
        transition(case.state, CollectionState.AGENT_ASSIGNED)

        if agent_id is None:
            agent = await self._pick_available_agent()
            if agent is None:
                raise RuntimeError("No available collections agents in the queue")
            agent_id = str(agent.id)
            agent.active_case_count += 1

        from_state = case.state
        case.state = CollectionState.AGENT_ASSIGNED
        case.assigned_agent_id = agent_id

        self._db.add(CollectionActivity(
            case_id=case.id,
            activity_type="agent_assigned",
            from_state=from_state.value,
            to_state=case.state.value,
            actor_id=actor_id,
            notes=f"Agent {agent_id} assigned",
        ))
        await self._db.commit()
        return case

    # ------------------------------------------------------------------
    # Record promise to pay
    # ------------------------------------------------------------------

    async def record_promise(
        self,
        *,
        loan_id: str,
        promise_date: str,        # ISO date string e.g. "2025-05-15"
        promise_amount_kobo: int,
        actor_id: str = "system",
    ) -> CollectionCase:
        """Record a borrower promise-to-pay commitment."""
        case = await self._require_case(loan_id)
        transition(case.state, CollectionState.PROMISE_TO_PAY)

        from_state = case.state
        case.state = CollectionState.PROMISE_TO_PAY
        case.promise_to_pay_date = promise_date
        case.promise_to_pay_amount_kobo = promise_amount_kobo

        self._db.add(CollectionActivity(
            case_id=case.id,
            activity_type="promise_recorded",
            from_state=from_state.value,
            to_state=case.state.value,
            actor_id=actor_id,
            notes=f"Promise to pay ₦{promise_amount_kobo/100:.2f} by {promise_date}",
        ))
        await self._db.commit()
        return case

    # ------------------------------------------------------------------
    # Mark broken promise
    # ------------------------------------------------------------------

    async def mark_broken_promise(
        self,
        *,
        loan_id: str,
        actor_id: str = "system",
    ) -> CollectionCase:
        """Called when a promise-to-pay date passes with no payment."""
        case = await self._require_case(loan_id)
        transition(case.state, CollectionState.BROKEN_PROMISE)

        from_state = case.state
        case.state = CollectionState.BROKEN_PROMISE

        self._db.add(CollectionActivity(
            case_id=case.id,
            activity_type="promise_broken",
            from_state=from_state.value,
            to_state=case.state.value,
            actor_id=actor_id,
            notes=f"Promise to pay by {case.promise_to_pay_date} was not fulfilled",
        ))
        await self._db.commit()
        return case

    # ------------------------------------------------------------------
    # Refer to legal
    # ------------------------------------------------------------------

    async def refer_to_legal(
        self,
        *,
        loan_id: str,
        actor_id: str = "system",
        notes: str = "",
    ) -> CollectionCase:
        """Escalate a case to the legal team."""
        case = await self._require_case(loan_id)
        transition(case.state, CollectionState.LEGAL)

        from_state = case.state
        case.state = CollectionState.LEGAL

        self._db.add(CollectionActivity(
            case_id=case.id,
            activity_type="legal_referral",
            from_state=from_state.value,
            to_state=case.state.value,
            actor_id=actor_id,
            notes=notes or f"Referred to legal at DPD={case.days_past_due}",
        ))
        await self._db.commit()
        return case

    # ------------------------------------------------------------------
    # Record recovery
    # ------------------------------------------------------------------

    async def record_recovery(
        self,
        *,
        loan_id: str,
        recovered_amount_kobo: int,
        actor_id: str = "system",
        notes: str = "",
    ) -> CollectionCase:
        """Record a payment and close the case as recovered."""
        case = await self._require_case(loan_id)
        transition(case.state, CollectionState.RECOVERED)

        from_state = case.state
        case.state = CollectionState.RECOVERED
        case.recovered_amount_kobo = recovered_amount_kobo
        case.resolved_at = datetime.now(timezone.utc)

        # Decrement agent caseload
        if case.assigned_agent_id:
            await self._decrement_agent_caseload(case.assigned_agent_id)

        self._db.add(CollectionActivity(
            case_id=case.id,
            activity_type="recovery_recorded",
            from_state=from_state.value,
            to_state=case.state.value,
            actor_id=actor_id,
            notes=notes or f"Recovered ₦{recovered_amount_kobo/100:.2f}",
        ))
        await self._db.commit()
        logger.info("Case %s recovered: ₦%s", case.id, recovered_amount_kobo / 100)
        return case

    # ------------------------------------------------------------------
    # Write off
    # ------------------------------------------------------------------

    async def write_off(
        self,
        *,
        loan_id: str,
        actor_id: str = "system",
        notes: str = "",
    ) -> CollectionCase:
        """Close a case with no recovery expected."""
        case = await self._require_case(loan_id)
        transition(case.state, CollectionState.WRITTEN_OFF)

        from_state = case.state
        case.state = CollectionState.WRITTEN_OFF
        case.resolved_at = datetime.now(timezone.utc)

        if case.assigned_agent_id:
            await self._decrement_agent_caseload(case.assigned_agent_id)

        self._db.add(CollectionActivity(
            case_id=case.id,
            activity_type="written_off",
            from_state=from_state.value,
            to_state=case.state.value,
            actor_id=actor_id,
            notes=notes or f"Written off at DPD={case.days_past_due}",
        ))
        await self._db.commit()
        logger.info("Case %s written off (DPD=%d)", case.id, case.days_past_due)
        return case

    # ------------------------------------------------------------------
    # Escalation check (called by daily worker)
    # ------------------------------------------------------------------

    async def escalate_if_needed(
        self,
        *,
        loan_id: str,
        current_dpd: int,
    ) -> str:
        """
        Evaluate escalation ladder and apply the recommended action if the
        case hasn't already been escalated beyond it.

        Returns a string describing the action taken (or skipped).
        """
        case = await self._require_case(loan_id)

        if case.is_terminal:
            return "skipped: case is terminal"

        # Update DPD
        case.days_past_due = current_dpd

        result = escalate(current_dpd)

        if result.action == EscalationAction.AGENT_REQUIRED and case.state == CollectionState.OPEN:
            await self._db.commit()   # save DPD update first
            await self.assign_agent(loan_id=loan_id)
            return f"agent_assigned at DPD={current_dpd}"

        if result.action == EscalationAction.LEGAL_NOTICE and case.state in (
            CollectionState.OPEN, CollectionState.AGENT_ASSIGNED, CollectionState.BROKEN_PROMISE
        ):
            await self._db.commit()
            await self.refer_to_legal(loan_id=loan_id, notes=f"Auto-escalated at DPD={current_dpd}")
            return f"legal_referral at DPD={current_dpd}"

        await self._db.commit()
        return f"no_change: action={result.action.value} state={case.state.value}"

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_case(self, loan_id: str) -> CollectionCase | None:
        return await self._get_case_by_loan(loan_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_case_by_loan(self, loan_id: str) -> CollectionCase | None:
        result = await self._db.execute(
            select(CollectionCase).where(CollectionCase.loan_id == loan_id)
        )
        return result.scalar_one_or_none()

    async def _require_case(self, loan_id: str) -> CollectionCase:
        case = await self._get_case_by_loan(loan_id)
        if case is None:
            raise ValueError(f"No collection case found for loan {loan_id!r}")
        return case

    async def _pick_available_agent(self) -> CollectionAgent | None:
        from app.core.config import get_settings
        settings = get_settings()
        result = await self._db.execute(
            select(CollectionAgent)
            .where(
                CollectionAgent.is_active == True,  # noqa: E712
                CollectionAgent.active_case_count < settings.max_cases_per_agent,
            )
            .order_by(CollectionAgent.active_case_count.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _decrement_agent_caseload(self, agent_id: str) -> None:
        result = await self._db.execute(
            select(CollectionAgent).where(CollectionAgent.id == uuid.UUID(agent_id))
        )
        agent = result.scalar_one_or_none()
        if agent and agent.active_case_count > 0:
            agent.active_case_count -= 1
