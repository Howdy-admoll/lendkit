"""Collections Service — API Schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.engine.state_machine import CollectionState


class CollectionCaseOut(BaseModel):
    id: uuid.UUID
    loan_id: str
    borrower_id: str
    state: CollectionState
    days_past_due: int
    outstanding_balance_kobo: int
    assigned_agent_id: str | None
    promise_to_pay_date: str | None
    promise_to_pay_amount_kobo: int
    recovered_amount_kobo: int
    opened_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class AssignAgentIn(BaseModel):
    agent_id: str | None = None   # None = auto-assign


class RecordPromiseIn(BaseModel):
    promise_date: str             # ISO date "YYYY-MM-DD"
    promise_amount_kobo: int


class RecordRecoveryIn(BaseModel):
    recovered_amount_kobo: int
    notes: str = ""


class WriteOffIn(BaseModel):
    notes: str = ""


class CollectionActivityOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    activity_type: str
    from_state: str | None
    to_state: str | None
    actor_id: str
    notes: str
    created_at: datetime

    model_config = {"from_attributes": True}
